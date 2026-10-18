#!/usr/bin/env python3
"""Self-test of the studio in about 12 s: records a page that plays a 440 Hz tone, then checks that sound, picture, frame rate and the slate are all on tape.
Prints PASS/FAIL per check.  Run it before every real take:  ./demo-video doctor"""
import json, pathlib, re, shutil, subprocess, sys, time, urllib.parse

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dvkit import stack, sync
from dvkit.session import Session

PAGE = """<body style='margin:0;background:#021B44;color:#fff;font:64px sans-serif'><h1 style='margin:40px'>doctor</h1>
<div style='width:120px;height:120px;background:#0ee;position:absolute;top:400px;animation:m 2s linear infinite alternate'></div>
<style>@keyframes m{from{left:0}to{left:1600px}}</style>
<script>window.tone=()=>{const a=new AudioContext();const o=a.createOscillator();o.frequency.value=440;const g=a.createGain();g.gain.value=0.3;o.connect(g);g.connect(a.destination);o.start();setTimeout(()=>o.stop(),2500);};</script>"""


def main():
    ok = True
    def check(name, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    for b in ("Xvfb", "pulseaudio", "pactl", "paplay", "ffmpeg", "ffprobe", "espeak-ng", "xdotool"):
        check(f"binary {b}", shutil.which(b) is not None)
    out = ROOT / "out" / "doctor"
    shutil.rmtree(out, ignore_errors=True)
    stack.up(verbose=False)
    with Session("doctor", out, sr_stub=False) as s:
        s.page.goto("data:text/html;charset=utf-8," + urllib.parse.quote(PAGE))
        time.sleep(0.5)
        s.start_recording()
        s.page.evaluate("tone()")
        for _ in range(4):               # extra pulses while the page animates: proves the capture clock holds under load
            time.sleep(1.2)
            s.page.evaluate("window.__dv.slate()")
        time.sleep(0.6)
        meta = s.stop_recording()
    mkv = out / "doctor.mkv"
    check("recording exists", mkv.exists() and mkv.stat().st_size > 50000, f"{mkv.stat().st_size // 1024} KiB" if mkv.exists() else "")
    r = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames,width,height", "-of", "json", str(mkv)], capture_output=True, text=True)
    st = json.loads(r.stdout)["streams"][0]
    check("picture 1920x1080 at ~30 fps", st["width"] == 1920 and st["height"] == 1080 and int(st["nb_read_frames"]) >= 3.2 * 28, f"{st['nb_read_frames']} frames")
    v = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(mkv), "-af", "volumedetect", "-vn", "-f", "null", "-"], capture_output=True, text=True).stderr
    mx = re.search(r"max_volume: (-?[0-9.]+) dB", v)
    check("browser sound reached the tape", mx and float(mx.group(1)) > -30, f"max {mx.group(1)} dB" if mx else "no audio")
    a = sync.analyze(mkv)
    check("capture kept up with the wall clock (lost under 0.6 s)", meta["capture_lost_s"] is not None and meta["capture_lost_s"] < 0.6, f"lost {meta['capture_lost_s']} s")
    check("start slate found (flash + beep)", a["skew_start"] is not None, f"flash {a['flash_start']} s, beep {a['beep_start']} s")
    check("end slate found (flash + beep)", a["skew_end"] is not None, f"flash {a['flash_end']} s, beep {a['beep_end']} s")
    check("skew stable across the take (drift under 60 ms)", a["drift"] is not None and abs(a["drift"]) < 0.06, f"start {a['skew_start']} s, end {a['skew_end']} s, drift {a['drift']} s")
    print(f"note: the capture runs with a constant picture/sound skew of {a['skew_start']} s; assemble removes it automatically")
    print("doctor:", "ALL PASS" if ok else "PROBLEMS FOUND (see README troubleshooting)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
