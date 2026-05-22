"""Designed empty states — never a blank panel or a bare zero."""

import streamlit as st


def empty_state(title, body=""):
    st.markdown(
        f'<div class="tt-empty"><div class="t">{title}</div>{body}</div>',
        unsafe_allow_html=True,
    )
