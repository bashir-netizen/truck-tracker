# Re-prioritized roadmap (post-Wialon-audit)

## Current direction (2026-05-23)
Owner is staying in **pull-mode** for now — no Wialon-side configuration is being
performed. Configure-mode P1 items are **deferred indefinitely**; pull-mode P1 items
remain on the table.

**Active (pull-mode, read access only):**
- Voltage / power ingestion (device-tamper / power-cut signal)
- Ignition (DIN1) ingestion *if wired* (real idling detection)
- Wialon native fuel-theft / filling event ingestion (corroborates our rules)

**Deferred (need manage rights, or not feasible):**
- Geofences for known sites
- Notifications setup (real-time fuel-theft / device-offline alerts)
- Maintenance intervals + last-service logs in Wialon
- ~~"Open in Wialon" deep-links~~ — dropped as infeasible (Track Player is an in-app
  modal with no URL state); in-dashboard playback (Map, Task 3) covers it instead.

**How to read this.** Gated by the owner's Wialon access level (audit §0). "Pull"
items need only read access; "Configure" items need *manage* rights on the unit/resource.
Goal: stop duplication, integrate high-value Wialon capabilities, preserve our
differentiation (owner-perspective interpretation + audit workflows).

## P0 — decide & correct (do first)
1. **Confirm Wialon access level** (read-only token vs. manage rights). Gates all
   "Configure" items below. *(Until known, assume read-only.)*
2. **Stop presenting generic maintenance as truth.** Add a caveat to the Maintenance/Care
   surfaces now ("generic FAW intervals; baseline not set — not the truck's actual service
   history"); fill `services.yaml` with real last-service data, or ingest Wialon
   maintenance (P1). *(Directly addresses the audit's flag #3.)*
3. **Switch driver score to Wialon's native value** (stop recomputing penalty→rank); keep
   hard-safety on top. *(Flag #4; small change.)*

## P1 — high-value Wialon integrations (PULL — read access only)
- **Voltage / power** ingestion → device-tamper / power-cut signal (theft indicator).
  Feasible on FMB920 (internal supply voltage).
- **Ignition (DIN1)** ingestion *if wired* → **real idling detection** (engine-on +
  stationary), honestly filling the idling gap we currently can't compute.
- **Geofence visits** ingestion (`resource/get_zones_by_unit`) → native dwell/visits,
  reduces DBSCAN labeling for known sites (audit flag #1).
- **Wialon native fuel-theft/filling events** → corroborate our `fuel_drop`/`unusual_fill`
  rules.
- **Wialon Maintenance report** ingestion (if intervals are configured) → truck-real
  service status (flag #3).

## P1 — high-value Wialon setup (CONFIGURE — needs manage rights)
- **Notifications:** real-time **fuel theft** + **device offline** (and optionally
  geofence enter/exit on the depot) → email/SMS to owner. *Don't build alerting into our
  app* (flag #2).
- **Geofences** for the known sites; **Maintenance** intervals + last-service logs.

## P1 — Category-A integration (no write needed)
- *(Removed — not feasible.)* "Open in Wialon" deep-links: Wialon's Track Player is an
  in-app modal whose state lives in the browser session, not the URL, so there's nothing
  to deep-link to. In-dashboard playback (Map Task 3.4) covers the drill-down use case.

## P2 — our exclusive value (continue building)
- **Overview rework** (status-led "is everything okay?", confidence labels) — *the paused
  task; still valuable as our interpretation layer.* Re-incorporate audit findings: the
  real trip mix, the maintenance caveat, score-from-Wialon, geofence-aware places.
- Audit-export enhancements; events/100 km baseline over time.
- **Stage 6 billing** (when Genwatt rates known): statement reconciliation + what-if rate
  calculator — fully owner-exclusive.

## P2 — reconsider the audit-PDF
Wialon can **schedule + email a PDF report** natively. Our planned ReportLab audit-PDF
partly duplicates that. **Recommend:** use Wialon's scheduled PDF for raw tables; build a
thin owner-framed summary PDF only if it adds audit *narrative* Wialon can't. Re-evaluate
before adding the ReportLab dependency.

## Preserve (our differentiation — do not replace with Wialon)
Journey stitching + classification; corridors; **audit-export ledger**;
`consumption_drift`; hard-safety reinterpretation; night-driving inference; the
owner-perspective Overview.

## Stop / skip (don't build; not worth it for single-truck audit)
Routes, Jobs, Logistics, Tachograph, Video (FMB920 can't anyway), Hecterra/NimBus,
retransmission, iButton hardware, multi-user role management, fleet-wide scoring.

## Duplication → action (summary)
| We built | Wialon native | Action |
|---|---|---|
| DBSCAN places | Geofences + visit reports | **Hybrid:** geofence known sites + ingest visits; DBSCAN for discovery |
| 4 anomaly rules (batch) | Notifications (real-time push) | **Hybrid:** keep batch ledger; add Wialon notifications for theft/offline |
| Maintenance projection (generic) | Maintenance module (authoritative) | **Switch/Hybrid:** ingest Wialon maintenance, or caveat ours |
| Driver score recompute | Native eco score | **Switch:** ingest native score; keep hard-safety |
| (planned) custom playback | Track Player (in-app modal — no deep-link) | **Build in-dashboard** playback (Task 3.4) |
| (planned) ReportLab audit-PDF | Scheduled PDF reports | **Reconsider:** lean on Wialon scheduling |

## Known scaling limits
The Map date-filter pill strip is designed for ranges up to **~60 days**: 60–120 days the
pills get hard to scan; 120+ days the pattern fails. When typical use exceeds 60 days,
replace the pills with one of — a calendar heatmap (7-col, density-coloured cells); week/
month auto-aggregation with drill-down; or de-emphasise date filtering in favour of
class/destination/anomaly filters. Not blocking today — revisit at the first quarterly audit.

## Map polish — deferred
Brightness-within-date (earlier trips darker, later lighter); numbered start markers
("1/2/3" per day); trip selection by clicking the start marker; hover-to-highlight (hovered
path solid, others dim to 30%); perceptual palette (HCL/Oklab); date filter "context mode"
(other dates dimmed but visible). Marker key shipped (● start / ○ end / → direction, by the
controls); still to do — more distinctive end markers (a different shape, or an arrow tip
pointing in the final direction of travel) and hover labels on the start/end markers showing
the exact timestamp.

**Journey View shipped** (Task 8 — open one round trip from the Overview: outbound/return
path, numbered waypoints, timeline, events). Deferred extensions:
- Journey View **playback** (animate the truck moving along the path).
- **Side-by-side journey comparison** (e.g. this month's Marsabit run vs last month's — same
  route or a detour?).
- **Unexpected-detour detection** — flag a journey whose path deviates significantly from the
  most-common route for that destination.
- **Per-journey analytics** — this trip's L/100km, violations, and stops vs the destination's
  average; and picking among the N trips in a grouped Overview row (today the row opens the
  latest).

## Refresh button — deferred
Auto-refresh every ~30 min while the page is open; webhook callback so the page auto-reloads
when the workflow completes; per-user audit log of manual refreshes.

## Overview content — deferred
Place-name hover with a visit-history mini-chart; editorial annotations on cards ("biggest
fill: 363 L on 21 May"); time-of-day (day vs night) activity split; per-day drill-down in
Geography (monthly → daily).

## Currently out — deferred
The current-status line + "Currently out" block escalate on simple rules (away >7d → warn,
>14d or device-silent >24h → critical). Deferred refinements:
- **Auto-escalation tuning** from historical durations (learn that Marsabit runs typically take
  3–4 days, so 5+ days warns) instead of fixed 7/14-day thresholds.
- **Live in-progress trip view** — a Map mode for the open trip showing path-so-far + last known
  position (today Journey View covers completed round trips only).
- **ETA** — estimated time remaining from the median duration for that destination.
- **Live position context** — "Last position: 2.3 km SW of Siaya town centre · updated 23 min ago".

## Driver page — deferred
Per-trip violation breakdown (which trips had which types); driver-behaviour trend over time
(events/100 km by week); geographic heat-map of where violations cluster.

## Places editor — deferred
When a cluster is unlabeled or mis-labeled (e.g. DBSCAN called it "Nairobi" but it's a
specific workshop), an in-app editor would beat hand-editing `places.yaml`:
- Click a place marker on the Map → "Rename this place" → text input + optional tag
  (depot / customer / workshop).
- Save writes the entry to `places.yaml` in the repo via the GitHub API — **reuse the
  refresh-button auth** (`GITHUB_*` secrets, the `app/components/refresh.py` pattern).
- The next ingestion (or an "Update now" run) picks up the new label.

**Revisit when:** the dashboard sees enough use that manual YAML editing feels like
friction. For now (click marker → edit `places.yaml` → commit), manual editing is acceptable.

## Places — typing & geocoding (deferred)
Typed places + the dwell-time signal shipped (Task 6): each place carries a `type`
(depot/destination/transit/customer/workshop) and a dwell-derived `dwell_pattern_hint`
+ `suggested_type_from_dwell` the Map surfaces for review. Still deferred:
- **Auto-geocoding** (OSM Nominatim + optional Google Places) to suggest names *and*
  types for new clusters; the dwell hint becomes one signal among several. The seam is
  `enrich/geocode.py::suggest_place` → a git-ignored `enrich/.suggested_places.yaml` the
  owner promotes into `places.yaml`.
- **On-highway vs off-highway detection** (needs road-graph/road-class data) to sharpen
  the transit-vs-customer call — currently a brief stop is just suggested `transit?`.
- **Time-of-day dwell patterns** (overnight vs daytime stays) as a further signal.
- **Customer-site identification** from a Genwatt-provided customer list (CSV upload →
  auto-tag matching clusters as `customer`).
- **In-app place editor** and **cluster merging** in the UI (see "Places editor" above).

**Revisit when:** clusters accumulate faster than hand-typing keeps up, or Genwatt shares
a customer list. For now, the dwell summary + Map callouts make manual typing low-effort.
