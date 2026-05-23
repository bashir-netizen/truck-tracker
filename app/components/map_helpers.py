"""Shared Map helpers — pure geo/format utilities and marker constants used by both
the period Map (``pages/1_Map.py``) and the Journey View (``components/journey_view.py``).
No Streamlit, no DB; depends only on pydeck for the ViewState return type."""

import math
from datetime import datetime, timezone
from urllib.parse import quote

import pydeck as pdk

# Event marker colours / labels: fuel fill, harsh eco violation, long unknown stop.
EVENT_RGB = {"fill": [29, 111, 184], "harsh": [196, 61, 47], "stop": [91, 103, 112]}
EVENT_NAME = {"fill": "⛽ fuel", "harsh": "⚠️ violation", "stop": "🅿️ parking"}
TYPE_LABELS = {"harsh_accel": "Harsh acceleration", "harsh_brake": "Harsh braking",
               "harsh_corner": "Harsh cornering", "speeding": "Speeding", "idling": "Idling"}
# Per-class arrow spacing (km) along a track.
ARROW_KM = {"long_haul": 5.0, "regional": 3.0, "local": 1.0, "yard": 1.0}
# A small right-pointing arrow; tinted dark, drawn along each track to show heading.
_ARROW_SVG = ("<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' "
              "viewBox='0 0 24 24'><path d='M3 12 H17 M12 6 L19 12 L12 18' "
              "fill='none' stroke='%230e1116' stroke-width='2.6' stroke-linecap='round' "
              "stroke-linejoin='round'/></svg>")
ARROW_ICON = {"url": "data:image/svg+xml;charset=utf-8," + quote(_ARROW_SVG),
              "width": 24, "height": 24, "anchorX": 12, "anchorY": 12}


def day_start(d):
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def fit_view(lats, lons):
    if not lats:
        return pdk.ViewState(latitude=0.5, longitude=37.5, zoom=5.5)  # Kenya
    clat, clon = (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2
    span = max(max(lats) - min(lats), max(lons) - min(lons), 0.02)
    return pdk.ViewState(latitude=clat, longitude=clon,
                         zoom=max(4.5, min(13.0, math.log2(360.0 / span) - 1)))


def haversine_km(la0, lo0, la1, lo1):
    r = 6371.0
    p0, p1 = math.radians(la0), math.radians(la1)
    dp, dl = math.radians(la1 - la0), math.radians(lo1 - lo0)
    a = math.sin(dp / 2) ** 2 + math.cos(p0) * math.cos(p1) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _bearing(lo0, la0, lo1, la1):
    dy = la1 - la0
    dx = (lo1 - lo0) * math.cos(math.radians((la0 + la1) / 2))
    return math.degrees(math.atan2(dy, dx))  # CCW from east; arrow SVG points east


def sample_arrows(path, every_km=5.0, min_arrows=0):
    """Arrow markers (position + heading) every ~every_km along a [[lon,lat],…] path."""
    out, acc = [], 0.0
    for i in range(1, len(path)):
        lo0, la0 = path[i - 1]
        lo1, la1 = path[i]
        acc += haversine_km(la0, lo0, la1, lo1)
        if acc >= every_km:
            acc = 0.0
            out.append({"position": [lo1, la1], "angle": _bearing(lo0, la0, lo1, la1),
                        "icon": ARROW_ICON})
    if len(out) < min_arrows and len(path) >= 2:   # tiny trips (yard): force a couple
        out, n = [], len(path)
        for k in range(1, min_arrows + 1):
            idx = max(1, min(n - 1, round(k * (n - 1) / (min_arrows + 1))))
            (lo0, la0), (lo1, la1) = path[idx - 1], path[idx]
            out.append({"position": [lo1, la1], "angle": _bearing(lo0, la0, lo1, la1),
                        "icon": ARROW_ICON})
    return out
