"""The live voice moment: open the assistant's voice mode, 'say' the question, record the assistant's real spoken reply.

Modes (see README "What works for the question audio"):
  stub  : fake microphone feeds the file to the site (the orb moves to our voice), the question WAV is also played into the
          recording sink, and a stand-in SpeechRecognition (inject.js) emits the known words in time with the audio.  The site's own
          code does everything else: transcript, 1.5 s pause, send, thinking, ElevenLabs reply, orb, word-by-word text.
  type  : voice mode opened, 'Type instead' used; the question is typed at the pace of the question WAV (also played into the recording).
  real  : real Web Speech API, no stand-in.  Fails in Chromium without Google's speech key (error 'network'); kept to document that.
"""
import json, subprocess, time

from . import stack
from .actions import cursor, move_click, type_text


def _state(page, sel, attr):
    return page.evaluate("([s,a]) => { const e = document.querySelector(s); return e ? e.getAttribute(a) : null; }", [sel, attr])


def play_question(wav):
    """Play the question into the recording sink; returns the Popen (we own the PID)."""
    return subprocess.Popen(["paplay", "--device=" + stack.SINK, wav], env=stack.env(),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def live_voice_moment(s, prof, question, qmeta, mode="stub", hold_after=3.0, max_wait=75, log=print):
    """Run the moment on Session `s`.  Returns a dict of the facts assemble needs (all times epoch seconds)."""
    v = prof["voice"]
    page = s.page
    page.evaluate("([a,b,c,d,e]) => { __dv.watchAttr(a,b,'state'); __dv.watchText(c,'answer_text'); __dv.watchText(d,'transcript_text'); }",
                  [v["overlay"], v["state_attr"], v["answer"], v["transcript"], ""])
    res = {"mode": mode, "question": question, "lead_s": qmeta["lead_s"], "speech_s": qmeta["speech_s"], "total_s": qmeta["total_s"]}

    box = page.locator(v["mic_button"]).bounding_box()
    s.mark("mic_move")
    move_click(page, box, move_s=0.8, show=True)
    res["t_mic_click"] = s.mark("mic_click")
    cursor(page, False)

    # wait for the overlay to listen and for the page to open the (fake) microphone
    t_end = time.time() + 6
    while time.time() < t_end and _state(page, v["overlay"], v["state_attr"]) != v["states"]["listening"]:
        time.sleep(0.03)
    t_end = time.time() + 3
    while time.time() < t_end:
        s.drain()
        if any(m["name"] == "gum_open" for m in s.page_marks):
            break
        time.sleep(0.03)

    # the question is spoken: audio into the tape, same file already feeding the fake microphone
    res["t_question_audio"] = s.mark("question_audio_start")
    proc = play_question(qmeta["wav"])
    time.sleep(qmeta["lead_s"])
    if mode == "stub":
        res["t_question_words"] = s.mark("question_words_start")
        ok = page.evaluate("([q,ms]) => __dv.srSay(q, ms)", [question, int(qmeta["speech_s"] * 1000)])
        res["stub_accepted"] = bool(ok)
        if not ok:
            log("WARNING: the speech-recognition stand-in was not listening; falling back to type mode")
            mode = res["mode"] = "type"
    if mode == "type":
        page.locator(v["type_instead"]).click()
        s.mark("type_instead")
        time.sleep(0.25)
        res["t_question_words"] = s.mark("question_words_start")
        page.locator(v["type_input"]).click()
        type_text(page, question, qmeta["speech_s"])
        page.keyboard.press("Enter")
        s.mark("question_sent")
    if mode == "real":
        res["t_question_words"] = s.mark("question_words_start")

    # follow the site: thinking -> speaking -> done
    seen, t0 = [], time.time()
    last = None
    while time.time() - t0 < max_wait:
        st = _state(page, v["overlay"], v["state_attr"])
        if st != last:
            seen.append((round(time.time(), 3), st)); last = st
            log(f"  state -> {st}")
        if st == v["states"]["done"] or st == v["states"]["error"]:
            break
        time.sleep(0.05)
    res["states"] = seen
    res["final_state"] = last
    res["t_done"] = s.mark("moment_done")
    answer = page.evaluate("(s) => (document.querySelector(s)||{}).innerText || ''", v["answer"]).strip()
    res["answer_text"] = answer
    res["transcript_text"] = page.evaluate("(s) => (document.querySelector(s)||{}).innerText || ''", v["transcript"]).strip()
    time.sleep(hold_after)
    res["t_hold_end"] = s.mark("moment_hold_end")
    try:
        proc.wait(timeout=1)
    except Exception:
        pass
    s.drain()
    return res
