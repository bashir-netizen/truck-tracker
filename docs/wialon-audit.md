# Wialon capability audit — KDX 415X (FMB920) owner-audit dashboard

**Purpose.** Catalog Wialon Hosting's native capabilities, catalog ours, reconcile
them, and flag where we rebuild what Wialon already does. Scope: one truck, owner
auditing subcontractor Genwatt. Sources: help.wialon.com, sdk.wialon.com,
wiki.teltonika-gps.com (cited at end). Researched 2026-05-23.

## 0. Cross-cutting blocker — the owner's Wialon access level
Every "configure it in Wialon" recommendation depends on **what the owner's token can
do**. Wialon's model: a **Resource** (holds geofences, notifications, reports,
drivers, service intervals) owned by an **Account**, with per-user access rights. If
the owner audits a unit inside **Genwatt's** resource via a read-only token, the owner
can **read** data but **cannot create** geofences/notifications/maintenance intervals.

- **Action (P0):** determine whether the owner is (a) a user with *manage* rights on
  the unit/resource, or (b) a read-only token. Check token flags / ask Genwatt.
- **Until known, assume read-only** → prefer *ingesting* Wialon data over *configuring*
  Wialon. (API: `core/search_items`, `resource/get_resource_data` reveal what's
  accessible.)

## 1. Wialon Hosting capability catalog (STEP 1)
API = remote-API availability. FMB920 = does our device support the underlying data.
Acct = best-effort guess our account has it (✓ = we already receive it; "verify" = unknown).

### FMB920 hardware reality (governs feasibility)
GNSS + GSM + **internal 3-axis accelerometer** (eco works) + BT 4.0. **1 digital input**
(DIN1, typically ignition), **1 analog input** (AIN1 0–30 V, e.g. fuel sender), **1
digital output**. **No CAN bus.** **No camera/video.** No native 1-Wire (iButton needs
external reader). Fuel must come from an **analog/BLE sensor** or **consumption math** —
never OBD/CAN. *Empirically we receive `unit_fillings` with a `sensor_name`, so a
fuel-level sensor IS configured on this unit.*

| Capability | UI location | API | FMB920 | Acct |
|---|---|---|---|---|
| Positions / track | Monitoring; Reports | yes (`messages/load_interval`) | full (GNSS) | ✓ |
| Messages / IO params | Unit→Sensors; Reports | yes (`messages/load_interval`) | partial (1 DIN/1 AIN/1 DOUT, accel ax/ay/az) | ✓ |
| Trip & parking detection | Unit→Trip Detector; Reports | yes (report `unit_trips`/`unit/get_trips`) | full (GPS) | ✓ |
| Mileage / odometer | Unit→General; Reports | yes (`core/search_items` `cnm`) | full (GPS-derived) | ✓ |
| **Fuel level sensor** + theft/fill detection | Unit→Sensors/Fuel; Notifications | yes (`unit/update_fuel_level_params`, report `unit_fillings`) | partial (analog/BLE; **no CAN**) | ✓ (sensor present) |
| Ignition (engine on/off) | Unit→Sensors | yes (`unit/update_sensor` on DIN1) | full **if DIN1 wired** | verify |
| Voltage / power | Unit→Sensors | yes (sensor / msg param) | partial (internal supply V; AIN1) | not ingested |
| Temperature | Unit→Sensors | yes (`unit/update_sensor`) | needs external sensor | n/a |
| Custom/virtual sensors | Unit→Sensors | yes (`unit/update_sensor`) | full (formulae on params) | unused |
| **Eco Driving** (harsh accel/brake/corner, speeding) | Unit→Eco Driving; Reports | partial (report `unit_ecodriving`; no per-event endpoint) | full (accelerometer) | ✓ (we ingest it) |
| **Eco rank/score (0–10)** | Eco Driving tab / widget | **no** — UI-only (see † below) | full | computed locally |
| **Geofences** (zones) enter/exit/dwell | Resources→Geofences; Reports | yes (`resource/update_zone`, `resource/get_zones_by_unit`) | full (server-side) | **not used** |
| **Notifications** (rule engine) | Monitoring→Notifications | yes (`resource/update_notification`) | full | **not used** |
| — channels: email / SMS / Telegram / **webhook** | (notification actions) | yes | — | verify (SMS needs setup) |
| **Maintenance / service intervals** + logs | Unit→Service Intervals; Reports | yes (`unit/update_service_interval`) | full | **not used** |
| **Reports**: templates, PDF/XLSX export, **scheduling** | Monitoring→Reports; Jobs | yes (`report/exec_report`; schedule via jobs) | full | ✓ (we exec reports) |
| Track Player / **Locator deep-link** | Monitoring→Tools; Locator | partial (no playback API; share via `token/update`) | full | ✓ (core) |
| Drivers: assignment / reporting | Unit→Drivers; Resources | yes (`resource/bind_unit_driver`) | manual=full; **iButton needs external reader** | verify |
| Routes / checkpoints / deviation | Logistics app | yes (`route/*`) — **add-on** | full (GPS) | likely no |
| Jobs / delivery assignment & completion | Logistics app | yes (`order/*`) — **add-on** | n/a | likely no |
| Maps / tile providers / geocoding | Maps subsystem | partial (server-side) | n/a | ✓ (we use own pydeck/Carto) |
| Multi-user / roles / sub-accounts | Management System | partial (admin UI) | n/a | **governs access (§0)** |
| Retransmission (Protocoller) | app | partial — add-on | n/a | no (we pull via API) |
| Mobile: Wialon client / WiaTag | apps | n/a | n/a | client ✓ (free) |
| Tachograph | Tacho apps | partial (file API) | **no reader; n/a in Kenya** | no |
| Video | Monitoring→Video | no | **FMB920 has no camera** | no |
| Ecosystem apps (Fleetrun, Hecterra, NimBus) | separate | varies | n/a | no (not relevant) |
| User-activity audit log | Administration | partial | n/a | ✓ (could verify Genwatt actions) |

> Note on Eco Driving: the two web sources disagreed (marketplace app vs. standard).
> **Empirically resolved:** we already ingest the `unit_ecodriving` report, so eco data
> *is* enabled on this account. The fancy marketplace "Eco Driving app" is a separate
> fleet UI we don't need.

> **† Empirical correction (2026-05-23).** This row first read "Eco rank/score (0–10) —
> partial (server-side, in report)". Verified **false** against the live API: the 0–10
> rank is computed server-side but is **not exposed via the remote report API** for
> tokens like ours — the `unit_ecodriving` report returns only violation rows, and
> requested `rank`/`rating`/`penalties`/`count`/`grade` columns are silently dropped
> (`stats` and `total` come back empty). So we reproduce the rank locally from the same
> penalty points (see `enrich/driver.py`, `docs/scoring.md`). This is exactly the kind
> of capability-vs-reality gap the audit was meant to catch.

## 2. Our dashboard capability catalog (STEP 2)
"Dup?" = duplicates a native Wialon capability. "Audit value" = owner-specific
interpretation Wialon doesn't provide.

### Ingest (raw, 1:1 from Wialon)
| Capability | File | Wialon source | Dup? | Audit value |
|---|---|---|---|---|
| Unit state (odometer, engine-h, pos) | `ingest/unit_state.py` | `core/search_items` | no | — |
| Trips (+ `consumed_l`) | `ingest/trips.py` | report `unit_trips` (`fuel_consumption_all` = **math: mileage×rate**) | partial | feeds journeys/economy |
| Fuel fillings | `ingest/fillings.py` | report `unit_fillings` (**sensor-based**, `sensor_name`) | partial | derives `level_after_l` for overfill rule |
| Eco events | `ingest/eco_events.py` | report `unit_ecodriving` | **yes** | re-interpreted as hard-safety |
| Parkings / stops | `ingest/parkings.py`/`stops.py` | report `unit_stays`/`unit_stops` | partial | seed DBSCAN places / harsh-count windows |
| GPS positions | `ingest/positions.py` | `messages/load_interval` | no | 25 m decimation for corridors |
| Ingestion log | `ingest/run.py` | ours | no | freshness contract |

### Enrich (derived) & app (display)
| Capability | File | Dup? | Audit value |
|---|---|---|---|
| **Places** (DBSCAN, eps 800 m) | `enrich/places.py` | **vs Geofences** | auto-discovers stops; `places.yaml` naming |
| **Journeys** (stitch legs across <3 h stops; classify long_haul/regional/local/yard; night-driving) | `enrich/journeys.py` | no | Wialon doesn't stitch/classify — **our value** |
| Trip metrics (L/100 km, harsh counts) | `enrich/metrics.py` | no | per-trip economy for audit |
| Corridors (RDP-simplified paths, by place-pair) | `enrich/corridors.py` | no | route aggregation for map |
| Eco flags (hard-safety = extreme only) | `enrich/eco.py` | no | road-condition-aware reinterpretation |
| **Driver score (0–10)** recomputed from penalties | `enrich/driver.py` | **vs native eco score** | reference; we recompute what Wialon already has |
| **Service status** from config defaults + `services.yaml` | `enrich/maintenance.py` | **vs Maintenance module** | generic intervals, 0 baseline (**not truck-real**) |
| **Anomalies** (4 rules) | `enrich/anomalies.py` | **vs Notifications** | batch audit rules; `consumption_drift` is ours |
| Pages: Overview, Map, Fuel, Driver, Utilization, Maintenance, Anomalies, **Audit Export** | `app/` | no | owner-framed; audit ledger = our core value |

## 3. Reconciliation (STEP 3)
- **A — Use Wialon directly (link, don't rebuild):** real-time alert *delivery*
  (email/SMS/Telegram/webhook); full basemap + geocoding; user-activity log;
  (Video/Routes/Jobs if ever needed). *(Track Player playback can't be deep-linked — it's
  an in-app modal with no URL state — so we build in-dashboard playback instead.)*
- **B — Pull data, surface with our framing:** trips, fillings, eco events,
  parkings/stops, positions, odometer/engine-hours; **+ candidates:** voltage/power,
  ignition, geofence visits, Wialon's native eco score, Wialon native maintenance status.
- **C — Wialon primitives + our interpretation:** eco events → hard-safety; trips →
  journey stitching/classification; geofence enter/exit → audit framing; fuel sensor →
  reconciliation.
- **D — Dashboard-exclusive (our differentiation):** journey stitching+classification,
  corridors, **audit-export ledger (line-by-line statement check)**, `consumption_drift`,
  events/100 km baseline, night-driving inference, the "is everything okay?" Overview,
  what-if rate calc + statement reconciliation (deferred, Stage 6).
- **E — Skip:** Routes, Jobs, Logistics, Tachograph, Video, Hecterra/NimBus,
  Retransmission, multi-user role mgmt, iButton hardware, fleet-wide scoring leaderboards.

## 4. Duplication flags (STEP 4)
**(1) DBSCAN places vs Wialon Geofences.** We auto-cluster; Wialon offers precise manual
zones with native dwell/visit reports that can also drive notifications. *Trade-off:*
DBSCAN = zero-setup discovery but fuzzy + needs labeling; geofences = exact + reusable
but manual + need write access. **Recommend HYBRID:** define geofences for the few known
sites (Genwatt office Athi River, Nairobi ICD, Marsabit, Kenol), ingest geofence visits;
keep DBSCAN for *discovery* of unknown stops.

**(2) Our 4 anomaly rules vs Wialon Notifications.** Ours are batch (≤3 h late), pull-only,
but version-controlled and customizable (`consumption_drift` is genuinely ours). Wialon
notifications are real-time + push, with native fuel-theft tuned to the sensor and
loss-of-connection alerts. *Trade-off:* don't rebuild real-time delivery in a pull app.
**Recommend HYBRID:** keep batch rules for the audit ledger/dashboard; set up Wialon
notifications for time-critical **fuel theft** + **device offline** (real-time email/SMS).
**Do not** add alert delivery to our app.

**(3) Maintenance projection vs Wialon Maintenance module.** **Strongest duplication.**
Ours uses generic FAW intervals off a **0 baseline** → not truck-real. Wialon's module is
authoritative (its odometer + engine-hours + calendar, service logs, overdue flags,
reminders). **Recommend SWITCH/HYBRID:** if owner has write access, set real intervals +
log last service in Wialon and **ingest the Maintenance report**; if read-only, keep ours
but **caveat it as generic** until `services.yaml` holds real last-service data. *(Until
then, the Care card must not present these as authoritative.)*

**(4) Driver score reproduction vs native eco score.** We recompute Wialon's 0–10 rank
from penalty points; Wialon already produces this number. **Recommend SWITCH:** ingest
Wialon's native score (cross-checkable by construction) and drop the recompute; keep our
hard-safety reinterpretation on top.

*Minor:* corridor rendering is fine for the static overview; for **playback** we build a
self-contained in-dashboard track player (Map Task 3.4). Wialon's Track Player is an
in-app modal with no URL state, so it can't be deep-linked to a specific moment.

## Appendix — verifications (from our DB/code)
- **Trip mix (all data, 13 journeys):** long_haul 4 (1,897 km; incl. Marsabit→Nairobi 559
  km ✓ and Kenol→Marsabit 494 km), regional 3, local 4, yard 2. Thresholds
  (`enrich/journeys.py`): long_haul ≥300 km or ≥24 h; regional ≥80 km; local ≥5 km. **No
  artificial splitting.**
- **Fuel:** fillings = **sensor** (report `unit_fillings`, `sensor_name`; e.g. +329.5 L,
  31.8→361.3); `trips.consumed_l` = **math** (`fuel_consumption_all` ≈ mileage×rate ≈
  21 L/100 km). Both from Wialon.
- **Maintenance:** generic config defaults (oil 15 k/500 h, transmission 60 k, air 30 k,
  major 90 k km); baseline from `services.yaml` (**absent → 0**); odometer ≈ 2,468 km;
  all "not due". Not from Wialon's module.
- **Places:** 18 via DBSCAN (eps 800 m, haversine); e.g. Genwatt office (Athi River) 15
  visits / 27.4 h. **No geofence/zone ingestion anywhere.**
- **Anomalies:** 4 own rules (`unusual_fill` >550 L or >577.5 L; `fuel_drop` >55 L
  unaccounted; `consumption_drift` >baseline×1.2 weekly; `device_silent` >24 h); all 0
  now. **No Wialon notification ingestion.**

## Sources
help.wialon.com (units/sensors, eco-driving, geofences, notifications, service
intervals, reports/export, locator, drivers, access rights); sdk.wialon.com
(`messages/load_interval`, `report/exec_report`, `resource/update_zone`,
`resource/update_notification`, `unit/update_service_interval`,
`unit/update_fuel_level_params`, `token/login`); wiki.teltonika-gps.com (FMB920 general
description, parameter list, accelerometer, analog fuel sensor, accessories). *Account-
specific items (billing plan, SMS enablement, token rights) marked "verify" need
in-account confirmation.*
