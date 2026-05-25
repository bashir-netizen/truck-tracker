"""Place roles — infer each cluster's role in the truck's trips (loading customer /
delivery destination / transit) from where it sits in journeys, so the owner can spot
and label cargo points that aren't classified yet.

Derived + read-only over journeys + places; writes role columns onto the `places` table
(like the dwell stats in places.py). Relative to the home depot:
  loading      first non-depot stop after leaving home, and not the farthest point
  destination  the farthest-from-home stop of a trip (the primary delivery)
  transit      a brief pass-through
Suggestions only — the owner confirms in places.yaml.

NB the loading dwell test uses the **75th-percentile** dwell, not the median: a loading
yard mixes many quick gate/queue stops with the long loads, which drags the median below
the threshold (e.g. Bamburi's median is ~25 min though it clearly loads for hours). p75
captures "a meaningful share of visits are long loads".
"""

import json
from collections import Counter, defaultdict

from enrich.round_trips import _haversine_km

LOAD_MIN_DWELL_S = 2 * 3600      # a real load takes hours (checked against p75 dwell)
TRANSIT_MAX_DWELL_S = 1 * 3600   # brief pass-through (median)


def rebuild(con, unit_id):
    P = {int(r[0]): {"lat": r[1], "lon": r[2], "label": r[3], "type": r[4],
                     "p75": r[5] or 0, "median": r[6] or 0, "yaml": r[7]}
         for r in con.execute("SELECT place_id, lat, lon, label, type, p75_dwell_s, "
                              "median_dwell_s, yaml_labeled FROM places")}
    depot_ids = {pid for pid, p in P.items() if p["type"] == "depot"}
    jrows = con.execute(
        "SELECT origin_place_id, dest_place_id, start_ts FROM journeys WHERE unit_id=? "
        "ORDER BY start_ts", (unit_id,)).fetchall()
    if not depot_ids:                                  # fallback: most-frequent origin = home
        c = Counter(int(o) for o, _d, _t in jrows if o is not None)
        depot_ids = {c.most_common(1)[0][0]} if c else set()

    # Segment the journey stream at each departure FROM a depot (start of a trip from home).
    segments, cur = [], []
    for o, d, ts in jrows:
        o = int(o) if o is not None else None
        if o in depot_ids and cur:
            segments.append(cur)
            cur = []
        cur.append((o, int(d) if d is not None else None, ts))
    if cur:
        segments.append(cur)

    total = defaultdict(int)
    loading, destination, via = defaultdict(int), defaultdict(int), defaultdict(int)
    loaded_before = defaultdict(Counter)   # loading place_id -> {destination label: n}

    for seg in segments:
        if seg[0][0] not in depot_ids:     # only trips that actually start at home
            continue
        depot = P.get(seg[0][0], {})
        dests = [(d, ts) for (_o, d, ts) in seg if d is not None and d not in depot_ids]
        if not dests:
            continue
        far = max((d for d, _ in dests),
                  key=lambda pid: _haversine_km(depot.get("lat"), depot.get("lon"),
                                                P.get(pid, {}).get("lat"), P.get(pid, {}).get("lon")))
        far_label = P.get(far, {}).get("label", "?")
        for idx, (d, _ts) in enumerate(dests):
            total[d] += 1
            if d == far:
                destination[d] += 1
            elif idx == 0:                 # first non-depot stop after leaving home
                loading[d] += 1
                loaded_before[d][far_label] += 1
            else:
                via[d] += 1

    # Same-label clusters can be ONE facility split across DBSCAN clusters (~km apart):
    # e.g. Bamburi's journey-arrivals land on one cluster while its long loads register on
    # another. Classify at the label-group level so a split signal still reads correctly.
    groups = defaultdict(list)
    for pid, p in P.items():
        groups[p["label"]].append(pid)

    def _group_role(pids):
        gt = sum(total.get(x, 0) for x in pids)
        gl = sum(loading.get(x, 0) for x in pids)
        gd = sum(destination.get(x, 0) for x in pids)
        gp75 = max((P[x]["p75"] for x in pids), default=0)        # the cluster that actually loads
        gmed = P[max(pids, key=lambda x: total.get(x, 0))]["median"]  # busiest cluster's median
        lsh = gl / gt if gt else 0.0
        dsh = gd / gt if gt else 0.0
        if lsh >= 0.5 and gp75 >= LOAD_MIN_DWELL_S:
            return "loading"
        if dsh >= 0.5:
            return "destination"
        if gmed and gmed < TRANSIT_MAX_DWELL_S and gt >= 2:
            return "transit"
        return "ambiguous"

    role_by_label = {lab: _group_role(pids) for lab, pids in groups.items()}

    for pid, p in P.items():
        t = total.get(pid, 0)
        lo, de, vi = loading.get(pid, 0), destination.get(pid, 0), via.get(pid, 0)
        lo_share = round(lo / t, 2) if t else 0.0
        de_share = round(de / t, 2) if t else 0.0
        role = role_by_label[p["label"]]
        ctx = ({"loaded_before": dict(loaded_before.get(pid, {}))} if role == "loading"
               else {"farthest_point": True} if role == "destination" else {})
        con.execute(
            "UPDATE places SET total_visits=?, loading_visits=?, destination_visits=?, "
            "via_visits=?, loading_share=?, destination_share=?, suggested_role=?, "
            "role_context=? WHERE place_id=?",
            (t, lo, de, vi, lo_share, de_share, role, json.dumps(ctx), pid))

    yaml_by_label = {p["label"]: p["yaml"] for p in P.values()}
    n_suggest = sum(1 for lab, role in role_by_label.items()
                    if role in ("loading", "destination") and not yaml_by_label.get(lab))
    _print_summary(con)
    return n_suggest


def _fmt(s):
    if not s:
        return "—"
    s = int(s)
    h, m = s // 3600, (s % 3600) // 60
    return f"{h}h{m:02d}m" if h else f"{m}m"


def _print_summary(con):
    rows = con.execute(
        "SELECT label, type, yaml_labeled, total_visits, loading_visits, destination_visits, "
        "median_dwell_s, p75_dwell_s, loading_share, destination_share, suggested_role "
        "FROM places ORDER BY (suggested_role='loading') DESC, total_visits DESC").fetchall()

    # Calibration FIRST: a KNOWN loading customer (Bamburi) must read 'loading'.
    bam = [r for r in rows if r[0] and r[0].startswith("Bamburi")]
    print("  place_roles — BAMBURI CALIBRATION (known loading customer; must be 'loading'):")
    c_lo = c_t = 0
    for lab, typ, yl, t, lo, de, med, p75, lsh, dsh, role in bam:
        c_lo += lo or 0
        c_t += t or 0
        flag = "OK" if role == "loading" else "!! NOT loading — re-tune"
        print(f"    {lab[:24]:24} v={t} load={lo} dest={de} median={_fmt(med)} p75={_fmt(p75)} "
              f"load_share={lsh} -> {role}  [{flag}]")
    if c_t:
        print(f"    combined: load_share={c_lo / c_t:.2f} over {c_t} visits "
              f"({'PASS' if c_lo / c_t >= 0.5 else 'FAIL'})")

    print("  place_roles — all places (name · type · own · visits · median · load% · dest% · role):")
    for lab, typ, yl, t, lo, de, med, p75, lsh, dsh, role in rows:
        mism = ""
        if role == "loading" and typ != "customer":
            mism = "  <- role≠type"
        elif role == "transit" and typ != "transit":
            mism = "  <- role≠type"
        print(f"    {(lab or '?')[:24]:24} {typ or '?':11} own={'y' if yl else '-'} "
              f"v={t or 0:<2} med={_fmt(med):>6} load={lsh or 0:.2f} dest={dsh or 0:.2f} "
              f"{role or '-'}{mism}")
