"""Estimate helpers — the start of the billing module.

Pure functions, no DB or API. Monetary logic lives here (not in the display
layer) per CLAUDE.md. Per-km rates are supplied by the caller and may be None;
this module never invents a rate.
"""

CLASSES = ("long_haul", "regional", "local")  # yard is not billable movement


def fuel_cost(filled_l, diesel_kes_per_l):
    """Cash spent on diesel: measured litres filled × pump price."""
    return (filled_l or 0) * (diesel_kes_per_l or 0)


def revenue_by_class(journeys, rates):
    """Revenue from journeys at the given per-class km rates.

    journeys: iterable of (character, distance_m).
    rates: {class: kes_per_km or None}.
    Returns (total, breakdown{class: {km, rate, kes}}, included[list], excluded[list]).
    Classes whose rate is None are excluded entirely (never assumed zero-value).
    """
    km = {c: 0.0 for c in CLASSES}
    for character, distance_m in journeys:
        if character in km:
            km[character] += (distance_m or 0) / 1000.0

    total, breakdown, included, excluded = 0.0, {}, [], []
    for c in CLASSES:
        rate = rates.get(c)
        if rate is None:
            if km[c] > 0:
                excluded.append(c)
            continue
        kes = km[c] * rate
        breakdown[c] = {"km": km[c], "rate": rate, "kes": kes}
        total += kes
        included.append(c)
    return total, breakdown, included, excluded
