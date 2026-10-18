#!/usr/bin/env python3
"""One command: studio up -> self-test -> live voice take -> proof shots -> assemble -> review frames.
  ./demo-video all --question "Tell me about Since Labs" --proof "P1:Every claim links back to a public record" [--module shots/jx_proof.py]
Use --mock to rehearse without spending live model or TTS calls (the result is then flagged and assembled with --allow-mock)."""
import argparse, pathlib, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable


def sh(*cmd):
    print("\n$", " ".join(str(c) for c in cmd), file=sys.stderr)
    r = subprocess.run([str(c) for c in cmd], cwd=ROOT, env={**__import__("os").environ, "PYTHONPATH": str(ROOT)})
    if r.returncode:
        raise SystemExit(f"step failed: {cmd[:3]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", required=True)
    ap.add_argument("--profile", default=str(ROOT / "profiles/jx.json"))
    ap.add_argument("--module", default=str(ROOT / "shots/jx_proof.py"))
    ap.add_argument("--proof", default="", help='"P1:caption,P2:caption"')
    ap.add_argument("--name", default="demo")
    ap.add_argument("--take", default="live1")
    ap.add_argument("--out")
    ap.add_argument("--mode", default="stub", choices=["stub", "type", "real"])
    ap.add_argument("--question-source", default="auto")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--no-vertical", action="store_true")
    ap.add_argument("--skip-doctor", action="store_true")
    ap.add_argument("--assemble-args", default="", help="extra args for assemble.py, e.g. '--proof-s 12 --think-cap 3'")
    a = ap.parse_args()
    import json
    prof = json.loads(pathlib.Path(a.profile).read_text())
    out = a.out or str(ROOT / "out" / prof["name"])
    sh(PY, "-m", "dvkit.stack", "up")
    if not a.skip_doctor:
        for attempt in (1, 2, 3):   # a shared machine can be starved for a moment; the gate must pass on a quiet moment, not once
            r = subprocess.run([PY, "dvkit/doctor.py"], cwd=ROOT, env={**__import__("os").environ, "PYTHONPATH": str(ROOT)})
            if r.returncode == 0:
                break
            if attempt == 3:
                raise SystemExit("doctor failed 3 times: see README troubleshooting (load: " + open("/proc/loadavg").read().split()[0] + ")")
            print(f"doctor attempt {attempt} failed (load {open('/proc/loadavg').read().split()[0]}); retrying in 15 s", file=sys.stderr)
            time.sleep(15)
    live = [PY, "dvkit/record.py", "live", "--profile", a.profile, "--out", out, "--take", a.take, "--question", a.question,
            "--mode", a.mode, "--question-source", a.question_source]
    if a.mock:
        live.append("--mock")
    sh(*live)
    names = [p.partition(":")[0] for p in a.proof.split(",") if p]
    for n in names:
        sh(PY, "dvkit/record.py", "shot", "--profile", a.profile, "--out", out, "--module", a.module, "--names", n)
    asm = [PY, "dvkit/assemble.py", "--profile", a.profile, "--out", out, "--take", a.take, "--name", a.name]
    if a.proof:
        asm += ["--proof", a.proof]
    if a.mock:
        asm.append("--allow-mock")
    if a.no_vertical:
        asm.append("--no-vertical")
    asm += a.assemble_args.split()
    sh(*asm)
    sh(PY, "dvkit/frames.py", str(pathlib.Path(out) / f"{a.name}.mp4"))
    print(f"\nDONE: {out}/{a.name}.mp4  (+ _vertical.mp4 unless --no-vertical, .srt, .proof.json)  review sheet: {out}/{a.name}_frames/sheet.png")


if __name__ == "__main__":
    main()
