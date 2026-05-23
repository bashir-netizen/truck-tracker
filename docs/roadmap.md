# Re-prioritized roadmap (post-Wialon-audit)

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
