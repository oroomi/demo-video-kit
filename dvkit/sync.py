"""Find the slate (magenta flash + 1 kHz beep) in a take and report where each landed on the recording's own timeline.
flash_t = first video frame that is magenta; beep_t = first sound above the noise floor.  av_skew = beep_t - flash_t (seconds):
how far the sound path runs behind (+) or ahead (-) of the picture in this capture.  assemble shifts the audio by -av_skew."""
import json, re, subprocess, sys


def _ff(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def duration(mkv):
    r = _ff(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mkv)])
    return float(r.stdout.strip())


def _flashes(mkv):
    """Start time of each flash event (video clock): a flash is a run of frames whose mean V chroma exceeds 200 (the full-screen magenta slate has V=234; ordinary pages sit near 128)."""
    r = _ff(["ffmpeg", "-hide_banner", "-i", str(mkv), "-an", "-vf",
             "scale=48:27,signalstats,metadata=print:key=lavfi.signalstats.VAVG:file=-", "-f", "null", "-"])
    events, tt, last = [], None, None
    for line in r.stdout.splitlines():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            tt = float(m.group(1))
        m = re.search(r"VAVG=([0-9.]+)", line)
        if m and tt is not None and float(m.group(1)) > 200:
            if last is None or tt - last > 0.5:
                events.append(tt)
            last = tt
    return events


def sound_bursts(mkv, noise="-35dB", d=0.04):
    """[(start, end)] of every stretch of sound on the audio clock."""
    r = _ff(["ffmpeg", "-hide_banner", "-nostats", "-i", str(mkv), "-vn", "-af", f"silencedetect=noise={noise}:d={d}", "-f", "null", "-"])
    ev = [(m.group(1), float(m.group(2))) for m in re.finditer(r"silence_(start|end): ([0-9.]+)", r.stderr)]
    out, cur = [], None
    for kind, t in ev:
        if kind == "end":
            cur = t
        elif kind == "start" and cur is not None:
            out.append((cur, t)); cur = None
    if cur is not None:
        out.append((cur, duration(mkv)))
    return out


def analyze(mkv):
    """Start slate and end slate: where the flash (picture) and the beep (sound) each landed on the tape, and the skew between them.
    skew > 0: the sound sits later than the picture; < 0: earlier.  drift = skew_end - skew_start (should be about 0)."""
    D = duration(mkv)
    fl = _flashes(mkv)
    allb = [x for x in sound_bursts(mkv) if x[1] - x[0] >= 0.06]    # ignore clicks at the very edges of the capture
    # nothing is audible before the start slate or after the end slate, so they are the first and the last bursts on the tape
    b0 = allb[0][0] if allb and 0.08 <= allb[0][1] - allb[0][0] <= 0.8 else None
    b1 = allb[-1][0] if len(allb) > 1 and 0.08 <= allb[-1][1] - allb[-1][0] <= 0.8 else None
    f0 = fl[0] if fl else None
    f1 = fl[-1] if len(fl) > 1 else None
    r = lambda x: None if x is None else round(x, 3)
    sk0 = None if f0 is None or b0 is None else round(b0 - f0, 3)
    sk1 = None if f1 is None or b1 is None else round(b1 - f1, 3)
    return {"duration": round(D, 3), "flash_start": r(f0), "beep_start": r(b0), "skew_start": sk0,
            "flash_end": r(f1), "beep_end": r(b1), "skew_end": sk1,
            "drift": None if sk0 is None or sk1 is None else round(sk1 - sk0, 3)}


if __name__ == "__main__":
    print(json.dumps(analyze(sys.argv[1]), indent=1))
