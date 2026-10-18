# demo-video: record the REAL live voice interaction for a hackathon video

Built after JunctionX Turku (lost): our video was screen footage with a separate narrator, so judges never saw the voice
assistant ("Aava") actually talking. This kit records one browser session as **picture + the assistant's real voice + our
spoken question, in sync**, then cuts it into a captioned 1920x1080 video (and a 9:16 cut) with the assistant speaking in the
first seconds. Works on a headless Linux VPS: no GPU, no screen, no sound card.

```
Chromium (headed, Xvfb :99) --sound--> PulseAudio null sink "dv_out" --\
        |                                                              >-- ffmpeg --> take.mkv  (picture + sound, one file)
        +--picture--> x11grab ----------------------------------------/
our question: WAV -> Chromium fake microphone (the orb moves to it)  +  paplay into dv_out (audible on tape)
sync: a magenta flash + 1 kHz beep (the "slate") at the start and end of every take; assemble measures and removes the skew
```

## One command

```bash
cd /root/hack/kits/demo-video
./demo-video all --question "Tell me about Since Labs" --proof "P1:Every claim links back to a public record"
# -> out/jx/demo.mp4  out/jx/demo_vertical.mp4  out/jx/demo.srt  out/jx/demo.proof.json  out/jx/demo_frames/sheet.png
```

`all` = studio up, self-test (`doctor`), one live voice take, the proof shots, assemble, review frames. Add `--mock` to rehearse
with fixtures (no live model or TTS cost; the result is flagged and cannot be assembled without `--allow-mock`).
The live take speaks to the real site, so it spends a real model call and about 300-400 characters of TTS: keep it to 3 takes.

Step by step:

```bash
./demo-video up                                   # Xvfb :99 + PulseAudio (idempotent; stack state in /run/demovideo)
./demo-video doctor                               # 12 s self-test, must print ALL PASS before a real take
./demo-video live --question "Tell me about Since Labs" --take live1 --out out/jx     # the live voice moment
./demo-video shot --module shots/jx_proof.py --names P1,P2 --out out/jx               # scripted proof shots (no voice)
./demo-video assemble --take live1 --proof "P1:Every claim links back to a public record" --name demo --out out/jx
./demo-video frames out/jx/demo.mp4 --every 5      # contact sheet to review
./demo-video down                                  # stops only the PIDs this kit started
```

Assemble options: `--hook-text`, `--hook-len`, `--title-s`, `--end-s`, `--proof-s`, `--think-cap` (longest thinking gap kept at real
speed, longer is sped up and labelled with the real wait), `--no-vertical`, `--max-mb`, `--allow-mock`.

## What it produces

| File | What |
|---|---|
| `<name>.mp4` | 1920x1080, 30 fps, H.264 + AAC 160k, -16 LUFS, under 50 MB (re-encoded to fit if needed) |
| `<name>_vertical.mp4` | 1080x1920 cut: live moment zoomed on the voice stage, proof shots stacked on a blurred fill, large captions; same audio |
| `<name>.srt` | captions |
| `<name>.proof.json` | numbers: first voice time, final audio vs edit list (ms), raw capture skew and drift, page-to-tape latency, volumes |
| `<take>.mkv`, `.marks.json`, `.live.json`, `.sync.json` | the raw take (kept: re-assemble any time), the timeline of what the page did, the question/answer facts, slate analysis |

Structure of the video (details and the 2-minute version: `templates/SHOTLIST.md`): hook (assistant already speaking), title card,
live moment (mic click, our question, the real reply), proof shots, transfer line + end card with URL and QR.

## What works for the question audio (tested on this VPS, Playwright 1.60 Chromium)

1. **Fake microphone from a file: works.** `--use-fake-device-for-media-stream --use-fake-ui-for-media-stream --use-file-for-fake-audio-capture=q.wav%noloop`.
   `getUserMedia` resolves, the site's orb analyser moves with our question. The WAV has 0.9 s of lead silence so the mic opening
   and the words do not need to be aligned to the millisecond.
2. **Real Web Speech API: does NOT work here.** The constructor exists, `start()` fires, then it errors immediately with
   `audio-capture` ("No microphone was found"): the recogniser ignores the fake device and finds no hardware input. Playwright's
   Chromium also has no Google speech key, so it would fail with `network` anyway. On a real laptop with Chrome it works; record there if you need the true recogniser.
3. **What the kit does (mode `stub`, default):** a stand-in `SpeechRecognition` (in `dvkit/inject.js`, injected only into the recording
   browser) emits the known question word by word over the length of the question audio, then a final result. The **site's own voice
   flow runs unchanged**: live transcript, the 1.5 s pause, send, "thinking", the model, the real ElevenLabs reply, the orb. The
   question audio itself is also played into the recording sink with `paplay`, so it is audible on tape.
4. **Fallback (mode `type`):** open voice mode, use "Type instead", type the question at the pace of the question audio (also played into the tape).
5. `--mode real` exists only to reproduce the failure in 3 above.

The reply audio is never faked: it is whatever the browser plays, captured from the PulseAudio sink the browser outputs to.

Question voice: your own recording is best (`--question-source path/to/me.wav`). Default is Piper neural TTS (offline, free;
voice `en_US-ryan-medium`), falling back to espeak-ng. The question text on screen and in captions is the text you pass, not a recognition result.
**Say so when you submit** (e.g. in DISCLOSURE: "voice input was a pre-recorded question; speech recognition was stubbed for headless capture; the answer and its voice are the live system").

## Requirements

Ubuntu 24.04 (tested), root (PulseAudio runs `--system`; a per-user daemon is not implemented). Free system packages:

```bash
apt-get install -y xvfb pulseaudio pulseaudio-utils ffmpeg espeak-ng xdotool     # ffmpeg needs libx264, x11grab, libpulse (Ubuntu's has them)
pip install playwright pillow qrcode && playwright install chromium
# optional, nicer question voice (offline):
python3 -m venv .venv-tts && .venv-tts/bin/pip install piper-tts
mkdir -p assets/voices && curl -L -o assets/voices/en_US-ryan-medium.onnx      https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/medium/en_US-ryan-medium.onnx
curl -L -o assets/voices/en_US-ryan-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/medium/en_US-ryan-medium.onnx.json
```

Needs no keys: the live site already has its own. The kit never reads any .env or key file.
Environment: `DV_DISPLAY` (default `:99`), `DV_SIZE` (`1920x1080`; changing it needs `down` then `up`), `DV_RUN` (`/run/demovideo`),
`DV_PA_DIR` (`/run/demovideo-pa`, must be outside `/root` because user `pulse` writes the socket there). No network port is used.

## Adapting to another site

Copy `profiles/jx.json`, change `url`, the `voice` selectors (mic button, overlay + its state attribute, transcript, answer text,
type-instead button and input), card text/colours, `qr`, and `perf_css`. Write proof shots like `shots/jx_proof.py`
(`SHOTS = {name: (fn(page, tl, m), path)}`, helpers in `dvkit/actions.py`: paced scroll, cursor ring + click, typed input).
If the site's voice UI works differently, change `dvkit/voice.py` (about 100 lines).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `display :99 is taken by a process this kit did not start` | Set `DV_DISPLAY=:98` or free it. Never pkill by pattern: stop the PID. |
| doctor: "browser sound reached the tape" FAIL | PulseAudio down or Chromium not on it: `./demo-video status`; `PULSE_SERVER=unix:/run/demovideo-pa/native pactl list short sinks` must show `dv_out`. The kit removes `--mute-audio` and sets `PULSE_SERVER` for the browser. |
| `WARNING: the capture lost N s ... CPU starved` | ffmpeg could not keep up (this VPS has 2 shared vCPUs). Re-record when `uptime` load is under 2. The kit already runs ffmpeg at nice -10 and the browser at +6. Last resort: `DV_SIZE=1280x720`. |
| Picture is a slideshow (a few fps) | Software rendering cannot animate a full-screen `backdrop-filter`. The profile's `perf_css` drops it for the recording (7 fps became 58 fps; the overlay is 88% opaque so it looks the same). `--faithful` turns this off. |
| assemble: `no slate found` | The take was not recorded with the kit (`start_recording` fires the slate). Re-record. |
| assemble: `MOCK rehearsal ... refusing` | Mock takes are not allowed into a real video. Re-record without `--mock`, or `--allow-mock` for pipeline tests only. |
| assemble: `no completed reply` | The assistant errored or timed out. Check `<take>.live.json` (`final_state`, `answer_text`) and `https://<site>/api/.../status`. |
| Question captions fine but the orb does not move | Fake mic file must be WAV PCM 16-bit; keep `%noloop`; check `.marks.json` for `gum_open`. |
| State goes to `error` immediately in voice mode | You are in `--mode real`: the real recogniser cannot work headless (see above). Use `stub` or `type`. |
| Skew changes between takes (e.g. -0.17 s, -0.45 s, -1.6 s) | Normal: the sound input opens a variable time after the picture input. The slate measures it per take and assemble removes it; `drift_s` (start vs end of take) is what matters, typically under 100 ms. |
| `Permission denied` creating the PulseAudio socket | `DV_PA_DIR` is inside `/root`. Use `/run/...`. |

Studio leftovers: `./demo-video down` stops Xvfb and PulseAudio by recorded PID only. A crashed take can leave a Chromium; find it by
PID (`ps -eo pid,args | grep dvprof-`) and `kill <pid>`.

## Layout

```
demo-video            entry point (bash)
dvkit/stack.py        Xvfb + PulseAudio lifecycle (PIDs tracked)      dvkit/session.py   one take: browser + ffmpeg + slate
dvkit/inject.js       page-side marks, cursor ring, slate, SR stand-in   dvkit/voice.py     the live voice moment
dvkit/question.py     question WAV (own recording / Piper / espeak)     dvkit/sync.py      slate analysis (flash + beep)
dvkit/record.py       CLI: live, shot                                   dvkit/assemble.py  edit, captions, loudnorm, vertical, proof.json
dvkit/doctor.py       self-test                                         dvkit/make.py      the one-command pipeline
dvkit/mock.py         rehearsal fixtures                                dvkit/frames.py    review contact sheet
profiles/jx.json      site profile (selectors, cards, perf CSS)         shots/jx_proof.py  scripted proof shots
templates/SHOTLIST.md the 2-minute structure, timing rules, checklist
```
