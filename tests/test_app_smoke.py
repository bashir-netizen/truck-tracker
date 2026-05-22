"""Smoke test: every dashboard page runs without raising.

Uses Streamlit's AppTest to execute each script server-side against the
real database. It does not assert on visuals — only that nothing throws.
"""

import pathlib

import pytest
from streamlit.testing.v1 import AppTest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = [ROOT / "app" / "main.py"] + sorted((ROOT / "app" / "pages").glob("*.py"))


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_page_runs(script):
    at = AppTest.from_file(str(script), default_timeout=60)
    at.run()
    assert not at.exception, f"{script.name} raised: {at.exception}"
