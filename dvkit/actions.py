"""Paced browser actions (ported from /root/hack/video_palette/rec.py): time-pinned scrolling with smoothstep easing,
a visible cursor ring that glides to a target and clicks, typed input at a human pace."""
import time


class TL:
    """Action timeline: tl.until(t) sleeps until t seconds after the timeline started."""
    def __init__(self):
        self.t0 = time.monotonic()

    def now(self):
        return time.monotonic() - self.t0

    def until(self, t):
        d = t - self.now()
        if d > 0:
            time.sleep(d)


def smooth(f):
    return f * f * (3 - 2 * f)


def scroll_to(page, tl, y1, ta, tb, x=900, y=500):
    """Mouse-wheel the page to scrollY=y1 between ta and tb (timeline seconds)."""
    tl.until(ta)
    y0 = page.evaluate("window.scrollY")
    page.mouse.move(x, y)
    total, sent = y1 - y0, 0
    while True:
        f = min(1.0, (tl.now() - ta) / max(0.01, (tb - ta)))
        want = round(total * smooth(f))
        if want != sent:
            page.mouse.wheel(0, want - sent)
            sent = want
        if f >= 1.0:
            break
        time.sleep(0.012)


def cursor(page, show):
    page.evaluate(f"window.__curShow && window.__curShow({'true' if show else 'false'})")


def move_click(page, box, move_s=0.7, dx=0.5, dy=0.5, click=True, show=True):
    """Glide the cursor ring to the element box over move_s seconds, then click."""
    cx = box["x"] + box["width"] * dx if dx <= 1 else box["x"] + dx
    cy = box["y"] + box["height"] * dy
    if show:
        cursor(page, True)
    page.mouse.move(cx, cy, steps=max(8, int(move_s * 40)))
    if click:
        page.mouse.click(cx, cy)
    return cx, cy


def type_text(page, text, total_s):
    """Type text so that it finishes in about total_s seconds (human pace, clamped 35-140 ms per key)."""
    per = max(0.035, min(0.14, total_s / max(1, len(text))))
    page.keyboard.type(text, delay=per * 1000)
    return per
