"""Cluster significant locations into named places (DBSCAN, haversine).

Candidates are journey endpoints + parking points, clustered at town/yard
scale with min_samples=1 (so a destination visited once still becomes a
place). Each place is auto-named from the nearest parking's geocoded
location string; a places.yaml entry (matched by coordinates) overrides it.
Also records total dwell time per place. Raw rows untouched.
"""

import math
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


def _match_label(labels, lat, lon):
    best, best_d = None, float("inf")
    for entry in labels:
        d = haversine_m(lat, lon, entry["lat"], entry["lon"])
        if d < best_d:
            best, best_d = entry, d
    return best["label"] if best and best_d <= LABEL_MAX_M else None


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
        "SELECT lat, lon, duration_s, location FROM parkings "
        "WHERE unit_id=? AND lat IS NOT NULL", (unit_id,)).fetchall()
    # Only meaningful dwells seed a place; brief halts still count toward a
    # place's dwell total below, but don't create their own place.
    points.extend((la, lo) for la, lo, dur, _ in parkings
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
        for la, lo, dur, loc in parkings:
            d = haversine_m(clat, clon, la, lo)
            if d <= radius:
                dwell += dur or 0
                visits += 1
                if loc and d < name_d:
                    name, name_d = loc, d

        label = (_match_label(yaml_labels, clat, clon) or _short_name(name)
                 or f"Place near {clat:.3f}, {clon:.3f}")
        rows.append((place_id, label, clat, clon, int(round(radius)), visits, int(dwell)))
        place_id += 1

    con.executemany(
        "INSERT INTO places (place_id, label, lat, lon, radius_m, visit_count, "
        "visit_time_total_s) VALUES (?,?,?,?,?,?,?)", rows)
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
