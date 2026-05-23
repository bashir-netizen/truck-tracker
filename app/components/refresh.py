"""On-demand data refresh — trigger the ingest GitHub Actions workflow.

Keeps the app read-only w.r.t. Wialon (CLAUDE.md): the button asks GitHub to run the
same scheduled `ingest.yml` (Wialon pull → enrich → commit `data/truck.db`). The PAT
lives only in `st.secrets` (server-side, never sent to the browser). Disabled with a
note until the GITHUB_* secrets are set. A 5-min cooldown limits abuse (the dashboard
is unauthenticated, so anyone with the URL can press it).
"""

import time
from datetime import datetime, timezone

import requests
import streamlit as st

_API = "https://api.github.com"
_COOLDOWN_S = 300
_POLL_TIMEOUT_S = 360


def _cfg():
    try:
        s = st.secrets
        return (s.get("GITHUB_TOKEN"), s.get("GITHUB_OWNER"), s.get("GITHUB_REPO"),
                s.get("GITHUB_WORKFLOW", "ingest.yml"))
    except Exception:
        return None, None, None, "ingest.yml"


def _hdr(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def _msg(code):
    return {401: "Token invalid or lacks permissions", 403: "GitHub rate limit reached",
            404: "Workflow not found — check GITHUB_WORKFLOW"}.get(code, f"GitHub error {code}")


def _fetch_latest(owner, repo, token):
    r = requests.get(f"{_API}/repos/{owner}/{repo}/actions/runs", params={"per_page": 1},
                     headers=_hdr(token), timeout=15)
    r.raise_for_status()
    runs = r.json().get("workflow_runs", [])
    return runs[0] if runs else None


@st.cache_data(ttl=30, show_spinner=False)
def _latest_cached(owner, repo, token):
    return _fetch_latest(owner, repo, token)


def _iso_epoch(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return 0


def _ago(epoch):
    if not epoch:
        return "unknown"
    m = max(0, int((time.time() - epoch) / 60))
    if m < 60:
        return f"{m} min ago"
    h = m // 60
    return f"{h}h ago" if h < 24 else f"{h // 24}d ago"


def update_button():
    """Render the sidebar refresh control. Safe (disabled + note) when unconfigured."""
    token, owner, repo, wf = _cfg()
    if not (token and owner and repo):
        st.sidebar.button("⟳ Update now", disabled=True, width="stretch", key="refresh_off")
        st.sidebar.caption("Set GITHUB_TOKEN / GITHUB_OWNER / GITHUB_REPO in Streamlit "
                           "secrets to enable on-demand refresh.")
        return
    if st.session_state.get("refresh_running"):
        _poll(owner, repo, token)
    else:
        _idle(owner, repo, wf, token)


def _idle(owner, repo, wf, token):
    ss = st.session_state
    if ss.get("refresh_done"):
        st.sidebar.success("✓ Updated. Refresh to see new data.")
        if st.sidebar.button("Refresh page", width="stretch", key="refresh_reload"):
            ss.pop("refresh_done", None)
            st.cache_data.clear()
            st.rerun()
        return
    if ss.get("refresh_error"):
        st.sidebar.error(f"✗ {ss['refresh_error']}")
        if st.sidebar.button("Try again", width="stretch", key="refresh_retry"):
            ss.pop("refresh_error", None)
            st.rerun()
        return
    elapsed = time.time() - ss.get("refresh_trig_at", 0)
    cooling = bool(ss.get("refresh_trig_at")) and elapsed < _COOLDOWN_S
    if st.sidebar.button("⟳ Update now", width="stretch", disabled=cooling, key="refresh_go"):
        try:
            r = requests.post(
                f"{_API}/repos/{owner}/{repo}/actions/workflows/{wf}/dispatches",
                json={"ref": "main"}, headers=_hdr(token), timeout=15)
            if r.status_code not in (201, 204):
                ss["refresh_error"] = _msg(r.status_code)
            else:
                ss["refresh_trig_at"] = time.time()
                ss["refresh_running"] = True
        except requests.RequestException:
            ss["refresh_error"] = "Couldn't reach GitHub"
        st.rerun()
    if cooling:
        st.sidebar.caption(f"Wait {int((_COOLDOWN_S - elapsed) / 60) + 1} min before "
                           "triggering again.")
    else:
        try:
            run = _latest_cached(owner, repo, token)
            st.sidebar.caption(f"Last updated {_ago(_iso_epoch((run or {}).get('updated_at', '')))}")
        except Exception:
            pass


@st.fragment(run_every=10)
def _poll(owner, repo, token):
    ss = st.session_state
    trig = ss.get("refresh_trig_at", 0)
    elapsed = int(time.time() - trig)
    st.sidebar.info(f"Fetching fresh data from Wialon… ({elapsed}s)")
    try:
        run = _fetch_latest(owner, repo, token)
    except Exception:
        run = None
    if run and _iso_epoch(run.get("created_at", "")) >= trig - 30 \
            and run.get("status") == "completed":
        ss["refresh_running"] = False
        if run.get("conclusion") == "success":
            ss["refresh_done"] = True
        else:
            ss["refresh_error"] = f"Workflow {run.get('conclusion') or 'failed'}"
        st.cache_data.clear()
        st.rerun()
    elif elapsed > _POLL_TIMEOUT_S:
        ss["refresh_running"] = False
        ss["refresh_error"] = "Still running — check GitHub Actions"
        st.rerun()
