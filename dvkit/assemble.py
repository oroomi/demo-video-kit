#!/usr/bin/env python3
"""Assemble the final video from recorded takes.

  assemble.py --take live1 [--proof P1,P2] [--name demo] [--no-vertical] [--allow-mock]

Reads out/<profile>/<take>.mkv + .marks.json + .live.json (from record.py) and writes
  <name>.mp4            1920x1080 30 fps H.264 + AAC, loudness -16 LUFS, under 50 MB
  <name>_vertical.mp4   1080x1920 cut (live moment zoomed, proof shots stacked), same audio
  <name>.srt            captions
  <name>.proof.json     the numbers that prove the voice is on tape and in sync

Structure (the 2-minute version is in templates/SHOTLIST.md): hook (the assistant already speaking), title card, the live
moment from the mic click to the end of the reply, proof shots, transfer line + end card with URL and QR.
Picture and sound come from ONE capture; the sound is shifted by the skew measured on the slate (magenta flash + beep).
Captions come from the known question and the assistant's streamed text, timed to the recorded audio with silence detection."""
import argparse, json, math, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from PIL import Image, ImageDraw, ImageFont
from dvkit import sync

FPS = 30
CAP_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
CAP_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONTS = ROOT / "assets/fonts"
NEWS = str(FONTS / "newsreader-latin-400-normal.ttf")
NEWSI = str(FONTS / "newsreader-latin-400-italic.ttf")
PLEX = str(FONTS / "ibm-plex-sans-latin-400-normal.ttf")
PLEX5 = str(FONTS / "ibm-plex-sans-latin-500-normal.ttf")

FMT = {   # per output format: canvas, caption font size, caption width, band geometry, hook font size
    "h": {"W": 1920, "H": 1080, "cap": 34, "maxw": 1640, "band": 148, "lines": 2, "hook": 76},
    "v": {"W": 1080, "H": 1920, "cap": 52, "maxw": 940, "band": 420, "lines": 5, "hook": 92},
}


def run(cmd, **kw):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if r.returncode:
        print(" ".join(str(c) for c in cmd)[:700]); print(r.stderr[-2500:]); sys.exit(1)
    return r


def frames(sec):
    return math.ceil(sec * FPS - 1e-6)


# ------------------------------------------------------------------------------------------------------------------ clocks
class Clock:
    """Maps page time (epoch s) to the capture's picture clock and sound clock using the start and end slates."""
    def __init__(self, marks, sa):
        pm = [m["t"] for m in marks if m["name"] == "slate"]
        if len(pm) < 1 or sa["flash_start"] is None or sa["beep_start"] is None:
            raise SystemExit("no slate found in this take (flash + beep): cannot align picture and sound. Re-record with the kit.")
        self.p0, self.f0, self.b0 = pm[0], sa["flash_start"], sa["beep_start"]
        self.kv = self.ka = 1.0
        if len(pm) > 1 and sa["flash_end"] is not None and sa["beep_end"] is not None and pm[-1] - pm[0] > 5:
            self.kv = (sa["flash_end"] - sa["flash_start"]) / (pm[-1] - pm[0])
            self.ka = (sa["beep_end"] - sa["beep_start"]) / (pm[-1] - pm[0])
        self.skew0 = sa["skew_start"]
        self.skew1 = sa["skew_end"] if sa["skew_end"] is not None else sa["skew_start"]
        self.f1 = sa["flash_end"] if sa["flash_end"] is not None else self.f0

    def v(self, t):   # page time -> picture clock
        return self.f0 + (t - self.p0) * self.kv

    def a(self, t):   # page time -> sound clock
        return self.b0 + (t - self.p0) * self.ka

    def skew_at(self, v):   # sound clock = picture clock + skew
        if self.f1 - self.f0 < 5:
            return self.skew0
        f = min(1.0, max(0.0, (v - self.f0) / (self.f1 - self.f0)))
        return self.skew0 + f * (self.skew1 - self.skew0)


def first(marks, name, after=None):
    for m in marks:
        if m["name"] == name and (after is None or m["t"] >= after):
            return m
    return None


# ------------------------------------------------------------------------------------------------------------------ captions
_fonts = {}


def font(size, bold=False):
    k = (size, bold)
    if k not in _fonts:
        _fonts[k] = ImageFont.truetype(CAP_BOLD if bold else CAP_FONT, size)
    return _fonts[k]


def wrap(text, fmt):
    f, maxw = font(FMT[fmt]["cap"]), FMT[fmt]["maxw"]
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if f.getlength(t) <= maxw:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    if len(lines) == 2:   # balance
        best = min(range(1, len(words)), key=lambda i: max(f.getlength(" ".join(words[:i])), f.getlength(" ".join(words[i:]))))
        lines = [" ".join(words[:best]), " ".join(words[best:])]
    return lines


def caption_blocks(text, t0, t1, pauses, fmt, style):
    """Sentence-aware caption blocks between t0 and t1 (capture clock). Sentence starts snap to a nearby detected pause."""
    sents = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]
    weights = [len(s) + 5 for s in sents]
    tot, acc, starts = sum(weights), 0.0, []
    for w in weights:
        starts.append(t0 + acc / tot * (t1 - t0)); acc += w
    starts.append(t1)
    for i in range(1, len(sents)):
        near = min(pauses, key=lambda p: abs(p - starts[i]), default=None)
        if near is not None and abs(near - starts[i]) <= 0.7 and starts[i - 1] + 0.4 < near < starts[i + 1] - 0.4:
            starts[i] = near
    blocks, nmax = [], FMT[fmt]["lines"]
    for i, s in enumerate(sents):
        lines = wrap(s, fmt)
        groups = [lines[j:j + nmax] for j in range(0, len(lines), nmax)]
        n = sum(len(" ".join(g)) for g in groups)
        a, b, cur = starts[i], starts[i + 1], starts[i]
        for g in groups:
            d = (b - a) * len(" ".join(g)) / n
            blocks.append({"t0": cur, "t1": cur + d, "lines": g, "style": style}); cur += d
    for i in range(len(blocks) - 1):
        blocks[i]["t1"] = blocks[i + 1]["t0"]
    blocks[-1]["t1"] = t1 + 0.15
    return blocks


def plain_words(text):
    return re.sub(r"\s+", " ", text).strip()


# ------------------------------------------------------------------------------------------------------------------ cards
def card_png(path, fmt, prof, lines, qr=None):
    c = prof.get("card", {})
    W, H = FMT[fmt]["W"], FMT[fmt]["H"]
    k = W / 1920
    im = Image.new("RGB", (W, H), c.get("bg", "#021B44"))
    d = ImageDraw.Draw(im)
    for text, ffile, size, col, cy in lines:
        f = ImageFont.truetype({"news": NEWS, "newsi": NEWSI, "plex": PLEX, "plex5": PLEX5}[ffile], int(size * (k if fmt == "h" else 0.62)))
        while f.getlength(text) > W * 0.92 and f.size > 20:
            f = ImageFont.truetype(f.path, f.size - 2)
        y = cy if fmt == "h" else int(cy * H / 1080 * 0.95)
        d.text((W // 2, y), text, font=f, fill=col, anchor="mm")
    if qr:
        import qrcode
        q = qrcode.QRCode(border=2, box_size=10); q.add_data(qr); q.make(fit=True)
        img = q.make_image(fill_color="#021B44", back_color="#F6FDFF").convert("RGB")
        s = 300 if fmt == "h" else 420
        img = img.resize((s, s), Image.NEAREST)
        pos = (W - s - 120, H - s - 100) if fmt == "h" else ((W - s) // 2, H - s - 220)
        im.paste(img, pos)
    im.save(path)


def card_clip(png, secs, out_v, out_a, fi=0.4, fo=0.4):
    n = frames(secs); d = n / FPS
    run(["ffmpeg", "-y", "-loop", "1", "-framerate", FPS, "-i", png, "-frames:v", n,
         "-vf", f"fade=t=in:st=0:d={fi},fade=t=out:st={d - fo}:d={fo},format=yuv420p",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", FPS, "-g", 60, "-an", out_v])
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{d:.4f}", "-c:a", "pcm_s16le", out_a])
    return d


# ------------------------------------------------------------------------------------------------------------------ take segments
def esc(path):
    return str(path).replace("\\", "/").replace(":", "\\:")


def render_take(seg, fmt, W_DIR, idx, clock):
    """seg: {take_mkv, v_in, dur_src, speed, caps: [{t0,t1,lines,style}] (capture clock), hook: str|None, vmode, focus, silent}"""
    g = FMT[fmt]
    speed = seg.get("speed", 1.0)
    v_in, dur_src = seg["v_in"], seg["dur_src"]
    out_dur = dur_src / speed
    n = frames(out_dur); D = n / FPS
    out_v, out_a = W_DIR / f"seg{idx}_{fmt}.mp4", W_DIR / f"seg{idx}.wav"
    pre = [f"setpts=(PTS-STARTPTS)/{speed}", f"fps={FPS}", "tpad=stop_mode=clone:stop_duration=2"]
    vm = seg.get("vmode", "crop")
    stack = (fmt == "v" and vm != "crop")
    if fmt == "h":
        chain = ",".join(pre + ["scale=1920:1080:flags=lanczos"])
    elif vm == "crop":
        cw = 608
        x0 = int(max(0, min(1920 - cw, seg.get("focus", 0.5) * 1920 - cw / 2)))
        chain = ",".join(pre + [f"crop={cw}:1080:{x0}:0", "scale=1080:1920:flags=lanczos"])
    else:   # stack: blurred fill behind, the whole frame in the middle
        chain = (",".join(pre) + ",split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=28:6,eq=brightness=-0.28[bg];"
                 "[b]scale=1080:-2:flags=lanczos[fg];[bg][fg]overlay=0:(H-h)/2-250")
    # captions and hook text (times relative to the segment output)
    dr = []
    caps = seg.get("caps", [])
    if caps or seg.get("hook"):
        a0 = (min([c["t0"] for c in caps]) - v_in) / speed if caps else 0
        a1 = (max([c["t1"] for c in caps]) - v_in) / speed if caps else out_dur
        if caps:
            dr.append(f"drawbox=x=0:y=ih-{g['band']}:w=iw:h={g['band']}:color=black@0.62:t=fill:enable='between(t,{a0 - 0.12:.3f},{a1 + 0.1:.3f})'")
    for bi, b in enumerate(caps):
        ta, tb = (b["t0"] - v_in) / speed, (b["t1"] - v_in) / speed
        if tb <= 0 or ta >= out_dur:
            continue
        nl = len(b["lines"])
        col = "0x00E5D4" if b.get("style") == "question" else "white"
        step = int(g["cap"] * 1.22)
        y0 = g["H"] - g["band"] + (g["band"] - step * nl) // 2 if fmt == "h" else g["H"] - g["band"] + 60
        for li, line in enumerate(b["lines"]):
            tf = W_DIR / f"cap{idx}_{fmt}_{bi}_{li}.txt"; tf.write_text(line)
            fnt = CAP_BOLD if b.get("style") == "question" else CAP_FONT
            dr.append(f"drawtext=fontfile={fnt}:textfile={esc(tf)}:expansion=none:fontsize={g['cap']}:fontcolor={col}:x=(w-text_w)/2:y={y0 + step * li}:enable='between(t,{ta:.3f},{tb:.3f})'")
    if seg.get("hook"):
        lines = wrap_hook(seg["hook"], fmt)
        hs = g["hook"]
        for li, line in enumerate(lines):
            tf = W_DIR / f"hook{idx}_{fmt}_{li}.txt"; tf.write_text(line)
            ypos = (70 if fmt == "h" else 150) + int(hs * 1.18) * li
            dr.append(f"drawtext=fontfile={NEWS}:textfile={esc(tf)}:expansion=none:fontsize={hs}:fontcolor=white:borderw=4:bordercolor=black@0.55:x=(w-text_w)/2:y={ypos}:enable='between(t,0.0,{min(out_dur, 4.0):.3f})'")
    chain += ("," if dr else "") + ",".join(dr) + ",format=yuv420p"
    cmd = ["ffmpeg", "-y", "-ss", f"{max(0, v_in):.3f}", "-t", f"{dur_src + 0.2:.3f}", "-i", seg["mkv"], "-frames:v", n]
    cmd += ["-filter_complex" if stack else "-vf", chain,
            "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-r", FPS, "-g", 60, "-an", out_v]
    run(cmd)
    # sound: the capture's own audio, shifted by the measured skew
    if fmt == "h":
        if seg.get("silent"):
            run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{D:.4f}", "-c:a", "pcm_s16le", out_a])
        else:
            sk = clock.skew_at(v_in + dur_src / 2)
            a_in = v_in + sk
            pre = ""
            if a_in < 0:
                pre = f"adelay={int(-a_in * 1000)}:all=1,"; a_in = 0
            tempo = f"atempo={speed}," if speed != 1.0 else ""
            run(["ffmpeg", "-y", "-ss", f"{a_in:.3f}", "-t", f"{dur_src + 0.2:.3f}", "-i", seg["mkv"], "-vn", "-af",
                 f"{pre}{tempo}apad=whole_dur={D:.4f},aresample=48000", "-ac", 2, "-t", f"{D:.4f}", "-c:a", "pcm_s16le", out_a])
    return out_v, out_a, D


def wrap_hook(text, fmt):
    f = ImageFont.truetype(NEWS, FMT[fmt]["hook"])
    maxw = FMT[fmt]["W"] * 0.86
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if f.getlength(t) <= maxw:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


# ------------------------------------------------------------------------------------------------------------------ main
def load_take(out, name, allow_mock=False):
    mkv = out / f"{name}.mkv"
    marks = json.loads((out / f"{name}.marks.json").read_text())
    live = json.loads((out / f"{name}.live.json").read_text()) if (out / f"{name}.live.json").exists() else None
    if live and live.get("mock") and not allow_mock:
        raise SystemExit(f"take {name} is a MOCK rehearsal (fixtures, not the live assistant): refusing to assemble it. Pass --allow-mock only for pipeline tests.")
    cache = out / f"{name}.sync.json"
    if cache.exists() and cache.stat().st_mtime > mkv.stat().st_mtime:
        sa = json.loads(cache.read_text())
    else:
        sa = sync.analyze(mkv)
        cache.write_text(json.dumps(sa, indent=1))
    return mkv, marks["marks"], live, sa


def build(a):
    prof = json.loads(pathlib.Path(a.profile).read_text())
    out = pathlib.Path(a.out or ROOT / "out" / prof["name"])
    W_DIR = out / "work"; W_DIR.mkdir(exist_ok=True)
    mkv, marks, live, sa = load_take(out, a.take, a.allow_mock)
    clock = Clock(marks, sa)
    print("sync:", json.dumps(sa))
    bursts = sync.sound_bursts(mkv, "-38dB", 0.12)
    # pauses (mid-points of silences >= 0.12 s) on the sound clock, for snapping caption boundaries
    pauses_a = [(bursts[i][1] + bursts[i + 1][0]) / 2 for i in range(len(bursts) - 1)]
    lv = {"mkv": str(mkv)}

    # ---- events on the capture's clocks
    t_mic = live["t_mic_click"]
    skew = clock.skew_at(clock.v(t_mic))
    q_burst = next(b for b in bursts if b[0] >= clock.a(live["t_question_audio"]) - 0.1)
    reply = lambda m: "/tts/" in str((m.get("data") or {}).get("src", ""))
    p_ev = next((m for m in marks if m["name"] == "audio_playing" and m["t"] >= live["t_mic_click"] and reply(m)), None)
    ended = next((m for m in marks if m["name"] == "audio_ended" and m["t"] >= live["t_mic_click"] and reply(m)), None)
    state = [(m["t"], m["data"]) for m in marks if m["name"] == "state"]
    t_think = next((t for t, s in state if s == "thinking"), None)
    t_speak = next((t for t, s in state if s == "speaking"), None)
    if not (p_ev and ended and t_think and t_speak):
        raise SystemExit("the take has no completed reply (no audio_playing/ended or thinking/speaking states): record again")
    r_a0 = clock.a(p_ev["t"]) - 0.25
    r_burst_list = [b for b in bursts if b[0] >= r_a0 and b[0] <= clock.a(ended["t"]) + 0.5]
    if not r_burst_list:
        raise SystemExit("no voice found on the tape in the reply window: check the PulseAudio sink (./demo-video doctor)")
    r_on, r_off = r_burst_list[0][0], r_burst_list[-1][1]            # sound clock
    q_on, q_off = q_burst[0], q_burst[1]
    to_v = lambda x: x - skew                                       # sound clock -> picture clock
    answer = plain_words(live["answer_text"])
    question = live["question"]
    pa = lambda lo, hi: [p for p in pauses_a if lo <= p <= hi]
    q_caps = [{"t0": to_v(q_on) - 0.05, "t1": to_v(q_off) + 0.35, "lines": wrap("“" + question + "”", "h"), "style": "question"}]
    q_caps_v = [{"t0": q_caps[0]["t0"], "t1": q_caps[0]["t1"], "lines": wrap("“" + question + "”", "v"), "style": "question"}]
    caps = {"h": q_caps + [dict(c, t0=to_v(c["t0"]), t1=to_v(c["t1"])) for c in caption_blocks(answer, r_on, r_off, pa(r_on, r_off), "h", "reply")],
            "v": q_caps_v + [dict(c, t0=to_v(c["t0"]), t1=to_v(c["t1"])) for c in caption_blocks(answer, r_on, r_off, pa(r_on, r_off), "v", "reply")]}
    print(f"question on tape {q_on:.2f}-{q_off:.2f} s (sound clock); reply {r_on:.2f}-{r_off:.2f} s ({r_off - r_on:.1f} s of voice)")

    segs = []   # (kind, spec, per-format caps)
    # ---- 1 hook: the assistant already speaking
    hook_len = a.hook_len
    h_in = to_v(r_on) - 0.3
    segs.append(("take", dict(lv, v_in=h_in, dur_src=hook_len, hook=a.hook_text, vmode="crop", name="hook"), "hook"))
    # ---- 2 title card
    segs.append(("card", {"kind": "title", "secs": a.title_s}, None))
    # ---- 3 the live moment (the thinking gap is sped up only if it exceeds think_cap)
    v_start = clock.v(first(marks, "mic_move", after=live["t_hero_start"])["t"]) - 0.5
    v_think, v_speak = clock.v(t_think), clock.v(t_speak)
    gap = v_speak - v_think
    v_end = to_v(r_off) + a.tail
    if gap > a.think_cap + 0.8:
        keep = 0.9
        f_gap = (gap - keep) / (a.think_cap - keep)
        g0, g1 = v_think + keep, v_speak - 0.1
        f_gap = (g1 - g0) / max(0.5, (a.think_cap - keep - 0.1))
        segs.append(("take", dict(lv, v_in=v_start, dur_src=g0 - v_start, vmode="crop", name="live_a"), "live"))
        segs.append(("take", dict(lv, v_in=g0, dur_src=g1 - g0, speed=f_gap, silent=True, vmode="crop", name="live_gap"), "live"))
        segs.append(("take", dict(lv, v_in=g1, dur_src=v_end - g1, vmode="crop", name="live_b"), "live"))
        print(f"thinking gap {gap:.1f} s real: sped up x{f_gap:.1f} to {a.think_cap:.1f} s")
    else:
        segs.append(("take", dict(lv, v_in=v_start, dur_src=v_end - v_start, vmode="crop", name="live"), "live"))
        print(f"thinking gap {gap:.1f} s real: kept as it happened")
    # ---- 4 proof shots (scripted, silent, with their own caption line)
    proofs = []
    for item in [p for p in (a.proof or "").split(",") if p]:
        name, _, text = item.partition(":")
        pm, pmarks, _, psa = load_take(out, name, True)
        pc = Clock(pmarks, psa)
        p_in = psa["flash_start"] + 0.6
        p_out = (psa["flash_end"] - 0.2) if psa["flash_end"] else p_in + a.proof_s
        dur = min(a.proof_s, p_out - p_in)
        spec = dict(mkv=str(pm), v_in=p_in, dur_src=dur, vmode="stack", silent=True, name=name,
                    caps=[{"t0": p_in + 0.3, "t1": p_in + dur - 0.1, "lines": None, "style": "reply", "text": text}] if text else [])
        segs.append(("take", spec, "proof"))
        proofs.append(name)
    # ---- 5 transfer line + end card
    segs.append(("card", {"kind": "end", "secs": a.end_s}, None))

    # ---- render both formats
    results, seg_starts = {}, {}
    for fmt in ("h",) + (() if a.no_vertical else ("v",)):
        parts_v, parts_a, t, srt = [], [], 0.0, []
        for i, (kind, spec, tag) in enumerate(segs):
            if kind == "card":
                png = W_DIR / f"card_{spec['kind']}_{fmt}.png"
                cd = prof.get("card", {}); acc, fg, soft = cd.get("accent", "#00E5D4"), cd.get("fg", "#F6FDFF"), cd.get("soft", "#CDEBFF")
                if spec["kind"] == "title":
                    card_png(png, fmt, prof, [(prof.get("headline", "Ocean Opportunity Radar"), "news", 132, fg, 470),
                                              (prof.get("tagline", ""), "plex", 36, acc, 610)])
                else:
                    card_png(png, fmt, prof, [(prof.get("transfer_line", "Swap one file, get a new sector."), "newsi", 64, soft, 330),
                                              (prof.get("end_url", "jx.hankintaviikko.fi"), "news", 150, acc, 500),
                                              (prof.get("end_line", ""), "plex", 44, fg, 650)], qr=prof.get("qr", prof.get("url")))
                ov, oa = W_DIR / f"seg{i}_{fmt}.mp4", W_DIR / f"seg{i}_card.wav"
                d = card_clip(str(png), spec["secs"], ov, oa)
                if fmt == "h":
                    run(["cp", oa, W_DIR / f"seg{i}.wav"])
                parts_v.append(ov); parts_a.append(W_DIR / f"seg{i}.wav"); t += d
                continue
            sp = dict(spec)
            if tag == "hook":
                sp["caps"] = [c for c in caps[fmt] if c["style"] == "reply" and c["t1"] > h_in and c["t0"] < h_in + hook_len]
            elif tag == "live":
                lo, hi = sp["v_in"], sp["v_in"] + sp["dur_src"]
                sp["caps"] = [c for c in caps[fmt] if c["t1"] > lo and c["t0"] < hi]
            elif tag == "proof":
                for c in sp["caps"]:
                    c["lines"] = wrap(c["text"], fmt)
            ov, oa, D = render_take(sp, fmt, W_DIR, i, clock)
            parts_v.append(ov); parts_a.append(W_DIR / f"seg{i}.wav")
            if fmt == "h":
                seg_starts[sp.get("name", str(i))] = (t, sp["v_in"], sp.get("speed", 1.0))
            if fmt == "h":
                for c in sp["caps"]:
                    srt.append((t + (c["t0"] - sp["v_in"]) / sp.get("speed", 1.0), t + (c["t1"] - sp["v_in"]) / sp.get("speed", 1.0), c["lines"]))
            t += D
        results[fmt] = {"parts_v": parts_v, "parts_a": parts_a, "total": t}
        (W_DIR / f"list_v_{fmt}.txt").write_text("".join(f"file '{p}'\n" for p in parts_v))
        if fmt == "h":
            (W_DIR / "list_a.txt").write_text("".join(f"file '{p}'\n" for p in parts_a))
            write_srt(out / f"{a.name}.srt", srt, t)

    # ---- audio: concat, two-pass loudnorm, then mux
    run(["ffmpeg", "-y", "-f", "concat", "-safe", 0, "-i", W_DIR / "list_a.txt", "-c", "copy", W_DIR / "all_a.wav"])
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(W_DIR / "all_a.wav"), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], capture_output=True, text=True)
    j = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S).group(0))
    ln = (f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={j['input_i']}:measured_TP={j['input_tp']}:measured_LRA={j['input_lra']}:"
          f"measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true")
    run(["ffmpeg", "-y", "-i", W_DIR / "all_a.wav", "-af", ln + ",aresample=48000", "-c:a", "pcm_s16le", W_DIR / "norm_a.wav"])
    outs = {}
    for fmt, suffix in (("h", ""), ("v", "_vertical")):
        if fmt not in results:
            continue
        run(["ffmpeg", "-y", "-f", "concat", "-safe", 0, "-i", W_DIR / f"list_v_{fmt}.txt", "-c", "copy", W_DIR / f"all_v_{fmt}.mp4"])
        dest = out / f"{a.name}{suffix}.mp4"
        mux(W_DIR / f"all_v_{fmt}.mp4", W_DIR / "norm_a.wav", dest, results[fmt]["total"], a.max_mb)
        outs[fmt] = dest
    proof = verify(outs["h"], live, caps["h"], clock, skew, r_on, r_off, q_on, q_off, sa, p_ev, seg_starts, to_v, results["h"]["total"], bursts)
    proof["files"] = {k: {"path": str(v), "mb": round(v.stat().st_size / 1e6, 2)} for k, v in outs.items()}
    (out / f"{a.name}.proof.json").write_text(json.dumps(proof, indent=1))
    print(json.dumps(proof, indent=1))


def mux(vid, aud, dest, total, max_mb):
    base = ["ffmpeg", "-y", "-i", vid, "-i", aud, "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-shortest", "-movflags", "+faststart"]
    run(base + ["-c:v", "copy", dest])
    if dest.stat().st_size > max_mb * 1e6:
        kbps = int((max_mb * 0.92 * 8e6 / total - 160_000) / 1000)
        print(f"{dest.name} is {dest.stat().st_size / 1e6:.1f} MB: re-encoding at {kbps} kbit/s to fit {max_mb} MB")
        run(["ffmpeg", "-y", "-i", vid, "-i", aud, "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "slow", "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.3)}k",
             "-bufsize", f"{kbps * 2}k", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-shortest", "-movflags", "+faststart", dest])


def write_srt(path, items, total):
    def ts(t):
        ms = int(round(t * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    with open(path, "w") as fh:
        for i, (a, b, lines) in enumerate(sorted(items), 1):
            fh.write(f"{i}\n{ts(a)} --> {ts(min(b, total))}\n" + "\n".join(lines) + "\n\n")


def volume(path, t0=None, t1=None):
    cmd = ["ffmpeg", "-hide_banner", "-nostats"]
    if t0 is not None:
        cmd += ["-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}"]
    r = subprocess.run(cmd + ["-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    m, x = re.search(r"mean_volume: (-?[0-9.]+|-inf)", r.stderr), re.search(r"max_volume: (-?[0-9.]+|-inf)", r.stderr)
    f = lambda s: None if s is None or s.group(1) == "-inf" else float(s.group(1))
    return {"mean_db": f(m), "max_db": f(x)}


def verify(final, live, caps, clock, skew, r_on, r_off, q_on, q_off, sa, p_ev, seg_starts, to_v, total, bursts_raw):
    """Numbers that prove the voice track is present and in sync, measured on the FINAL file."""
    fb = sync.sound_bursts(final, "-38dB", 0.12)
    dur = sync.duration(final)
    def expected(sound_t, segname):
        t0, v_in, speed = seg_starts[segname]
        return t0 + (to_v(sound_t) - v_in) / speed
    def nearest(x):
        return min((b[0] for b in fb), key=lambda o: abs(o - x), default=None)
    exp_reply = expected(r_on, "hook")
    live_segs = [k for k in seg_starts if k.startswith("live")]
    exp_q = expected(q_on, live_segs[0])
    exp_r2 = expected(r_on, live_segs[-1])
    chk = {}
    for label, e in (("hook_reply_onset", exp_reply), ("live_question_onset", exp_q), ("live_reply_onset", exp_r2)):
        m = nearest(e)
        chk[label] = {"expected_s": round(e, 3), "measured_s": None if m is None else round(m, 3), "delta_ms": None if m is None else round((m - e) * 1000)}
    out = {"final_duration_s": round(dur, 2),
           "first_voice_s": round(fb[0][0], 2) if fb else None,
           "voice_in_first_5s": bool(fb and fb[0][0] <= 5.0), "voice_in_first_20s": bool(fb and fb[0][0] <= 20.0),
           "final_vs_edit_list": chk,
           "raw_capture": {"skew_start_s": sa["skew_start"], "skew_end_s": sa["skew_end"], "drift_s": sa["drift"],
                           "applied_skew_s": round(skew, 3), "question_on_tape_s": [round(q_on, 2), round(q_off, 2)], "reply_on_tape_s": [round(r_on, 2), round(r_off, 2)]},
           "page_to_tape": {"audio_playing_event_to_voice_onset_ms": round((r_on - clock.a(p_ev["t"])) * 1000),
                            "note": "positive = the voice reaches the tape this long after the page reports the audio element playing; picture and sound share the slate"},
           "whole_file_volume": volume(final),
           "reply_window_volume_in_hook": volume(final, exp_reply, exp_reply + 3.5)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=str(ROOT / "profiles/jx.json"))
    ap.add_argument("--out")
    ap.add_argument("--take", required=True)
    ap.add_argument("--proof", default="", help="comma list NAME[:caption text] of scripted shots recorded with `record.py shot`")
    ap.add_argument("--name", default="demo")
    ap.add_argument("--hook-text", default="Ask it out loud. It answers.")
    ap.add_argument("--hook-len", type=float, default=4.2)
    ap.add_argument("--title-s", type=float, default=2.4)
    ap.add_argument("--end-s", type=float, default=3.6)
    ap.add_argument("--proof-s", type=float, default=6.0)
    ap.add_argument("--tail", type=float, default=1.6, help="seconds to hold after the reply ends")
    ap.add_argument("--think-cap", type=float, default=3.0, help="longest thinking gap shown at real speed (s); longer ones are sped up to this")
    ap.add_argument("--no-vertical", action="store_true")
    ap.add_argument("--allow-mock", action="store_true")
    ap.add_argument("--max-mb", type=float, default=50.0)
    a = ap.parse_args()
    build(a)


if __name__ == "__main__":
    main()
