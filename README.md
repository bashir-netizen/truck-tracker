# Truck Tracker

Independent fleet-audit and asset-management for a single truck — **KDX 415X**
(FAW 6x4, Teltonika FMB920 tracker), operated by subcontractor **Genwatt** in
Kenya.

The truck's owner does not operate it day to day; Genwatt does, and sends
statements. This tool pulls the truck's data straight from **Wialon Hosting**,
stores it locally in **SQLite**, and shows it in a read-only **Streamlit**
dashboard — so statements can be verified line by line, the asset is protected
from driver abuse and skipped servicing, and fuel anomalies surface early.

Data flows one direction only: **Wialon → SQLite → Streamlit**. The dashboard
never calls Wialon.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then paste your WIALON_TOKEN
python -m ingest.run               # one-shot ingestion / connection proof
streamlit run app/main.py          # launch dashboard (Stage 4+)
```

## Getting a Wialon API token

The token is a long-lived credential, created once from the Wialon UI:

1. Log in to Wialon Hosting (`https://hosting.wialon.com`).
2. Open the user menu (top-right) and find the token/access management
   ("Create access token" / via the OAuth flow for `hst-api.wialon.eu`).
3. Grant a read-capable scope that covers viewing the unit and executing its
   reports. (Too narrow a scope shows up as Wialon error 7.)
4. Copy the token string into `.env` as `WIALON_TOKEN=...`.

The token lives only in `.env` (gitignored) locally and in GitHub Actions repo
secrets in CI. It is never committed.

## Layout

```
config.py           thresholds, intervals, tunables (no secrets)
ingest/             Wialon -> SQLite (raw tables)
  wialon.py         the single API client
  schema.sql        all table definitions (idempotent)
  run.py            entry point
enrich/             SQLite raw -> SQLite derived (Stage 3)
app/                Streamlit dashboard, read-only (Stage 4)
billing/            per-trip costing — empty until rates are known (Stage 6)
data/truck.db       the database (committed while small)
tests/              fixtures + tests (no live API)
.github/workflows/  scheduled ingestion (Stage 5)
```

See `CLAUDE.md` for the architecture rules and conventions.

## Status

Stage 1 (scaffolding + connection proof) — in progress.
