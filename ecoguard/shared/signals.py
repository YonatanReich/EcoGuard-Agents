"""What "an anomalous reading of X in cell Y" means, for every X.

A coordinator that merges candidates from independent detectors has to compare
claims made in different units on different scales. Brightness is kelvin, rain
is millimetres, PM2.5 is micrograms per cubic metre, and a satellite hotspot is
not a measurement at all — it is a yes. None of those can be compared directly,
and picking one as the reference unit only moves the problem.

The unification is to stop comparing **magnitudes** and start comparing
**rarity**. Not "how hot" but "how unusual is this for this cell, at this time
of year, compared with everything this cell has done before". That question has
the same answer type for every variable: a number between 0 and 1. A 1-in-500
brightness reading and a 1-in-500 PM2.5 reading are the same strength of claim,
and a coordinator can weigh them against each other without knowing what either
measures.

Two things are kept deliberately apart, because collapsing them is the classic
error in this domain:

  **rarity** — how far this departs from normal. Statistical, needs a baseline,
  and says nothing about danger. 25 C in a Negev January is extremely rare and
  entirely harmless.

  **severity** — how dangerous the reading is. Domain judgement, needs no
  baseline. 40 C in a Negev August is utterly unremarkable statistically and is
  exactly the condition that burns the country down.

A system with only rarity misses every seasonal-normal disaster. A system with
only severity cannot detect anything novel and cannot compare across hazards.
Detectors are responsible for rarity; severity is the analysers' job and is
left None here until one fills it in.

`confidence` is a third, separate axis: how much the *reading itself* can be
trusted, before asking what it means. A low-confidence VIIRS pixel and a
baseline built from eleven samples are both weak evidence of a strong claim.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Sequence

from ecoguard.shared.cells import are_adjacent
from ecoguard.shared.grid import (
    LATITUDE_KM_PER_DEGREE,
    LONGITUDE_KM_PER_DEGREE_AT_EQUATOR,
)

# --- hazards ---------------------------------------------------------------

FIRE = "fire"

# Conditions under which a fire starts and runs, as distinct from a fire.
#
# The two are different claims and the difference is not pedantry: it decides
# who gets woken. "Something is burning at this point" sends an engine;
# "this region is hot, dry and windy" is a warning nobody drives to. They were
# one hazard until a live run put five undispatchable weather incidents above a
# real 90 MW fire in the emergency queue, which is what conflating them looks
# like in practice.
#
# Deliberately not "fire_risk". Risk is the analysers' word, and this module
# spends thirty lines above keeping rarity and severity apart; a detector that
# advertised "risk" in its output would be the first step in collapsing them
# again. This names what was measured and stops there.
FIRE_WEATHER = "fire_weather"

FLOOD = "flood"
AIR_QUALITY = "air_quality"
HEAT = "heat"

# --- which tail is the concerning one --------------------------------------

HIGH = "high"      # large values are the worrying ones
LOW = "low"        # small values are (humidity, soil moisture, greenness)
EITHER = "either"  # both tails matter

# Keyed by (hazard, variable), not by variable alone, because the same
# measurement points opposite ways for different hazards. Heavy rain is the
# flood signal and the *absence* of a fire signal; a detector that shared one
# direction table across hazards would report every storm as a fire risk.
#
# There is deliberately no default. A variable missing from this table forces
# the caller to state its direction explicitly, because the alternative —
# assuming HIGH — silently inverts every variable where low is bad, and
# "unusually green vegetation" would be reported as a fire anomaly.
CONCERNING_DIRECTION: dict[tuple[str, str], str] = {
    # FIRE is measurement of combustion itself. Only a satellite produces these.
    (FIRE, "brightness"): HIGH,
    (FIRE, "frp"): HIGH,

    # FIRE_WEATHER is everything that makes combustion likely and fast. None of
    # it can tell you a fire exists — a weather model has no knowledge one does.
    (FIRE_WEATHER, "temperature_2m"): HIGH,
    (FIRE_WEATHER, "relative_humidity_2m"): LOW,
    (FIRE_WEATHER, "wind_speed_10m"): HIGH,
    (FIRE_WEATHER, "wind_gusts_10m"): HIGH,
    (FIRE_WEATHER, "vapour_pressure_deficit"): HIGH,
    (FIRE_WEATHER, "soil_moisture_0_to_7cm"): LOW,
    (FIRE_WEATHER, "precipitation"): LOW,
    # Fuel rather than weather, and filed here because it is the same kind of
    # claim: a precondition, not an event. It moves if a fuel detector ever
    # wants its own hazard.
    (FIRE_WEATHER, "ndvi"): LOW,
    (FIRE_WEATHER, "fwi"): HIGH,
    (FLOOD, "precipitation"): HIGH,
    (FLOOD, "soil_moisture_0_to_7cm"): HIGH,
    (FLOOD, "water_level"): HIGH,
    (AIR_QUALITY, "pm25"): HIGH,
    (AIR_QUALITY, "pm10"): HIGH,
    (AIR_QUALITY, "ozone"): HIGH,
    (AIR_QUALITY, "no2"): HIGH,
    (HEAT, "temperature_2m"): HIGH,
}

# How rare a reading must be before it is worth reporting at all.
#
# This number is a false-alarm budget, not a taste preference, and the
# arithmetic is worth doing before choosing it. The national grid is 1,174
# cells; checked hourly that is 28,176 cell-hours a day, per variable. Pure
# chance then produces:
#
#     0.95   -> 1,409 a day     unusable
#     0.99   ->   282 a day     unusable
#     0.999  ->    28 a day     tractable
#     0.9999 ->     3 a day     quiet
#
# 0.999 is the default because the coordinator is what makes it workable:
# corroboration multiplies. Two *independent* sources each at 0.999 in the same
# cell is a one-in-a-million coincidence, so the useful threshold for raising an
# incident is far stricter than the threshold for emitting a signal — and that
# is precisely the division of labour between a detector and this stage.
REPORTING_RARITY = 0.999

# How far apart in time two signals may be and still describe one event.
# Chosen for the slowest source that matters: FIRMS near-real-time runs about
# three hours behind the overpass, so a ground report and the satellite
# confirmation of the same fire are routinely hours apart.
CORROBORATION_WINDOW = timedelta(hours=3)


def direction_for(hazard: str, variable: str) -> str | None:
    """Which tail is concerning, or None when nobody has decided yet."""
    return CONCERNING_DIRECTION.get((hazard, variable))


# --- the baseline a reading is judged against ------------------------------

@dataclass(frozen=True)
class Baseline:
    """What this cell normally does for this variable at this time of year.

    The seven quantiles are what `weather_baselines` stores. They are enough to
    place any reading on the distribution by interpolation, and small enough to
    keep in one row per cell per variable per month per hour.
    """

    minimum: float
    p05: float
    p25: float
    median: float
    p75: float
    p95: float
    maximum: float
    samples: int
    # Free text naming where the distribution came from, so a signal can
    # explain itself: "10y MODIS-era climatology", "365d detection rate".
    origin: str = "unspecified"

    @property
    def knots(self) -> tuple[tuple[float, float], ...]:
        """(value, cumulative probability) pairs, ascending."""
        return (
            (self.minimum, 0.0), (self.p05, 0.05), (self.p25, 0.25),
            (self.median, 0.5), (self.p75, 0.75), (self.p95, 0.95),
            (self.maximum, 1.0),
        )


def percentile_of(value: float, baseline: Baseline) -> float:
    """Where a reading sits in its baseline, 0..1, by linear interpolation.

    Below everything on record is 0.0 and above everything is 1.0 — saturating
    rather than extrapolating, because a decade of samples says nothing about
    how much worse than its own record a cell can get.

    Flat stretches are the normal case, not an edge case: it does not rain in
    most hours, so a precipitation baseline has p05 through p95 all at zero. A
    dry reading then lands at or below the first knot and returns 0.0, which is
    correct — a dry hour in a dry bucket is the most ordinary thing there is.
    """
    knots = baseline.knots
    if value <= knots[0][0]:
        return 0.0
    if value >= knots[-1][0]:
        return 1.0

    for (low_value, low_p), (high_value, high_p) in zip(knots, knots[1:]):
        if low_value <= value <= high_value:
            if high_value == low_value:
                # A flat segment: every reading here is the same value, so the
                # top of the segment is the honest answer — it beats everything
                # below and ties everything within.
                return high_p
            span = (value - low_value) / (high_value - low_value)
            return low_p + span * (high_p - low_p)
    return 1.0


def rarity_from_baseline(value: float, baseline: Baseline, direction: str) -> float:
    """How unusual a reading is on its concerning side, 0..1.

    0 is utterly typical and 1 is beyond anything on record. The direction is
    what makes this comparable across variables that disagree about which way
    is bad: for humidity the rare-and-worrying end is the bottom, for
    temperature the top, and both come back as a number near 1.
    """
    place = percentile_of(value, baseline)
    if direction == HIGH:
        return place
    if direction == LOW:
        return 1.0 - place
    if direction == EITHER:
        # Distance from the middle, rescaled so either extreme reaches 1.
        return min(1.0, abs(place - 0.5) * 2)
    raise ValueError(f"unknown direction {direction!r}")


def rarity_from_rate(historical_share: float) -> float:
    """Rarity for things that either happen or do not, from how often they do.

    Some sources have no magnitude to place on a distribution. A FIRMS hotspot
    is a yes, and the only sensible baseline is how often this cell says yes: a
    quarry that trips the sensor on two days in five is unremarkable when it
    trips again, while the same detection in a cell that has never lit in a
    year is a genuine one-off.

    This is the persistent-hotspot filter expressed as rarity, which is what
    lets a categorical source share a scale with a continuous one.
    """
    return max(0.0, min(1.0, 1.0 - historical_share))


# --- the universal record --------------------------------------------------

@dataclass(frozen=True)
class CellSignal:
    """One detector's claim that something is off in one cell at one time.

    This is the only shape the coordinator consumes. A detector for any hazard
    produces these and nothing else, which is what lets one deduplicator serve
    fire, flood and air quality without knowing anything about any of them.
    """

    cell_id: str
    observed_at: datetime
    hazard: str
    variable: str
    value: float
    unit: str
    source: str

    # How unusual, 0..1. None when no baseline exists for this cell yet — an
    # honest "not assessed", which must never be read as "assessed and fine".
    rarity: float | None
    direction: str
    baseline: Baseline | None = None

    # Where the thing actually is, with the precision of that fix. None when
    # the detector has no point and the cell is all it knows — which is a real
    # state for a Telegram report naming no street, and must stay
    # distinguishable from a confident fix at the cell centre.
    location: "CellLocation | None" = None

    # How much the reading itself can be trusted, before asking what it means.
    confidence: float = 1.0

    # How dangerous. Left None by detectors on purpose; the analysers fill it.
    # See the module docstring for why this is not merged into rarity.
    severity: float | None = None

    # Whatever the detector wants to carry forward: the raw payload, the pixel
    # list, the message text. Opaque to the coordinator.
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def reportable(self) -> bool:
        """Whether this clears the bar for emitting a signal at all."""
        return self.rarity is not None and self.rarity >= REPORTING_RARITY

    @property
    def beyond_record(self) -> bool:
        """Outside everything the baseline has ever seen.

        Worth separating from a high rarity: it means the baseline itself has
        no experience of this, so the rarity figure is a floor rather than an
        estimate.
        """
        if self.baseline is None:
            return False
        return self.value > self.baseline.maximum or self.value < self.baseline.minimum


def corroborates(
    first: CellSignal,
    second: CellSignal,
    *,
    window: timedelta = CORROBORATION_WINDOW,
    radius: int = 1,
) -> bool:
    """Whether two signals plausibly describe the same event.

    Three tests, and the loose one is deliberate:

      * **Same hazard.** A rainfall anomaly does not corroborate a fire.
      * **Same or adjacent cell.** Events do not respect cell edges — a fire on
        a boundary lights pixels either side, and a satellite fix and a ground
        report of one fire routinely land a cell apart. Requiring an exact
        match is the most common way a deduplicator splits one event in two.
      * **Overlapping in time**, within a window sized for the slowest source.

    Deliberately *not* tested: whether either signal is reportable. Two weak
    signals agreeing is itself evidence, and throwing them away individually
    before checking whether they agree discards exactly the corroboration this
    stage exists to find.

    Same source and same variable still corroborate, because two satellites
    seeing one cell is genuine agreement. Whether to *weight* that lower than
    two independent sources is the coordinator's call, not this predicate's.
    """
    if first.hazard != second.hazard:
        return False
    if abs(first.observed_at - second.observed_at) > window:
        return False
    return are_adjacent(first.cell_id, second.cell_id, radius=radius)


# --- where the thing actually is -------------------------------------------

# Nominal precision by how a location was obtained, in metres. These are the
# radius within which the true thing plausibly sits — not the size of the thing
# itself, and not the size of the cell.
#
# The spread matters more than any single number here: a VIIRS pixel and a
# town-name geocode differ by a factor of twenty, and a UI that draws both as
# the same dot tells an operator the second one is as trustworthy as the first.
VIIRS_PIXEL_M = 375.0
MODIS_PIXEL_M = 1000.0
# Meteosat, via the geostationary feed. The detections come back on a grid
# whose nearest-neighbour spacing measures about 1.4 km over Israel, but the
# instrument's true footprint is coarser than its reporting grid and widens off
# nadir - and Israel is a long way off nadir from 0 degrees longitude. Three
# kilometres is the conservative reading, and conservative is the right
# direction: this number becomes the radius a crew is told the fire sits
# within, so overstating precision sends people to the wrong field.
GEOSTATIONARY_PIXEL_M = 3000.0
STREET_ADDRESS_M = 100.0
LOCALITY_M = 2000.0
# No point at all — the cell is the location. 5 km cell, so half-diagonal.
CELL_ONLY_M = 3500.0


@dataclass(frozen=True)
class CellLocation:
    """Where a detector thinks the thing is, and how sure it is of that.

    Separate from `cell_id` on purpose. The cell is a bucket for comparison —
    it answers "is this the same event as that one" and "which baseline applies
    here". This answers "where do we send the truck", and the two are routinely
    kilometres apart: a 5 km cell's centroid sits up to 3.5 km from a fire
    inside it.

    `precision_m` is the radius the true location plausibly sits within. It is
    what stops a UI from drawing a town-name geocode and a satellite pixel as
    the same confident dot, and it is what lets the coordinator pick the better
    of two locations when signals merge.
    """

    latitude: float
    longitude: float
    precision_m: float
    # How it was derived, for display and for debugging a bad fix:
    # "viirs_pixel", "frp_weighted_centroid", "locality_geocode", "cell_centre".
    method: str

    @property
    def is_point(self) -> bool:
        """Whether this is precise enough to draw as a point rather than an area.

        The threshold is the cell itself: anything as vague as a cell should be
        drawn as the cell, because a dot would claim precision that is not
        there.
        """
        return self.precision_m < CELL_ONLY_M


def cell_centre_location(cell_id: str) -> CellLocation | None:
    """The fallback when a detector has no point at all.

    Honest rather than convenient: the precision says "somewhere in this cell",
    so a map draws the square and nobody reads the centroid as the fire.
    """
    from ecoguard.shared.cells import cell_by_id

    cell = cell_by_id(cell_id)
    if cell is None:
        return None
    return CellLocation(cell.latitude, cell.longitude, CELL_ONLY_M, "cell_centre")


def locate_points(
    points: Sequence[tuple[float, float, float]],
    *,
    pixel_precision_m: float = VIIRS_PIXEL_M,
    method: str = "weighted_centroid",
) -> CellLocation | None:
    """One location from several weighted observations of the same thing.

    Args:
        points: (latitude, longitude, weight) triples. For fire the weight is
            radiative power, so the fix is pulled toward the hottest part of
            the burn rather than the geometric middle of the pixels — which is
            the bit of the fire that matters and the bit a crew heads for.
        pixel_precision_m: how precise each contributing point is on its own.
        method: recorded on the result for display and debugging.

    Returns:
        CellLocation, or None when there are no usable points.

    The returned precision covers the *spread*, not just the instrument: four
    pixels strung over two kilometres is a two-kilometre-long fire, and
    reporting its centroid to 375 m would be a confident fix on a spot that may
    not be burning at all.
    """
    usable = [(lat, lon, max(0.0, weight)) for lat, lon, weight in points]
    if not usable:
        return None

    total = sum(weight for _, _, weight in usable)
    if total <= 0:
        # No weights to go on — every point counts the same.
        usable = [(lat, lon, 1.0) for lat, lon, _ in usable]
        total = float(len(usable))

    latitude = sum(lat * weight for lat, _, weight in usable) / total
    longitude = sum(lon * weight for _, lon, weight in usable) / total

    scale = math.cos(math.radians(latitude))
    spread = max(
        math.hypot(
            (lat - latitude) * LATITUDE_KM_PER_DEGREE * 1000,
            (lon - longitude) * LONGITUDE_KM_PER_DEGREE_AT_EQUATOR * 1000 * scale,
        )
        for lat, lon, _ in usable
    )
    return CellLocation(latitude, longitude, max(pixel_precision_m, spread), method)


def best_location(*candidates: CellLocation | None) -> CellLocation | None:
    """The most precise location among several, ignoring the missing ones.

    The rule for merging: an incident inherits the *best* fix available, never
    the first one seen and never an average. A satellite pixel and a
    town-name geocode of one fire average to a place neither source suggested,
    and averaging a 375 m fix with a 2 km one throws away the 375 m fix.
    """
    present = [candidate for candidate in candidates if candidate is not None]
    if not present:
        return None
    return min(present, key=lambda location: location.precision_m)
