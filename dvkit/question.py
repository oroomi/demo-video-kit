"""The spoken question: a WAV with a short lead-in of silence, the words, and a short tail.
Sources: a recording (your own voice: best), Piper neural TTS (offline, free), or espeak-ng (robotic, always installed).
The same file is (a) fed to Chromium's fake microphone so the site's orb really moves to it, and (b) played into the
recording sink so the question is audible on tape."""
import json, pathlib, re, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent.parent
PIPER_PY = HERE / ".venv-tts/bin/python"
PIPER_VOICE = HERE / "assets/voices/en_US-ryan-medium.onnx"


def _run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        raise SystemExit(f"{cmd[0]} failed: {r.stderr[-600:]}")
    return r


def duration(path):
    return float(_run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]).stdout.strip())


def make_question(text, out, source="auto", lead=0.9, tail=0.5, length_scale=1.08):
    """Write `out` (48 kHz mono s16 WAV) and `out`.json.  source: 'auto' | 'piper' | 'espeak' | path to your own recording."""
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = out.with_suffix(".raw.wav")
    src = source
    if source == "auto":
        src = "piper" if (PIPER_PY.exists() and PIPER_VOICE.exists()) else "espeak"
    if src == "piper":
        subprocess.run([str(PIPER_PY), "-m", "piper", "-m", str(PIPER_VOICE), "--length-scale", str(length_scale), "-f", str(raw)],
                       input=text, text=True, capture_output=True, check=True)
    elif src == "espeak":
        _run(["espeak-ng", "-v", "en-us+f3", "-s", "150", "-p", "55", "-w", str(raw), text])
    else:
        raw = pathlib.Path(src)
        if not raw.exists():
            raise SystemExit(f"question recording not found: {src}")
    ms = int(round(lead * 1000))
    af = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,"
          "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,"
          f"loudnorm=I=-18:TP=-2:LRA=7,adelay={ms}|{ms},apad=pad_dur={tail}")
    _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw), "-af", af, "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(out)])
    if src in ("piper", "espeak"):
        raw.unlink(missing_ok=True)
    total = duration(out)
    meta = {"text": text, "source": src, "lead_s": lead, "speech_s": round(total - lead - tail, 3), "total_s": round(total, 3), "wav": str(out)}
    out.with_suffix(".json").write_text(json.dumps(meta, indent=1))
    return meta


if __name__ == "__main__":
    print(make_question(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "auto"))
