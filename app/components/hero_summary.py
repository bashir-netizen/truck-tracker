"""The hero line — the period's story compressed to one badged prose sentence."""

import streamlit as st


def render(prose_html):
    """prose_html: a one-line summary with inline <b> values and confidence badges."""
    st.markdown(f'<div class="tt-card tt-body" style="line-height:1.7">{prose_html}</div>',
                unsafe_allow_html=True)
