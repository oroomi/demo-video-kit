"""Scripted proof shots for the Ocean Opportunity Radar (no voice, no model calls: plain page loads).
Contract: SHOTS = {name: (fn(page, tl, m), path)}.  fn drives the page on the timeline `tl` and sets m["total"] (seconds)."""
from dvkit.actions import scroll_to, move_click, cursor


def P1(page, tl, m):
    """Company page: the four questions, each with sources."""
    tl.until(0.4)
    scroll_to(page, tl, 520, 0.4, 2.6, x=960)
    scroll_to(page, tl, 1250, 2.9, 5.6, x=960)
    tl.until(6.0)
    m["total"] = 6.0


def P2(page, tl, m):
    """Match page: open 'Why this match' to show the printed rule and evidence."""
    tl.until(0.3)
    scroll_to(page, tl, 420, 0.3, 1.8, x=960)
    box = page.locator("summary", has_text="Why this match").first.bounding_box()
    move_click(page, box, move_s=0.8, dx=0.15)
    m["expanded"] = tl.now()
    tl.until(3.0); cursor(page, False)
    scroll_to(page, tl, 760, 3.3, 5.6, x=960)
    tl.until(6.0)
    m["total"] = 6.0


def P3(page, tl, m):
    """Backtest: the earliness chart, with the misses published."""
    tl.until(0.4)
    scroll_to(page, tl, 1500, 0.6, 3.6, x=960)
    scroll_to(page, tl, 1700, 3.6, 5.6, x=960)
    tl.until(6.0)
    m["total"] = 6.0


SHOTS = {"P1": (P1, "/c/2962040-6"), "P2": (P2, "/match?org=redstone-blue"), "P3": (P3, "/backtest")}
