"""Geocoding stub — deferred. The seam for future OSM / Google Places lookups.

Today a new cluster gets its name from the nearest Wialon parking's geocoded
location string (``enrich/places.py::_short_name``) and its type from a
``places.yaml`` entry or, failing that, the dwell-pattern hint
(``enrich/places.py::_suggested_type``). When real geocoding lands, this module
turns a coordinate (plus the dwell-pattern hint) into a *suggested* name and
type, written to a git-ignored ``enrich/.suggested_places.yaml`` that the owner
reviews and promotes into ``places.yaml``.

Nothing here calls the network yet — this is only the placeholder so adding it
later does not restructure ``places.py``. The future classifier should combine:

  - reverse-geocoded address / nearby POIs (OSM Nominatim; optional Google Places)
  - on-highway vs off-highway (road class from the geocoder) — deferred
  - dwell-pattern hint (brief / medium / long / overnight) from ``place_visits``
  - visit frequency (one-off vs regular)

See docs/roadmap.md "Places — typing & geocoding (deferred)".
"""


def suggest_place(lat, lon, dwell_pattern=None, visit_count=None):
    """Return a {'name', 'type', 'confidence', 'source'} suggestion for a coordinate.

    Deferred. When implemented: reverse-geocode (lat, lon), combine the result
    with ``dwell_pattern`` / ``visit_count`` to pick a type, and emit a
    suggestion for review. Write suggestions to ``enrich/.suggested_places.yaml``
    only — never to ``places.yaml`` directly (the owner confirms).
    """
    raise NotImplementedError(
        "geocoding deferred — see module docstring (Task 6 B4)")
