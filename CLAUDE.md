# Truck Tracker — working agreement

Personal fleet-audit system for a single truck (KDX 415X, FAW 6x4, Teltonika
FMB920) operated by subcontractor Genwatt in Kenya. It gives the **owner**
independent ground-truth to verify Genwatt's statements line by line, protect
the asset from driver abuse and under-servicing, and catch fuel anomalies.

## Architecture — three layers, one-directional flow

```
Wialon API  ->  SQLite (data/truck.db)  ->  Streamlit (read-only)
   ingest/          (raw + derived)            app/
                         ^
                      enrich/  (writes derived tables only)
```

- **ingest/** hits the Wialon API and writes RAW tables. Idempotent
  (`INSERT OR IGNORE` on natural keys). One job per run: login, fetch, write,
  exit.
- **enrich/** reads raw, writes DERIVED tables. Never modifies raw rows.
- **app/** reads SQLite **read-only** and renders. Never calls Wialon — even
  for a "live" feel. Freshness contract is "as of last ingestion run".

**Layer isolation is absolute.** ingest does not import from enrich or app;
enrich does not import from app; app imports from neither — it reads the DB.
If a change crosses a boundary, push back and propose a layer-respecting
alternative.

## Conventions

- Timestamps: INTEGER Unix epoch seconds, UTC. Convert to local only at display.
- Coordinates: REAL `lat`, `lon`. Never strings, never a combined column.
- Distances: metres (INTEGER) at ingestion; km only for display.
- Fuel: litres (REAL). Engine hours: integer seconds; display as days/hours.
- Thresholds and tunables live in `config.py`. Maintenance intervals too.
- Owner-maintained label files: `places.yaml` (place names), `services.yaml`
  (last-service baselines).
- All Wialon calls go through the single `WialonClient` in `ingest/wialon.py`;
  retry/error/rate-limit handling is centralized there.
- The dashboard opens the DB read-only:
  `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`.

## Wialon API quick reference

- Host `https://hst-api.wialon.eu`, all calls POST to `/wialon/ajax.html`
  with form fields `svc`, `params` (JSON string), `sid`.
- `token/login` -> session id in `eid` (used as `sid`). Re-login per run.
- Every response has an integer `error` field — check it every time.
  1=invalid session (re-login), 4=bad input, 5=server, 7=scope too narrow,
  8=bad token, 1003=one request at a time.
- Unit lookup: `core/search_items` itemsType `avl_unit`, flags `13313`.
  Mileage in `cnm` (km), engine hours in `cneh` (h), position in `pos`/`lmsg`.
- Trips/fuel/eco come from `report/exec_report` against tuned stock templates,
  then `get_result_rows`, then `cleanup_result`. Only ONE report per session;
  resolve tables by `name`/`label`, never a fixed index.

## Do NOT

- Add an ORM, or any web framework beyond Streamlit (no Flask/FastAPI/Django).
- Add Docker/k8s/microservices, or dashboard authentication.
- Store the Wialon token anywhere but `.env` (local) / Actions secrets (CI).
- Destructively clean or auto-merge raw ingested rows.
- Call the Wialon API from the Streamlit app.
- Introduce a second vehicle's data/UI before there is an actual second truck
  (the schema already carries `unit_id`).
- Add a dependency without justifying it against the stack. Prefer the
  smallest change; resist unrequested refactoring.
- Test against the live API. Use recorded JSON fixtures in `tests/`.

## Build stages (gated — each ends in a working commit)

1. Scaffolding + connection proof  ← (current)
2. Pull real data (30 days), idempotent, `--since` backfill
3. Enrichment (places, metrics, driver score, maintenance)
4. Dashboard (all pages, polished, mobile-usable)
5. Automation (GitHub Actions every 3h; weekly email; audit PDF)
6. Billing (only when Genwatt rates are known) — isolated in `billing/`

## Frontend conventions (Stage 4)

Density over decoration; numbers first with units and baseline context; plain
labels; one accent colour; designed empty states; light theme only; system
sans (no Google Fonts); plotly via a shared theme module; pydeck `light-v10`;
reusable components in `app/components/`; usable at 380px width.
