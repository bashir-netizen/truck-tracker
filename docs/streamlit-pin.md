# Streamlit version pin

`requirements.txt` pins **`streamlit==1.57.0`**. This is a *defensive* pin, not a
permanent decision.

## Why we pinned
Two components render raw HTML via `st.components.v1.html`:
- `app/components/refresh.py` — the "Update now" button.
- `app/components/track_player.py` — the Map's deck.gl playback.

Streamlit 1.57 warns that `components.html` will be **removed ~2026-06-01**. Pinning to
1.57.0 (the version everything was built and tested against) keeps the deployed app on a
known-good Streamlit so an automatic Cloud upgrade can't remove `components.html` out from
under those two components.

## What needs to change to unpin
Migrate both components off `components.html` to whatever the current Streamlit offers for
embedding self-contained HTML/JS (e.g. a successor API or a small custom component), then
re-test the refresh-button flow and the Map playback, and drop the pin (or bump it).

## When to revisit
- Streamlit announces a hard end-of-life date for 1.57.x, **or**
- we need a feature/fix that only exists in a newer Streamlit.

Until then, bumping is optional. If you do bump, run `pytest` + the AppTest smoke suite and
click through the refresh button and Map playback before deploying.
