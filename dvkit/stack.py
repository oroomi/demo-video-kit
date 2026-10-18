"""Virtual studio: Xvfb display + PulseAudio null sinks.  Everything started here is tracked by PID in RUN/pids.json,
and `down` stops only those PIDs (never a pattern kill).

Audio graph (PulseAudio runs in --system mode because root may not run a per-user daemon):
    Chromium  ->  sink "dv_out"   (the browser's speakers; ffmpeg records dv_out.monitor)
    paplay    ->  sink "dv_out"   (our spoken question, played at the right moment, so it lands in the recording too)
    Chromium mic: the fake device (--use-file-for-fake-audio-capture), see browser.py
"""
import json, os, pathlib, signal, subprocess, sys, time

DISPLAY = os.environ.get("DV_DISPLAY", ":99")
SIZE = os.environ.get("DV_SIZE", "1920x1080")
RUN = pathlib.Path(os.environ.get("DV_RUN", "/run/demovideo"))
PA_DIR = pathlib.Path(os.environ.get("DV_PA_DIR", "/run/demovideo-pa"))   # must be outside /root: user `pulse` writes the socket here
PA_SOCK = PA_DIR / "native"
SINK = "dv_out"
PIDS = RUN / "pids.json"


def env(base=None):
    """Environment for every child that must see the studio (browser, ffmpeg, paplay, pactl)."""
    e = dict(os.environ if base is None else base)
    e["DISPLAY"] = DISPLAY
    e["PULSE_SERVER"] = f"unix:{PA_SOCK}"
    e.pop("PULSE_SINK", None); e.pop("PULSE_SOURCE", None)
    e["PULSE_SINK"] = SINK
    return e


def _load():
    try:
        return json.loads(PIDS.read_text())
    except Exception:
        return {}


def _save(d):
    RUN.mkdir(parents=True, exist_ok=True)
    PIDS.write_text(json.dumps(d))


def _alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:   # a zombie is not alive
        return pathlib.Path(f"/proc/{pid}/stat").read_text().split(") ")[1][0] != "Z"
    except Exception:
        return True


def _x_socket():
    return pathlib.Path("/tmp/.X11-unix") / ("X" + DISPLAY.lstrip(":"))


def _pactl(*args, check=True):
    return subprocess.run(["pactl", *args], env=env(), capture_output=True, text=True, check=check)


def up(verbose=True):
    """Start Xvfb and PulseAudio if they are not already ours and running.  Idempotent."""
    RUN.mkdir(parents=True, exist_ok=True)
    PA_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(PA_DIR, 0o777)
    d = _load()
    log = lambda m: print("[stack]", m, file=sys.stderr) if verbose else None

    # ---- X display
    if _alive(d.get("xvfb")) and _x_socket().exists():
        log(f"Xvfb {DISPLAY} already up (pid {d['xvfb']})")
    else:
        if _x_socket().exists():
            raise SystemExit(f"display {DISPLAY} is taken by a process this kit did not start ({_x_socket()}). "
                             f"Set DV_DISPLAY=:98 (or free it) and retry.")
        p = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", f"{SIZE}x24", "-nolisten", "tcp", "-ac"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        d["xvfb"] = p.pid
        for _ in range(50):
            if _x_socket().exists():
                break
            time.sleep(0.1)
        else:
            raise SystemExit("Xvfb did not come up")
        log(f"Xvfb {DISPLAY} {SIZE} started, pid {p.pid}")

    # ---- PulseAudio (system mode, anonymous socket, one null sink)
    if _alive(d.get("pulse")) and PA_SOCK.exists():
        log(f"PulseAudio already up (pid {d['pulse']})")
    else:
        if PA_SOCK.exists():
            PA_SOCK.unlink()
        p = subprocess.Popen(
            ["pulseaudio", "--system", "--daemonize=no", "--disallow-exit", "--exit-idle-time=-1", "--disable-shm=yes", "-n",
             "-L", f"module-native-protocol-unix socket={PA_SOCK} auth-anonymous=1",
             "-L", f"module-null-sink sink_name={SINK} rate=48000 channels=2 sink_properties=device.description=DemoVideoOut"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        d["pulse"] = p.pid
        for _ in range(60):
            if PA_SOCK.exists() and _pactl("info", check=False).returncode == 0:
                break
            time.sleep(0.1)
        else:
            raise SystemExit("PulseAudio did not come up")
        _pactl("set-default-sink", SINK)
        log(f"PulseAudio started, pid {p.pid}, sink {SINK}")
    _save(d)
    return d


def down(verbose=True):
    """Stop only the PIDs this kit started."""
    d = _load()
    for k in ("xvfb", "pulse"):
        pid = d.get(k)
        if _alive(pid):
            os.kill(pid, signal.SIGTERM)
            for _ in range(30):
                if not _alive(pid):
                    break
                time.sleep(0.1)
            else:
                os.kill(pid, signal.SIGKILL)
            if verbose:
                print(f"[stack] stopped {k} pid {pid}", file=sys.stderr)
    for f in (PA_SOCK, _x_socket()):
        try:
            f.unlink()
        except OSError:
            pass
    try:
        PIDS.unlink()
    except OSError:
        pass


def status():
    d = _load()
    out = {k: {"pid": d.get(k), "alive": _alive(d.get(k))} for k in ("xvfb", "pulse")}
    out["display_socket"] = _x_socket().exists()
    out["pulse_socket"] = PA_SOCK.exists()
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "up":
        up()
    elif cmd == "down":
        down()
    else:
        print(json.dumps(status(), indent=1))
