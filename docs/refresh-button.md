# On-demand refresh ("Update now")

The sidebar **⟳ Update now** button triggers the existing `ingest.yml` GitHub Actions
workflow (Wialon pull → enrich → commit `data/truck.db`) without waiting for the
3-hourly schedule. Use it right before sharing the dashboard with Genwatt.

The app stays **read-only toward Wialon** (CLAUDE.md): it asks GitHub to run the
workflow; it never calls Wialon itself. The token lives only in Streamlit secrets
(server-side) and is never sent to the browser.

## Setup (one-time)

1. **Create a GitHub Personal Access Token.** A **fine-grained** token scoped to *only*
   the `truck-tracker` repo is recommended:
   - Repository access → Only select repositories → `truck-tracker`
   - Permissions → **Actions: Read and write** (and Contents: Read).
   (A classic PAT with `repo` + `workflow` scopes also works but grants more.)

2. **Add Streamlit Cloud secrets** (App → Settings → Secrets):
   ```toml
   GITHUB_TOKEN = "github_pat_…"
   GITHUB_OWNER = "bashir-netizen"
   GITHUB_REPO = "truck-tracker"
   GITHUB_WORKFLOW = "ingest.yml"   # optional; this is the default
   ```

3. That's it — `ingest.yml` already has `workflow_dispatch`, so no workflow change is
   needed. Until the secrets are set, the button shows disabled with a note.

## Behaviour
- **Cooldown:** 5 minutes between triggers (the dashboard is unauthenticated, so anyone
  with the URL can press it; the cooldown limits abuse).
- **Runtime:** a refresh typically takes **1–3 minutes**. The button polls every ~10 s and
  shows progress, then "✓ Updated — Refresh to see new data."
- **"Last updated"** comes from the latest workflow run's time (GitHub API), not the
  committed file's mtime.

## Failure messages
- *Configure GITHUB_TOKEN…* — secrets not set.
- *Token invalid or lacks permissions* (401) — regenerate / fix scopes.
- *GitHub rate limit reached* (403). · *Workflow not found* (404) — check `GITHUB_WORKFLOW`.
- *Couldn't reach GitHub* — network error.
