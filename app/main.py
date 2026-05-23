"""Overview — is everything okay with the truck? Status first, then the story."""

import pathlib
import sys
from collections import Counter
from datetime import datetime, timezone

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "config.py").exists())
sys.path.insert(0, str(ROOT))

import json  # noqa: E402

import plotly.express as px  # noqa: E402
import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402

import config  # noqa: E402
from app.components import (db, hero_summary, journey_row, status_panel,  # noqa: E402
                            status_strip, theme, thumbnail_map, trip_mix_line)
from app.components.empty_state import empty_state  # noqa: E402
from app.components.format import format_kes, relative_day  # noqa: E402
from app.components.metric_card import metric_card  # noqa: E402
from billing import estimate  # noqa: E402

theme.page_setup("Overview")

if not db.has_data():
    theme.header("Overview")
    empty_state("No data yet",
                "Run <code>python -m ingest.run</code> then "
                "<code>python -m enrich.run</code> to populate the database.")
    st.stop()

frm, to, label = theme.period_selector()
theme.freshness_caption()

CLASS_LABELS = {"long_haul": "long-haul", "regional": "regional",
                "local": "local", "yard": "yard"}
PERIOD_WORD = {"Last 7 days": "this week", "Last 30 days": "this month",
               "This month": "this month"}
RANK = {"long_haul": 3, "regional": 2, "local": 1, "yard": 0}


def psum(col, table="trips", ts="start_ts", lo=None, hi=None):
    lo, hi = (frm if lo is None else lo), (to if hi is None else hi)
    return db.scalar(f"SELECT COALESCE(SUM({col}),0) FROM {table} WHERE {ts} BETWEEN ? AND ?",
                     (lo, hi), 0) or 0


# --- core figures ---------------------------------------------------------
span = to - frm
dist_km = psum("distance_m") / 1000.0
prev_km = psum("distance_m", lo=frm - span, hi=frm) / 1000.0
has_prev = (db.scalar("SELECT COUNT(*) FROM trips WHERE start_ts < ?", (frm,), 0) or 0) > 0
fuel_l = psum("consumed_l")
active_days = int(db.scalar("SELECT COUNT(DISTINCT strftime('%Y-%m-%d', start_ts, 'unixepoch')) "
                            "FROM trips WHERE start_ts BETWEEN ? AND ?", (frm, to), 0) or 0)
period_days = max(1, round(span / 86400))
util = active_days / period_days * 100

mix = {r.journey_character: int(r.n) for r in db.q(
    "SELECT journey_character, COUNT(*) n FROM journeys WHERE start_ts BETWEEN ? AND ? "
    "GROUP BY journey_character", (frm, to)).itertuples()}
hard = int(db.scalar("SELECT COUNT(*) FROM eco_flags WHERE hard_safety=1 AND ts BETWEEN ? AND ?",
                     (frm, to), 0) or 0)
eco_total = int(db.scalar("SELECT COUNT(*) FROM eco_events WHERE ts BETWEEN ? AND ?",
                          (frm, to), 0) or 0)
per100 = eco_total / (dist_km / 100) if dist_km else 0
score = db.scalar("SELECT score FROM driver_score ORDER BY period_start DESC LIMIT 1")
score_s = f"{score:.1f}" if score is not None else "—"

filled = psum("volume_l", table="fillings", ts="ts")
diesel = config.RATES["diesel_kes_per_l"]

P = {int(r.place_id): r.label for r in db.q("SELECT place_id, label FROM places").itertuples()}


def delta_pct(cur, prev):
    """('+12% vs last period', 'up'|'down') or the honest first-period note."""
    if not has_prev or not prev:
        return "first full period — no prior data to compare", "flat"
    pct = (cur - prev) / prev * 100
    return f"{pct:+.0f}% vs last period", ("up" if pct >= 0 else "down")


# --- header ---------------------------------------------------------------
hl, hr = st.columns([5, 1])
with hl:
    desc = " ".join(config.UNIT_DESCRIPTION.split())
    pills = f'<span class="tt-pill accent">{config.UNIT_DISPLAY_NAME}</span>'
    for part in [p.strip() for p in desc.replace("·", "|").split("|") if p.strip()]:
        pills += f' <span class="tt-pill neutral">{part}</span>'
    st.markdown(f'<div style="display:flex;gap:.4rem;flex-wrap:wrap;align-items:center">{pills}'
                f'</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="tt-title">Your truck {PERIOD_WORD.get(label, "this period")}</div>',
                unsafe_allow_html=True)
    st.markdown(f'<div class="tt-sub">{label} · is everything okay with the truck?</div>',
                unsafe_allow_html=True)
with hr:
    components.html(
        '<button onclick="window.top.print()" style="width:100%;font:600 13px '
        '-apple-system,sans-serif;background:#fff;border:1px solid #e6e8ec;border-radius:8px;'
        'padding:.4rem .5rem;cursor:pointer;color:#0e1116">⤓ Share PDF</button>',
        height=44)

items = status_panel.gather(frm, to)
status_strip.render(items)

# === Section 1 — Status ===================================================
st.markdown('<div style="height:1.2rem"></div>', unsafe_allow_html=True)
status_panel.render(items)

# === Section 2 — Hero summary (one prose line) ==========================
st.markdown('<div style="height:1.8rem"></div>', unsafe_allow_html=True)
dist_dt, dist_dir = delta_pct(dist_km, prev_km)
mix_str = " · ".join(f"{mix[c]} {CLASS_LABELS[c]}"
                     for c in ["long_haul", "regional", "local", "yard"] if mix.get(c)) or "—"
_O, _I = theme.confidence_badge("observed"), theme.confidence_badge("inferred")
hero_summary.render(
    f'<b>{active_days} active day{"s" if active_days != 1 else ""}</b> '
    f'{PERIOD_WORD.get(label, "this period")}: '
    f'<b>{dist_km:,.0f} km</b> {_O}, <b>{fuel_l:,.0f} L</b> fuel '
    f'(≈ {format_kes(estimate.fuel_cost(filled, diesel))}) {_I}, '
    f'<b>{mix_str}</b> {_I}, '
    f'<b>{hard} hard-safety event{"s" if hard != 1 else ""}</b> {_O}.')

# === Section 3 — Three supporting cards ==================================
st.markdown('<div style="height:1.2rem"></div>', unsafe_allow_html=True)
daily = db.q("SELECT strftime('%Y-%m-%d', start_ts, 'unixepoch') d, SUM(distance_m)/1000.0 km "
             "FROM trips WHERE start_ts BETWEEN ? AND ? GROUP BY d ORDER BY d", (frm, to))
spark = [float(v) for v in daily["km"]] if not daily.empty else None
c1, c2, c3 = st.columns(3)
with c1:
    metric_card("Distance", f"{dist_km:,.0f}", unit="km", confidence="observed",
                icon="route", sparkline=spark, delta_text=dist_dt, delta_direction=dist_dir)
with c2:
    metric_card("Fuel", f"{fuel_l:,.0f}", unit="L", confidence="inferred", icon="droplet",
                source=f"≈ {format_kes(estimate.fuel_cost(filled, diesel))} at EPRA Nairobi "
                       f"ref · KES {diesel}/L")
with c3:
    metric_card("Activity", f"{active_days} of {period_days}", unit="days", confidence="inferred",
                icon="activity", delta_text=f"{util:.0f}% utilization", delta_direction="flat",
                source=f"{active_days} active · {period_days - active_days} idle days")

# === Section 4 — Geography (round trips) =================================
st.markdown('<div style="height:1.8rem"></div>', unsafe_allow_html=True)
st.markdown('<div class="tt-h2">Where it went</div>', unsafe_allow_html=True)

depot_ids = {int(r.place_id) for r in db.q("SELECT place_id FROM places WHERE type='depot'").itertuples()}
depots = [P.get(i, "—") for i in depot_ids]
rts = db.q("SELECT primary_destination_name dest, journey_class cls, total_distance_km km, "
           "total_duration_s dur, via_places via, return_via_places rvia, start_ts, end_ts "
           "FROM round_trips WHERE start_ts BETWEEN ? AND ? ORDER BY start_ts", (frm, to))
last_return = int(rts["end_ts"].max()) if not rts.empty else 0

gcol, mcol = st.columns([3, 2])
with gcol:
    if depots:
        ret = f" — last returned {relative_day(last_return)}" if last_return else ""
        st.markdown(f'<div class="tt-small" style="margin-bottom:.5rem"><b>Home base:</b> '
                    f'{", ".join(depots)}{ret}</div>', unsafe_allow_html=True)
    trip_mix_line.render(mix)

    if rts.empty:
        empty_state("No completed round trips this period")
    else:
        groups = {}
        for r in rts.itertuples():
            if r.cls in ("long_haul", "regional"):
                key, title = (r.dest or "—"), f"{r.dest or '—'} run"
            elif r.cls == "local":
                key, title = "__local__", None
            else:
                key, title = "__yard__", "Yard movements"
            g = groups.setdefault(key, {"title": title, "cls": r.cls, "count": 0,
                                        "last_start": 0, "last_end": 0, "km": 0.0, "dur": 0,
                                        "via": [], "rvia": [], "dests": []})
            g["count"] += 1
            if int(r.end_ts) >= g["last_end"]:        # track the most-recent trip's span
                g["last_end"], g["last_start"] = int(r.end_ts), int(r.start_ts)
            g["km"] += r.km or 0
            g["dur"] += int(r.dur or 0)
            g["via"] += json.loads(r.via)
            g["rvia"] += json.loads(r.rvia)
            g["dests"].append(r.dest)
            if RANK.get(r.cls, 0) > RANK.get(g["cls"], 0):
                g["cls"] = r.cls
        if "__local__" in groups:
            gl = groups["__local__"]
            common = Counter(d for d in gl["dests"] if d).most_common(1)
            gl["title"] = f"Local {common[0][0]} work" if common else "Local work"
        for g in sorted(groups.values(), key=lambda x: (RANK.get(x["cls"], 0), x["count"]),
                        reverse=True):
            via, rvia = list(dict.fromkeys(g["via"])), list(dict.fromkeys(g["rvia"]))
            if g["cls"] in ("long_haul", "regional"):
                bits = []
                if via:
                    bits.append("via " + ", ".join(via) + " (out)")
                if rvia:
                    bits.append(", ".join(rvia) + " (return)")
                context = " · ".join(bits) or "out and back"
            elif g["cls"] == "local":
                context = "Around " + g["title"].replace("Local ", "").replace(" work", "")
            else:
                context = "Within the yard"
            journey_row.render(g["title"], CLASS_LABELS.get(g["cls"], g["cls"]), g["count"],
                               context, theme.fmt_date_range(g["last_start"], g["last_end"]),
                               g["km"] / g["count"], theme.fmt_dur(g["dur"] // g["count"]),
                               multi=g["count"] > 1)

    # currently out (left a depot, not yet returned)
    openj = db.q("SELECT dest_place_id, start_ts FROM journeys WHERE start_ts > ? "
                 "AND start_ts BETWEEN ? AND ? ORDER BY start_ts", (last_return, frm, to))
    if not openj.empty:
        d_last = openj.iloc[-1]["dest_place_id"]
        if d_last == d_last and int(d_last) not in depot_ids:   # not NaN, not a depot
            st.markdown('<div class="tt-small" style="margin-top:.5rem;color:var(--accent)">'
                        f'<b>Currently out:</b> at {P.get(int(d_last), "—")} since '
                        f'{theme.fmt_dt(int(openj.iloc[0]["start_ts"]), False)}</div>',
                        unsafe_allow_html=True)

    n_hidden = db.scalar(
        "SELECT COUNT(DISTINCT pv.place_id) FROM place_visits pv JOIN places p "
        "ON p.place_id=pv.place_id WHERE pv.ts BETWEEN ? AND ? "
        "AND (p.needs_label=1 OR p.type='transit')", (frm, to), 0) or 0
    if n_hidden:
        st.markdown(f'<div class="tt-small" style="margin-top:.5rem">{n_hidden} unlabeled or '
                    f'transit stop{"s" if n_hidden != 1 else ""} not shown</div>',
                    unsafe_allow_html=True)
        st.page_link("pages/1_Map.py", label="Open full map →")
with mcol:
    corr = [json.loads(r.path_geojson) for r in db.q(
        "SELECT path_geojson FROM corridors").itertuples() if r.path_geojson]
    pts = [(lon, lat) for lon, lat in db.q("SELECT lon, lat FROM places").itertuples(index=False)]
    thumbnail_map.render(corr, pts, height=210)

# === Section 5 — Cost & value ===========================================
st.markdown('<div style="height:1.8rem"></div>', unsafe_allow_html=True)
st.markdown('<div class="tt-h2">Cost &amp; value</div>', unsafe_allow_html=True)
km_rates = {c: config.RATES[f"{c}_kes_per_km"] for c in ("long_haul", "regional", "local")}
cc1, cc2 = st.columns(2)
with cc1:
    metric_card("Estimated fuel cost", format_kes(estimate.fuel_cost(filled, diesel)),
                confidence="inferred", icon="fuel",
                source=f"{filled:,.0f} L filled × KES {diesel}/L (EPRA Nairobi ref)")
with cc2:
    if any(v is not None for v in km_rates.values()):
        routes = [(r.journey_character, r.distance_m) for r in db.q(
            "SELECT journey_character, distance_m FROM journeys WHERE is_local=0 "
            "AND start_ts BETWEEN ? AND ?", (frm, to)).itertuples()]
        total, _, _, _ = estimate.revenue_by_class(routes, km_rates)
        metric_card("Revenue", format_kes(total), confidence="inferred", icon="banknote")
    else:
        metric_card("Revenue", "", confidence="missing", icon="banknote")

# === Section 6 — Truck care =============================================
st.markdown('<div style="height:1.8rem"></div>', unsafe_allow_html=True)
st.markdown('<div class="tt-h2">Truck care</div>'
            '<div class="tt-small" style="margin:-.1rem 0 .6rem">Driver behaviour and '
            'maintenance status.</div>', unsafe_allow_html=True)
vcounts = {r.type: int(r.n) for r in db.q(
    "SELECT type, COUNT(*) n FROM eco_events WHERE ts BETWEEN ? AND ? GROUP BY type",
    (frm, to)).itertuples()}
ranked = theme.top_violations(vcounts)
if not ranked:
    vsub = f"{eco_total} events · {per100:.1f} per 100 km"
elif len(ranked) > 1 and ranked[1][1] >= ranked[0][1] * 0.8:
    vsub = (f"{eco_total} events total · {ranked[0][0]} ({ranked[0][1]}), "
            f"{ranked[1][0]} ({ranked[1][1]}) · {per100:.1f} per 100 km")
else:
    vsub = (f"{eco_total} events total · mostly {ranked[0][0]} ({ranked[0][1]}) · "
            f"{per100:.1f} per 100 km")
care1, care2 = st.columns(2)
with care1:
    if hard:
        head, hcolor, border = (f"{hard} hard-safety event{'s' if hard != 1 else ''}",
                                "var(--critical)", "")
    else:
        head, hcolor, border = ("✓ No hard-safety events", "var(--ok)",
                                "border-left:3px solid var(--ok)")
    st.markdown(
        f'<div class="tt-card" style="{border}">'
        f'<div style="display:flex;justify-content:space-between;align-items:center">'
        f'<div class="lbl">Driver behaviour</div>{theme.confidence_badge("observed")}</div>'
        f'<div class="val" style="font-size:20px;color:{hcolor}">{head}</div>'
        f'<div class="tt-small" style="margin-top:.3rem">{vsub}</div>'
        f'<div class="src">Wialon score {score_s}/10 — reference (calibrated for Europe; '
        f'see Driver)</div></div>', unsafe_allow_html=True)
    st.page_link("pages/3_Driver.py", label="View Driver →")
with care2:
    svc = db.q("SELECT service_type, km_remaining, due FROM service_status ORDER BY km_remaining")
    if svc.empty:
        metric_card("Service status", "—", confidence="missing")
    else:
        nxt = svc.iloc[0]
        due_now = svc[svc["due"] == 1]
        if not due_now.empty:
            names = ", ".join(s.replace("_", " ") for s in due_now["service_type"])
            metric_card("Service due now", names.title(), tone="alert", confidence="inferred",
                        icon="wrench", source="Generic FAW intervals, 0 km baseline — not the "
                        "truck's real history. Update services.yaml.")
        else:
            metric_card("Next service", f"{nxt['km_remaining']:,.0f}", unit="km",
                        confidence="inferred", icon="wrench",
                        hint=f"{nxt['service_type'].replace('_', ' ')}",
                        source="Generic FAW intervals, 0 km baseline — not the truck's real "
                        "history. Update services.yaml.")
    st.page_link("pages/5_Maintenance.py", label="View Maintenance →")

# === Distance-by-day chart (D3) =========================================
st.markdown('<div style="height:1.8rem"></div>', unsafe_allow_html=True)
st.markdown('<div class="tt-h3">Distance by day</div>', unsafe_allow_html=True)
if daily.empty:
    empty_state("No trips in this period", "Try a wider period in the sidebar.")
else:
    peak = daily.loc[daily["km"].idxmax()]
    peak_d = datetime.strptime(peak["d"], "%Y-%m-%d")
    st.markdown(f'<div class="tt-small">Peaked {peak_d:%d %b} — {peak["km"]:,.0f} km</div>',
                unsafe_allow_html=True)
    daily = daily.assign(lbl=daily["d"].map(lambda s: datetime.strptime(s, "%Y-%m-%d").strftime("%d %b")))
    fig = px.bar(daily, x="lbl", y="km")
    fig.update_traces(marker_color=theme.ACCENT, marker_line_width=0,
                      hovertemplate="%{x}<br>%{y:.0f} km<extra></extra>")
    try:
        fig.update_traces(marker_cornerradius=4)   # rounded tops (newer plotly)
    except Exception:
        pass
    fig.update_yaxes(title=None)
    fig.update_xaxes(title=None, dtick=5)
    fig.update_layout(bargap=0.45)
    st.plotly_chart(theme.style_fig(fig, height=240), width="stretch")
    trip_mix_line.render(mix)

st.caption("Use the sidebar for the map, fuel, driver, utilization, maintenance, anomalies, "
           "and the audit export.")
