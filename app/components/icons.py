"""Inline-SVG icon set (Lucide names), zero dependencies.

Lucide isn't available to Streamlit natively, so we ship a small hand-picked set
as inline SVG and tint it via `currentColor`. `icon(name, size, color)` returns an
HTML <svg> string for use inside st.markdown(..., unsafe_allow_html=True) — e.g. in
metric cards (Part B) and the custom sidebar nav (Part D).
"""

# Inner SVG markup for a 24x24 stroke icon (no fill), one entry per Lucide name.
_ICONS = {
    "home": '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
    "map": '<path d="M9 4 4 6v14l5-2 6 2 5-2V4l-5 2-6-2z"/><path d="M9 4v14"/><path d="M15 6v14"/>',
    "droplet": '<path d="M12 3c3 3.5 5.5 6.5 5.5 9.5a5.5 5.5 0 0 1-11 0C6.5 9.5 9 6.5 12 3z"/>',
    "user": '<circle cx="12" cy="8" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/>',
    "activity": '<path d="M3 12h4l2.5 7 5-14L17 12h4"/>',
    "wrench": '<path d="M15 5a4 4 0 0 1 4.9 5.2L21 12 12 21l-1.8-1.1A4 4 0 0 1 5 14.9z"/>',
    "alert-circle": '<circle cx="12" cy="12" r="9"/><path d="M12 7v6"/><path d="M12 16.5h.01"/>',
    "file-text": ('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>'
                  '<path d="M14 3v5h5"/><path d="M9 13h6"/><path d="M9 17h5"/>'),
    "circle-check": '<circle cx="12" cy="12" r="9"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
    "function-square": ('<rect x="3" y="3" width="18" height="18" rx="3"/>'
                        '<path d="M14 8.5c-2 0-2.2 7-4 7"/><path d="M9 12.5h5"/>'),
    "circle-help": ('<circle cx="12" cy="12" r="9"/>'
                    '<path d="M9.5 9.3a2.6 2.6 0 0 1 5 .9c0 1.7-2.5 2.3-2.5 3.3"/>'
                    '<path d="M12 17h.01"/>'),
    "route": ('<circle cx="6.5" cy="17.5" r="2.5"/><circle cx="17.5" cy="6.5" r="2.5"/>'
              '<path d="M9 17.5h6a2.5 2.5 0 0 0 0-5H9a2.5 2.5 0 0 1 0-5h2"/>'),
    "gauge": '<path d="M5 18a8 8 0 1 1 14 0"/><path d="M12 14l3.5-3.5"/>',
    "fuel": ('<rect x="4" y="3" width="9" height="18" rx="1.5"/><path d="M7 8h3"/>'
             '<path d="M13 8h3a2 2 0 0 1 2 2v7a2 2 0 0 0 4 0V9l-3.5-3.5"/>'),
    "banknote": ('<rect x="2.5" y="6" width="19" height="12" rx="1.5"/>'
                 '<circle cx="12" cy="12" r="2.5"/><path d="M6 9.5v.01"/><path d="M18 14.5v.01"/>'),
    "calendar": ('<rect x="3.5" y="4.5" width="17" height="16" rx="2"/><path d="M3.5 9h17"/>'
                 '<path d="M8 3v3"/><path d="M16 3v3"/>'),
    "play": '<path d="M7 5l12 7-12 7z"/>',
    "pause": '<path d="M8 5v14"/><path d="M16 5v14"/>',
}


def icon(name, size=16, color="currentColor", stroke=2.0):
    """Return an inline <svg> string for a Lucide-named icon, or '' if unknown."""
    inner = _ICONS.get(name)
    if not inner:
        return ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            f'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="{stroke}" '
            f'stroke-linecap="round" stroke-linejoin="round" '
            f'style="vertical-align:middle;flex:none">{inner}</svg>')
