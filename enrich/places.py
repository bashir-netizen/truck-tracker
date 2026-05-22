"""Cluster trip endpoints into named places (DBSCAN, haversine).

Rebuilds the `places` derived table from `trips`. Optional human labels
come from places.yaml (a list of {label, lat, lon}); each cluster takes
the label of the nearest entry within a small radius. Raw rows untouched.
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


def rebuild(con, unit_id):
    points = []
    for slat, slon, elat, elon in con.execute(
            "SELECT start_lat, start_lon, end_lat, end_lon FROM trips WHERE unit_id=?", (unit_id,)):
        if slat is not None and slon is not None:
            points.append((slat, slon))
        if elat is not None and elon is not None:
            points.append((elat, elon))

    con.execute("DELETE FROM places")
    if not points:
        return 0

    coords = np.array(points)
    db = DBSCAN(eps=config.DBSCAN_EPS_M / EARTH_M,
                min_samples=config.DBSCAN_MIN_SAMPLES,
                metric="haversine").fit(np.radians(coords))

    labels = _load_labels()
    rows, place_id = [], 0
    for cluster in sorted(set(db.labels_)):
        if cluster == -1:  # DBSCAN noise — not a place
            continue
        members = coords[db.labels_ == cluster]
        clat, clon = float(members[:, 0].mean()), float(members[:, 1].mean())
        radius = max(haversine_m(clat, clon, la, lo) for la, lo in members)
        rows.append((place_id, _match_label(labels, clat, clon),
                     clat, clon, int(round(radius)), len(members)))
        place_id += 1

    con.executemany(
        "INSERT INTO places (place_id, label, lat, lon, radius_m, visit_count) "
        "VALUES (?,?,?,?,?,?)", rows)
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
