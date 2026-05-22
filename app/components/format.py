"""Display formatting helpers (presentation only, no monetary logic)."""

import time


def format_kes(value):
    """Compact KES: 280000 -> 'KES 280k', 1250000 -> 'KES 1.25M', 70880 -> 'KES 70.9k'."""
    v = float(value or 0)
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1e6:
        s = f"{v / 1e6:.2f}".rstrip("0").rstrip(".")
        return f"{sign}KES {s}M"
    if v >= 1e3:
        s = f"{v / 1e3:.1f}".rstrip("0").rstrip(".")
        return f"{sign}KES {s}k"
    return f"{sign}KES {v:.0f}"


def relative_day(ts, now=None):
    """'today', 'yesterday', '3 days ago', '2 weeks ago', '3 months ago'."""
    if not ts:
        return "—"
    now = now or int(time.time())
    days = max(0, int((now - ts) // 86400))
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 31:
        w = round(days / 7)
        return f"{w} week{'s' if w != 1 else ''} ago"
    m = round(days / 30)
    return f"{m} month{'s' if m != 1 else ''} ago"
