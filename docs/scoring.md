# Driver scoring & safety signals

## Why the Wialon score reads low on Kenyan routes

Wialon's eco-driving rank is a 0–10 score derived from **penalty points** (summed
per the unit's configured penalties) mapped through Wialon's documented
penalty→rank table. Those penalties and thresholds are calibrated for **European
fleet operations**.

On Kenyan roads, **mild and medium** harsh-acceleration, harsh-braking and
sharp-cornering events fire **constantly** — potholes, unmarked bumps, long
mountain descents, unpredictable traffic — largely **independent of how the driver
behaves**. With the unit's real penalty points (medium events = 500 pts each), a
normal week of long-haul driving accumulates thousands of penalty points, which
pushes the rank to the bottom of the table (this unit: **~1/10**) even with **no
extreme events at all**.

So the score is treated as a **reference** — useful to cross-check against Wialon's
own UI, but **not** a verdict on the driver. We deliberately do **not** normalize
it per distance, so it reproduces Wialon's own report number.

Computed using Wialon's documented penalty→rank formula with this unit's configured
penalty points. Cross-checkable against Wialon's Eco Driving tab. The remote report
API does not expose this value, so we reproduce it locally. (Verified against the live
API on 2026-05-23: the `unit_ecodriving` report returns only violation rows, and
requested `rank`/`rating`/`penalties` columns are silently dropped. This unit:
computed **1.0** vs Wialon's UI **~1.1** — a rounding/interpolation gap, not a
methodology difference.)

## What we lead with instead: hard-safety events

"Hard-safety" events are ones that are unsafe **regardless of road conditions**:

- **any extreme-severity event** (any type), and
- **(deferred)** speeding ≥20 km/h over the limit for ≥60 s, or ≥30 km/h over (any
  duration).

> The speeding clauses are **not yet evaluated**: the eco report available to our
> token exposes only *absolute* max speed (not km/h-over-limit) and leaves the
> per-event duration blank. Implementing them needs those fields from Wialon. For
> the current driver it is moot — there is no medium/extreme speeding.

Night highway driving is **not** hard-safety — it's normal scheduled long-haul on
Kenyan roads. It's surfaced separately as neutral information (see below).

## Events per 100 km

`events_per_100km = total eco events ÷ (distance_km ÷ 100)` for the period. This is
the road-condition-aware rate to watch over time. **Baseline** = this unit's rolling
30-day average once enough history exists; until then the card shows
"no baseline yet — building from this period". A unit's own baseline is the fair
comparison, because absolute rates differ by route.

## Night driving (informational)

Hours driven in the **19:00–05:00 local (Kenya, UTC+3)** window on long-haul or
regional journeys, summed from trip-leg time. It raises fatigue/accident risk and
is worth confirming with the operator (scheduled vs unplanned). It is **inferred**
from timestamps — engine-on at a fuel stop can look like night activity — so it is
shown without alarm styling.

## Caveat on thresholds

The 0.16 g "medium" accelerometer threshold (and the cornering/braking equivalents)
is **road-condition sensitive**: on rough surfaces it triggers from the road, not
the driver. That is the core reason the raw event counts and the Wialon score are
not, by themselves, a behaviour verdict in this environment.
