"""Owner place metadata from places.yaml (depot/home flags) — display-side only.

The app reads places.yaml directly (owner config, not the DB) so the Overview can
tag depots without a schema change. Matching is by place label.
"""

import pathlib

import yaml

_ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "config.py").exists())


def depot_labels():
    """Set of place labels flagged `depot: true` or `home: true` in places.yaml."""
    path = _ROOT / "places.yaml"
    if not path.exists():
        return set()
    try:
        entries = yaml.safe_load(path.read_text()) or []
    except Exception:
        return set()
    return {e["label"] for e in entries
            if isinstance(e, dict) and e.get("label") and (e.get("depot") or e.get("home"))}
