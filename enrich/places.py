"""Cluster significant locations into named places (DBSCAN, haversine).

Candidates are journey endpoints + parking points, clustered at town/yard
scale with min_samples=1 (so a destination visited once still becomes a
place). Each place is auto-named from the nearest parking's geocoded
location string; a places.yaml entry (matched by coordinates) overrides it.
Also records total dwell time per place. Raw rows untouched.
"""

import math
import re
from pathlib import Path

import numpy as np
import yaml
from sklearn.cluster import DBSCAN

import config

ROOT = Path(__file__).resolve().parents[1]
PLACES_YAML = ROOT / "places.yaml"
EARTH_M = 6371000.0
LABEL_MAX_M = 300  # a cluster adopts a yaml label only if within this distance


def haversine_m(lat1, lon1, lat2, lon2):
    r1, r2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(r1) * math.cos(r2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_M * math.asin(math.sqrt(a))


def _load_labels():
    if PLACES_YAML.exists():
        return yaml.safe_load(PLACES_YAML.read_text()) or []
    return []


def _match_entry(labels, lat, lon):
    """Nearest places.yaml entry within LABEL_MAX_M, or None."""
    best, best_d = None, float("inf")
    for entry in labels:
        d = haversine_m(lat, lon, entry["lat"], entry["lon"])
        if d < best_d:
            best, best_d = entry, d
    return best if best and best_d <= LABEL_MAX_M else None


def _entry_type(entry):
    """Place type from a yaml entry: explicit `type`, else depot/home flag, else destination."""
    if not entry:
        return "destination"
    if entry.get("type"):
        return entry["type"]
    if entry.get("depot") or entry.get("home"):
        return "depot"
    return "destination"


def _short_name(location):
    """A concise place name from a Wialon geocoded string.

    "Icd Road, Nairobi, South C Ward, …" -> "Nairobi";
    "Marsabit-Moyale Road, Marsabit, …" -> "Marsabit".
    """
    if not location:
        return None
    parts = [p.strip() for p in str(location).split(",") if p.strip()]
    if not parts:
        return None
    return parts[1] if len(parts) > 1 else parts[0]


def _fmt_dur(s):
    """Compact duration for the enrich-side summary print ('5h22m', '18m', '—')."""
    if s is None:
        return "—"
    s = int(s)
    h, m = s // 3600, (s % 3600) // 60
    return f"{h}h{m:02d}m" if h else f"{m}m"


def _dwell_pattern(median_s):
    """Median stop duration -> categorical pattern (thresholds in config)."""
    if median_s < config.DWELL_BRIEF_MAX_S:
        return "brief"
    if median_s < config.DWELL_MEDIUM_MAX_S:
        return "medium"
    if median_s < config.DWELL_LONG_MAX_S:
        return "long"
    return "overnight"


def _suggested_type(pattern, visit_count):
    """A *suggested* place type from dwell pattern + visit frequency. '?' = not authoritative."""
    if pattern == "brief":
        return "transit?"      # quick stop — fuel, rest, errand
    if pattern == "medium":
        return "rest?"         # driver break or a small pickup
    if pattern == "long":
        return "customer?"     # hours on site = bulk loading / unloading
    return "depot?" if visit_count >= config.DWELL_HIGH_VISIT_COUNT else "overnight?"


def _print_dwell_summary(con, by_place):
    """Per-place dwell signature: place · visits · median · pattern · type · suggests."""
    rows = con.execute(
        "SELECT place_id, label, type, median_dwell_s, dwell_pattern_hint, "
        "suggested_type_from_dwell FROM places ORDER BY median_dwell_s DESC").fetchall()
    print("  place dwell summary (place · visits · median · pattern · type · suggests):")
    print(f"    {'place':<26} {'vis':>3} {'median':>7}  {'pattern':<9} {'type':<11} suggests")
    for pid, label, typ, median, pattern, sug in rows:
        n = len(by_place.get(int(pid), []))
        print(f"    {(label or '—')[:26]:<26} {n:>3} {_fmt_dur(median):>7}  "
              f"{(pattern or '—'):<9} {(typ or '—'):<11} {sug or '—'}")


def rebuild(con, unit_id):
    con.execute("DELETE FROM places")

    # Candidate points: journey endpoints + parking points.
    points = []
    for olat, olon, dlat, dlon in con.execute(
            "SELECT origin_lat, origin_lon, dest_lat, dest_lon FROM journeys WHERE unit_id=?",
            (unit_id,)):
        for la, lo in ((olat, olon), (dlat, dlon)):
            if la is not None and lo is not None:
                points.append((la, lo))
    parkings = con.execute(
        "SELECT lat, lon, duration_s, location, start_ts FROM parkings "
        "WHERE unit_id=? AND lat IS NOT NULL", (unit_id,)).fetchall()
    # Only meaningful dwells seed a place; brief halts still count toward a
    # place's dwell total below, but don't create their own place.
    points.extend((la, lo) for la, lo, dur, _loc, _ts in parkings
                  if (dur or 0) >= config.PLACE_MIN_DWELL_S)

    if not points:
        return 0

    coords = np.array(points)
    db = DBSCAN(eps=config.PLACE_EPS_M / EARTH_M,
                min_samples=config.PLACE_MIN_SAMPLES,
                metric="haversine").fit(np.radians(coords))

    yaml_labels = _load_labels()
    rows, place_id = [], 0
    for cluster in sorted(set(db.labels_)):
        if cluster == -1:
            continue
        members = coords[db.labels_ == cluster]
        clat, clon = float(members[:, 0].mean()), float(members[:, 1].mean())
        radius = max(config.PLACE_EPS_M,
                     max(haversine_m(clat, clon, la, lo) for la, lo in members))

        # dwell, visit count, and a name from parkings inside this place
        dwell, visits, name, name_d = 0, 0, None, float("inf")
        for la, lo, dur, loc, _ts in parkings:
            d = haversine_m(clat, clon, la, lo)
            if d <= radius:
                dwell += dur or 0
                visits += 1
                if loc and d < name_d:
                    name, name_d = loc, d

        entry = _match_entry(yaml_labels, clat, clon)
        override = entry["label"] if entry else None
        label = override or _short_name(name) or f"Place near {clat:.3f}, {clon:.3f}"
        weak = override is None and bool(
            re.match(r"^(Place near |\d+(\.\d+)? km from )", label))
        rows.append((place_id, label, clat, clon, int(round(radius)), visits,
                     int(dwell), 1 if weak else 0, _entry_type(entry)))
        place_id += 1

    con.executemany(
        "INSERT INTO places (place_id, label, lat, lon, radius_m, visit_count, "
        "visit_time_total_s, needs_label, type) VALUES (?,?,?,?,?,?,?,?,?)", rows)

    # Map each parking to its nearest place so the dashboard can sum in-range
    # dwell with plain SQL.
    pls = load_places(con)
    visits_rows = []
    for la, lo, dur, _loc, ts in parkings:
        pid = nearest_place_id(pls, la, lo)
        if pid is not None and ts is not None:
            visits_rows.append((pid, ts, dur or 0))
    con.executemany(
        "INSERT OR IGNORE INTO place_visits (place_id, ts, duration_s) VALUES (?,?,?)",
        visits_rows)

    # --- dwell signal (Task 6 B): per-place stop-duration stats from the
    # nearest-based visits, plus a pattern and a *suggested* type for review.
    by_place = {}
    for pid, dur in con.execute("SELECT place_id, duration_s FROM place_visits"):
        by_place.setdefault(int(pid), []).append(int(dur or 0))
    for pid, durs in by_place.items():
        arr = np.array(sorted(durs))
        median = int(np.median(arr))
        pattern = _dwell_pattern(median)
        con.execute(
            "UPDATE places SET median_dwell_s=?, p25_dwell_s=?, p75_dwell_s=?, "
            "longest_dwell_s=?, shortest_dwell_s=?, dwell_pattern_hint=?, "
            "suggested_type_from_dwell=? WHERE place_id=?",
            (median, int(np.percentile(arr, 25)), int(np.percentile(arr, 75)),
             int(arr.max()), int(arr.min()), pattern, _suggested_type(pattern, len(arr)), pid))

    _print_dwell_summary(con, by_place)
    return len(rows)


def load_places(con):
    return [dict(place_id=r[0], label=r[1], lat=r[2], lon=r[3], radius_m=r[4])
            for r in con.execute("SELECT place_id, label, lat, lon, radius_m FROM places")]


def nearest_place_id(places, lat, lon):
    """Place whose centroid is closest and within its radius (or eps), else None."""
    if lat is None or lon is None:
        return None
    best, best_d = None, float("inf")
    for p in places:
        d = haversine_m(lat, lon, p["lat"], p["lon"])
        if d < best_d:
            best, best_d = p, d
    if best and best_d <= max(best["radius_m"], config.DBSCAN_EPS_M):
        return best["place_id"]
    return None
