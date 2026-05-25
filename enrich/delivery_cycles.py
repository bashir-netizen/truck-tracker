"""Delivery cycles — the operational unit for a cement hauler.

A delivery cycle = load at an anchor (the depot OR a loading customer) -> deliver -> arrive
at the NEXT anchor. Anchored on loading customers, where round_trips is depot-anchored; both
models coexist (this one maps to billable loads).

Derived, read-only over journeys + places. cycle_type: delivery (a non-anchor destination
between anchors), positioning (anchor -> anchor with no delivery), incomplete (the open tail —
left an anchor, not yet at the next). Multi-cluster customers are label-grouped, so a facility
split across DBSCAN clusters still triggers one anchor (Bamburi's two clusters both do).
"""

import json

from enrich.round_trips import _DEST_TYPES, _haversine_km


def rebuild(con, unit_id):
    con.execute("DELETE FROM delivery_cycles")
    places = {int(r[0]): {"label": r[1], "lat": r[2], "lon": r[3], "type": r[4],
                          "role": r[5], "named": r[6] == 0}
              for r in con.execute("SELECT place_id, label, lat, lon, type, suggested_role, "
                                   "needs_label FROM places")}
    # Loading anchors, label-grouped: any cluster sharing a name with an anchor is an anchor.
    anchor_labels = {p["label"] for p in places.values()
                     if p["type"] == "depot" or (p["type"] == "customer" and p["role"] == "loading")}
    anchor_ids = {pid for pid, p in places.items() if p["label"] in anchor_labels}

    jr = con.execute(
        "SELECT journey_id, start_ts, end_ts, origin_place_id, dest_place_id, distance_m "
        "FROM journeys WHERE unit_id=? ORDER BY start_ts", (unit_id,)).fetchall()
    arrivals = [i for i, j in enumerate(jr) if j[4] is not None and int(j[4]) in anchor_ids]
    if not arrivals:
        return 0

    def farthest(origin_pid, dest_ids):
        o = places.get(origin_pid, {})
        nonanchor = [d for d in dest_ids if d not in anchor_ids]
        named = [d for d in nonanchor if places.get(d, {}).get("named")]
        # prefer real delivery endpoints (exclude transit pass-throughs), then any named, then any
        targets = [d for d in named if places.get(d, {}).get("type") in _DEST_TYPES]
        pool = targets or named or nonanchor
        if not pool:
            return None
        return max(pool, key=lambda d: _haversine_km(
            o.get("lat"), o.get("lon"), places.get(d, {}).get("lat"), places.get(d, {}).get("lon")))

    out = []
    for k, ai in enumerate(arrivals):
        nai = arrivals[k + 1] if k + 1 < len(arrivals) else None
        seg = jr[ai + 1: (nai + 1) if nai is not None else len(jr)]
        if not seg:
            continue
        incomplete = nai is None
        origin_pid = int(jr[ai][4])
        cstart = int(jr[ai][2])
        cend = int(jr[nai][2]) if nai is not None else None
        seg_dests = [int(j[4]) for j in seg if j[4] is not None]
        nonanchor = [d for d in seg_dests if d not in anchor_ids]
        dest_pid = farthest(origin_pid, seg_dests)
        ctype = "incomplete" if incomplete else ("delivery" if nonanchor else "positioning")

        via, seen = [], set()
        for d in seg_dests:
            if d in anchor_ids or d == dest_pid or d in seen:
                continue
            seen.add(d)
            if places.get(d, {}).get("named"):
                via.append(places[d]["label"])
        dur = (cend if cend is not None else int(seg[-1][2])) - cstart
        out.append((
            unit_id, cstart, cend, origin_pid, places.get(origin_pid, {}).get("label"),
            dest_pid, (places.get(dest_pid, {}).get("label") if dest_pid else None), ctype,
            round(sum((j[5] or 0) for j in seg) / 1000.0, 1), dur,
            json.dumps([int(j[0]) for j in seg]), json.dumps(via)))

    con.executemany(
        "INSERT INTO delivery_cycles (unit_id, cycle_start_ts, cycle_end_ts, origin_place_id, "
        "origin_place_name, destination_place_id, destination_place_name, cycle_type, "
        "total_distance_km, total_duration_s, constituent_journey_ids, via_places) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", out)

    by = {}
    for c in out:
        by[c[7]] = by.get(c[7], 0) + 1
    print(f"  delivery_cycles: {len(out)} cycles ("
          + ", ".join(f"{v} {k}" for k, v in sorted(by.items())) + ")")
    return len(out)
