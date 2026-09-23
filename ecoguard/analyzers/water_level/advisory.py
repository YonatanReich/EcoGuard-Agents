"""Turn stored Kinneret levels into an operator advisory.

Pure and deterministic. The Water Authority publishes the operating lines, so
"is action needed" is a lookup against them plus the direction the lake is
moving. There is nothing here a model would know that the three constants
below do not already say, and a model would introduce a failure mode — a
plausible sentence recommending the wrong direction — that arithmetic cannot
have.

The one judgement this module does make is the trend, and it is deliberately
the least clever thing that answers the question. See the ponytail note on
`_trend_m_per_day`.
"""

from __future__ import annotations

from ecoguard.shared.activity import live_actor

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import linear_regression

# The Water Authority's published operating lines for the Kinneret, in metres
# relative to mean sea level. These are the Authority's numbers, not
# EcoGuard's, and every band below is meaningless without them:
#
#   upper red   above it the Degania dam is opened, or the lake overflows
#   lower red   below it extraction for supply is meant to stop
#   black       below it the damage to the lake is not recoverable
#
# ponytail: three module constants, not a table. They change roughly never.
# Move them to operator-editable rows (the `text_sources` pattern) if the
# Authority starts revising them or a second lake arrives.
UPPER_RED_LINE_M = -208.8
LOWER_RED_LINE_M = -213.0
BLACK_LINE_M = -214.87

TREND_WINDOW_DAYS = 30
MINIMUM_TREND_SAMPLES = 2

BAND_ABOVE_UPPER_RED = "above_upper_red"
BAND_NORMAL = "normal"
BAND_BELOW_LOWER_RED = "below_lower_red"
BAND_BELOW_BLACK = "below_black"

ACTIONS = {
    BAND_ABOVE_UPPER_RED: (
        "Open the Degania dam to release water and prevent overflow. Do not "
        "pump water in."
    ),
    BAND_NORMAL: "No action required. Continue routine monitoring.",
    BAND_BELOW_LOWER_RED: (
        "Halt extraction for supply, and pump desalinated water in through "
        "the Eshkol-Tzalmon line."
    ),
    BAND_BELOW_BLACK: (
        "Sustained inflow required urgently. Below the black line the "
        "ecological damage to the lake is not recoverable."
    ),
}


@dataclass(frozen=True)
class LevelReading:
    """One survey: when it was taken and what the lake stood at."""

    observed_at: datetime
    level_m: float


@dataclass(frozen=True)
class KinneretAdvisory:
    """What the lake is doing and what, if anything, to do about it."""

    level_m: float
    observed_at: datetime
    band: str
    action: str
    rationale: str
    # None means the trend was not assessed, never that the lake is flat. A
    # caller that renders a missing trend as 0 m/year reports a stable lake
    # during an outage, which is the one wrong answer that looks reassuring.
    trend_m_per_day: float | None
    trend_m_per_year: float | None
    distance_to_upper_red_m: float
    distance_to_lower_red_m: float
    days_to_black_line: int | None
    sample_count: int
    thresholds: dict[str, float]


def band_for(level_m: float) -> str:
    """Which operating band a level sits in.

    A level exactly on a line is treated as being on the safe side of it: at
    -213.00 the lower red line has been reached but not crossed, and the
    advisory should not yet call for pumping.
    """

    if level_m >= UPPER_RED_LINE_M:
        return BAND_ABOVE_UPPER_RED
    if level_m >= LOWER_RED_LINE_M:
        return BAND_NORMAL
    if level_m > BLACK_LINE_M:
        return BAND_BELOW_LOWER_RED
    return BAND_BELOW_BLACK


def _trend_m_per_day(
    readings: list[LevelReading], *, window_days: int = TREND_WINDOW_DAYS
) -> float | None:
    """Least-squares slope over the recent window, or None if it cannot be fitted.

    A fit rather than a first-minus-last difference, because the published
    series skips days: the two ends of a window are not a fixed distance
    apart, and differencing them silently rescales the answer by however many
    days happened to be missing.

    ponytail: a straight line through thirty days, not a hydrological model.
    It has a real ceiling — the Kinneret's level is strongly seasonal, so a
    window in September catches peak summer evaporation and annualising its
    slope overstates the yearly decline (and a window in February understates
    it). Good enough to say "falling, and roughly how fast"; replace it with a
    seasonal decomposition before anyone uses the projection to size an actual
    pumping programme.
    """

    if not readings:
        return None
    newest = max(reading.observed_at for reading in readings)
    cutoff = newest - timedelta(days=window_days)
    window = [reading for reading in readings if reading.observed_at >= cutoff]
    if len(window) < MINIMUM_TREND_SAMPLES:
        return None

    origin = min(reading.observed_at for reading in window)
    days = [
        (reading.observed_at - origin).total_seconds() / 86400 for reading in window
    ]
    if len(set(days)) < MINIMUM_TREND_SAMPLES:
        # Every sample landed on one instant; there is no slope to fit, and
        # linear_regression would raise rather than say so.
        return None
    return linear_regression(days, [reading.level_m for reading in window]).slope


def _days_until(level_m: float, target_m: float, slope_m_per_day: float | None) -> int | None:
    """How long a falling level takes to reach a line below it."""

    if slope_m_per_day is None or slope_m_per_day >= 0:
        return None
    if level_m <= target_m:
        return None
    return int((level_m - target_m) / -slope_m_per_day)


def _rationale(level_m: float, band: str, slope_m_per_day: float | None) -> str:
    """Why the lake is in this band, in words."""
    where = {
        BAND_ABOVE_UPPER_RED: (
            f"{level_m - UPPER_RED_LINE_M:.2f} m above the upper red line"
        ),
        BAND_NORMAL: f"{level_m - LOWER_RED_LINE_M:.2f} m above the lower red line",
        BAND_BELOW_LOWER_RED: (
            f"{LOWER_RED_LINE_M - level_m:.2f} m below the lower red line"
        ),
        BAND_BELOW_BLACK: f"{BLACK_LINE_M - level_m:.2f} m below the black line",
    }[band]
    if slope_m_per_day is None:
        return (
            f"The lake stands at {level_m:.2f} m, {where}. Trend not assessed: "
            f"too few readings in the last {TREND_WINDOW_DAYS} days."
        )
    direction = "falling" if slope_m_per_day < 0 else "rising"
    return (
        f"The lake stands at {level_m:.2f} m, {where}, and is {direction} at "
        f"{abs(slope_m_per_day) * 365:.2f} m/year over the last "
        f"{TREND_WINDOW_DAYS} days."
    )


@live_actor("analyzer.water_level")
def advise(readings: list[LevelReading]) -> KinneretAdvisory:
    """The current advisory from a series of surveys, newest anywhere in it.

    Raises ValueError on an empty series. A caller with no stored readings has
    nothing to advise on and should say so rather than receive a default.
    """

    if not readings:
        raise ValueError("advise() needs at least one reading")

    latest = max(readings, key=lambda reading: reading.observed_at)
    band = band_for(latest.level_m)
    slope = _trend_m_per_day(readings)
    return KinneretAdvisory(
        level_m=latest.level_m,
        observed_at=latest.observed_at,
        band=band,
        action=ACTIONS[band],
        rationale=_rationale(latest.level_m, band, slope),
        trend_m_per_day=slope,
        trend_m_per_year=None if slope is None else slope * 365,
        distance_to_upper_red_m=UPPER_RED_LINE_M - latest.level_m,
        distance_to_lower_red_m=LOWER_RED_LINE_M - latest.level_m,
        days_to_black_line=_days_until(latest.level_m, BLACK_LINE_M, slope),
        sample_count=len(readings),
        thresholds={
            "upper_red_line_m": UPPER_RED_LINE_M,
            "lower_red_line_m": LOWER_RED_LINE_M,
            "black_line_m": BLACK_LINE_M,
        },
    )
