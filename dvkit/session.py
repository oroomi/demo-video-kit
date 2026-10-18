"""One recording take: headed Chromium on the Xvfb display, its sound routed to the PulseAudio null sink, and ffmpeg
grabbing picture + sound into one MKV.  Usage:

    with Session("take1", out_dir, question_wav=..., sr_stub=True) as s:
        s.goto("https://example.com/?demo=1")
        s.start_recording()          # slate flash + beep fire here; everything after is on tape
        ... drive s.page ...
    # leaves  take1.mkv  and  take1.marks.json  in out_dir
"""
import json, os, pathlib, shutil, subprocess, sys, tempfile, time

from . import stack

HERE = pathlib.Path(__file__).parent


class Session:
    def __init__(self, name, out_dir, size=None, fps=30, question_wav=None, sr_stub=True, cursor="#00E5D4",
                 init_scripts=(), init_css=None, mock=None, keep_profile=False, extra_args=(), theme=None, locale="en-US"):
        self.name = name
        self.out = pathlib.Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.size = size or stack.SIZE
        self.w, self.h = (int(x) for x in self.size.split("x"))
        self.fps = fps
        self.question_wav = str(question_wav) if question_wav else None
        self.sr_stub = sr_stub
        self.cursor = cursor
        self.init_scripts = list(init_scripts)
        self.init_css = init_css
        self.mock = mock
        self.extra_args = list(extra_args)
        self.theme = theme
        self.locale = locale
        self.marks = []           # harness-side marks (epoch seconds)
        self.page_marks = []      # page-side marks, drained at stop
        self.ff = None
        self._pw = None
        self.ctx = None
        self.page = None
        self.t_rec = None
        self.mkv = self.out / f"{name}.mkv"
        self._profile = None
        self._keep_profile = keep_profile
        self.responses = []

    # ------------------------------------------------------------------ lifecycle
    def __enter__(self):
        from playwright.sync_api import sync_playwright
        stack.up(verbose=False)
        geo = subprocess.run(["xdotool", "getdisplaygeometry"], env=stack.env(), capture_output=True, text=True).stdout.split()
        if geo and f"{geo[0]}x{geo[1]}" != self.size:
            raise SystemExit(f"the X display is {geo[0]}x{geo[1]} but this take wants {self.size}: run `./demo-video down && DV_SIZE={self.size} ./demo-video up`")
        try:
            os.nice(6)      # the browser (and Playwright's driver) inherit this; ffmpeg is started at -10 so the capture clock always wins
        except OSError:
            pass
        self._profile = tempfile.mkdtemp(prefix="dvprof-", dir=str(self.out))
        args = [
            "--kiosk", "--window-position=0,0", f"--window-size={self.w + 1},{self.h + 1}",   # +1: kiosk comes out 1 px short
            "--force-device-scale-factor=1",
            "--autoplay-policy=no-user-gesture-required",
            "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
            "--no-first-run", "--disable-infobars", "--hide-crash-restore-bubble", "--disable-session-crashed-bubble",
            "--disable-features=Translate,MediaRouter", "--password-store=basic", "--use-mock-keychain",
            "--disable-background-timer-throttling", "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows",
        ]
        if self.question_wav:
            args.append(f"--use-file-for-fake-audio-capture={self.question_wav}%noloop")
        args += self.extra_args
        self._pw = sync_playwright().start()
        self.ctx = self._pw.chromium.launch_persistent_context(
            self._profile, headless=False, env=stack.env(), no_viewport=True, locale=self.locale,
            ignore_default_args=["--mute-audio", "--enable-automation"], args=args)
        cfg = {"srStub": bool(self.sr_stub), "cursor": self.cursor}
        self.ctx.add_init_script("window.__DV_CFG = " + json.dumps(cfg) + ";")
        self.ctx.add_init_script((HERE / "inject.js").read_text())
        if self.theme:
            self.ctx.add_init_script(f"try{{localStorage.setItem('theme',{json.dumps(self.theme)})}}catch(e){{}}")
        if self.init_css:   # recording-only CSS (e.g. drop backdrop-filter: software rendering cannot animate it); never touches the site's files
            self.ctx.add_init_script("(() => { const css = " + json.dumps(self.init_css) + "; const add = () => { const s = document.createElement('style'); s.id = '__dvcss'; "
                                     "s.textContent = css; (document.head || document.documentElement).appendChild(s); }; "
                                     "if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', add); else add(); })();")
        for s in self.init_scripts:
            self.ctx.add_init_script(s)
        if self.mock:
            self.mock(self.ctx)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        return self

    def __exit__(self, *a):
        try:
            self.stop_recording()
        finally:
            try:
                if self.ctx:
                    self.ctx.close()
            except Exception:
                pass
            if self._pw:
                self._pw.stop()
            if self._profile and not self._keep_profile:
                shutil.rmtree(self._profile, ignore_errors=True)

    # ------------------------------------------------------------------ helpers
    def goto(self, url, settle_ms=800):
        self.page.goto(url, wait_until="networkidle", timeout=60000)
        self.page.evaluate("document.fonts && document.fonts.ready.then(()=>1)")
        self.page.wait_for_timeout(settle_ms)

    def mark(self, name, data=None):
        t = time.time()
        self.marks.append({"name": name, "t": t, "data": data})
        return t

    def drain(self):
        try:
            self.page_marks += self.page.evaluate("window.__dv ? window.__dv.take() : []")
        except Exception:
            pass

    # ------------------------------------------------------------------ recording
    def start_recording(self, slate=True, lead_s=0.6):
        """Start ffmpeg, wait until it is really producing frames, then fire the slate (flash + beep)."""
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-copyts", "-start_at_zero",   # keep the two inputs' real wall-clock offset
               "-thread_queue_size", "64", "-use_wallclock_as_timestamps", "1", "-f", "x11grab", "-framerate", str(self.fps),
               "-video_size", self.size, "-draw_mouse", "0", "-i", stack.DISPLAY,
               "-thread_queue_size", "512", "-use_wallclock_as_timestamps", "1", "-f", "pulse", "-ac", "2", "-i", stack.SINK + ".monitor",
               "-vf", f"fps={self.fps}", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-threads", "2", "-pix_fmt", "yuv420p", "-g", str(self.fps * 2),
               "-c:a", "pcm_s16le", "-ar", "48000", str(self.mkv)]
        self.ff = subprocess.Popen(cmd, env=stack.env(), stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                                   preexec_fn=lambda: os.nice(-16))
        self.t_rec = time.time()
        # wait for the first frames to land on disk
        for _ in range(100):
            if self.mkv.exists() and self.mkv.stat().st_size > 20000:
                break
            time.sleep(0.05)
        time.sleep(lead_s)
        if slate:
            self.page.evaluate("window.__dv.slate()")
            self.mark("slate_call")
            time.sleep(0.5)

    def stop_recording(self, end_slate=True):
        if self.ff and self.ff.poll() is None and end_slate:
            try:
                self.page.evaluate("window.__dv.slate()")
                self.mark("slate_end_call")
                time.sleep(0.6)
            except Exception:
                pass
        self.drain()
        if self.ff and self.ff.poll() is None:
            self.t_q = time.time()
            try:
                self.ff.stdin.write(b"q"); self.ff.stdin.flush()
            except Exception:
                pass
            try:
                self.ff.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.ff.terminate()
                self.ff.wait(timeout=10)
        if self.ff:
            err = (self.ff.stderr.read() or b"").decode("utf-8", "replace")[-1500:] if self.ff.stderr else ""
            self.ff = None
            lost = None
            try:
                d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(self.mkv)],
                                         capture_output=True, text=True).stdout.strip())
                lost = round((self.t_q - self.t_rec) - d, 2)
            except Exception:
                pass
            if lost is not None and lost > 0.6:
                print(f"WARNING: the capture lost {lost} s against the wall clock (CPU starved). Picture and sound may not line up; "
                      f"re-record when the machine is quieter, or lower the load (DV_SIZE=1280x720).", file=sys.stderr)
            meta = {"capture_lost_s": lost, "name": self.name, "size": self.size, "fps": self.fps, "t_rec_start": self.t_rec,
                    "question_wav": self.question_wav, "marks": sorted(self.marks + self.page_marks, key=lambda m: m["t"]),
                    "ffmpeg_stderr_tail": err}
            (self.out / f"{self.name}.marks.json").write_text(json.dumps(meta, indent=1))
            return meta
