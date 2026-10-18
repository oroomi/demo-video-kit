#!/usr/bin/env python3
"""Review sheet: a frame every N seconds (default 5) as PNGs plus one contact sheet.
   ./demo-video frames out/jx/demo.mp4 [--every 5] [--cols 4] [--width 480]"""
import argparse, pathlib, subprocess

ap = argparse.ArgumentParser()
ap.add_argument("video")
ap.add_argument("--every", type=float, default=5.0)
ap.add_argument("--cols", type=int, default=4)
ap.add_argument("--width", type=int, default=480)
a = ap.parse_args()
v = pathlib.Path(a.video)
d = v.parent / (v.stem + "_frames")
d.mkdir(exist_ok=True)
dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(v)], capture_output=True, text=True).stdout)
n = int(dur // a.every) + 1
rows = -(-n // a.cols)
run = lambda *c: subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *c], check=True)
run("-i", str(v), "-vf", f"fps=1/{a.every},scale={a.width}:-1,tile={a.cols}x{rows}", "-frames:v", "1", str(d / "sheet.png"))
run("-i", str(v), "-vf", f"fps=1/{a.every}", str(d / "f%03d.png"))
print(d / "sheet.png")
