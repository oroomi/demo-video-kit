#!/usr/bin/env python3
"""Record takes.
  record.py live  --question "Tell me about Since Labs" --take live1 [--mode stub|type|real] [--mock] [--hero 2.0]
  record.py shot  --module shots/jx_proof.py --names P1,P2
Output goes to out/<profile>/ : <take>.mkv (picture + sound), <take>.marks.json, <take>.live.json (live takes), question.wav."""
import argparse, importlib.util, json, pathlib, sys, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dvkit import actions, question as Q, voice
from dvkit.mock import mock_aava
from dvkit.session import Session


def load_profile(path):
    return json.loads(pathlib.Path(path).read_text())


def cmd_live(a):
    prof = load_profile(a.profile)
    out = pathlib.Path(a.out or ROOT / "out" / prof["name"])
    out.mkdir(parents=True, exist_ok=True)
    qwav = out / "question.wav"
    qmeta = Q.make_question(a.question, qwav, a.question_source, lead=a.lead)
    print(f"question audio: {qmeta['source']}, speech {qmeta['speech_s']} s, total {qmeta['total_s']} s", file=sys.stderr)
    mock = None
    if a.mock:
        mock = mock_aava(a.mock_answer, a.mock_mp3)
        print("MOCK: no live model or TTS calls; this take cannot be assembled without --allow-mock", file=sys.stderr)
    url = a.url or prof["url"]
    with Session(a.take, out, size=a.size, question_wav=qwav, sr_stub=(a.mode == "stub"), cursor=prof.get("cursor", "#00E5D4"),
                 theme=prof.get("theme"), mock=mock) as s:
        s.goto(url)
        s.start_recording()
        s.mark("hero_start")
        time.sleep(a.hero)
        res = voice.live_voice_moment(s, prof, a.question, qmeta, mode=a.mode, hold_after=a.hold,
                                      log=lambda m: print(m, file=sys.stderr))
        res["mock"] = bool(a.mock)
        res["take"] = a.take
        res["t_hero_start"] = [m["t"] for m in s.marks if m["name"] == "hero_start"][0]
        s.page.screenshot(path=str(out / f"{a.take}_end.png"))
        s.mark("end")
        meta = s.stop_recording()
    (out / f"{a.take}.live.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: res[k] for k in ("mode", "final_state", "answer_text", "mock")}, indent=1))
    print("take:", out / f"{a.take}.mkv")


def cmd_shot(a):
    prof = load_profile(a.profile)
    out = pathlib.Path(a.out or ROOT / "out" / prof["name"])
    out.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location("shots_mod", a.module)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    base = a.base or prof["url"].split("/?")[0].rstrip("/")
    for name in a.names.split(","):
        fn, path = mod.SHOTS[name]
        with Session(name, out, size=a.size, sr_stub=False, cursor=prof.get("cursor", "#00E5D4"), theme=prof.get("theme")) as s:
            s.goto(base + path)
            s.start_recording()
            tl = actions.TL()
            m = {"shot": name}
            fn(s.page, tl, m)
            s.mark("shot_end", m)
            s.page.screenshot(path=str(out / f"{name}_end.png"))
            s.stop_recording()
        (out / f"{name}.shot.json").write_text(json.dumps(m, indent=1))
        print("shot", name, "done", m)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", default=str(ROOT / "profiles/jx.json"))
    common.add_argument("--out")
    common.add_argument("--size")
    lv = sub.add_parser("live", parents=[common])
    lv.add_argument("--question", required=True)
    lv.add_argument("--take", default="live1")
    lv.add_argument("--mode", choices=["stub", "type", "real"], default="stub")
    lv.add_argument("--question-source", default="auto", help="auto | piper | espeak | path to your own recording")
    lv.add_argument("--url")
    lv.add_argument("--hero", type=float, default=2.0, help="seconds of hero screen before the mic is clicked")
    lv.add_argument("--hold", type=float, default=3.0, help="seconds to hold after the reply ends")
    lv.add_argument("--lead", type=float, default=0.9, help="silence before the question words (s)")
    lv.add_argument("--mock", action="store_true", help="rehearse with fixtures: no live model or TTS calls")
    lv.add_argument("--mock-mp3", default="/root/hack/video_palette/seg2.mp3")
    lv.add_argument("--mock-answer", default="Since Labs is a Finnish early-stage company in the radar. This is a rehearsal fixture, not a live answer.")
    lv.set_defaults(fn=cmd_live)
    sh = sub.add_parser("shot", parents=[common])
    sh.add_argument("--module", required=True)
    sh.add_argument("--names", required=True)
    sh.add_argument("--base")
    sh.set_defaults(fn=cmd_shot)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
