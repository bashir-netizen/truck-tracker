"""One row in the top-destinations list: place · class tag · visits · last visited."""

import streamlit as st

from app.components.format import relative_day


def render(name, tag, visits, last_ts):
    st.markdown(
        f'<div class="tt-row"><div><b>{name}</b> '
        f'<span class="tt-pill neutral">{tag}</span></div>'
        f'<div class="tt-small">{int(visits)} visit{"s" if visits != 1 else ""} · '
        f'{relative_day(last_ts)}</div></div>',
        unsafe_allow_html=True)
