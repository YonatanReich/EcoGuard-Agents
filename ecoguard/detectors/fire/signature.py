"""What a cell normally does, and whether this detection is it.

The problem this exists for
---------------------------
`satellite.py` suppresses a cell that lights on more than one day in twenty,
from a flat rate in `firms_baselines`. Measured against a full year, that bar
catches 17 cells out of 1,174 — and then blinds us to those 17 forever. The
worst of them lights on 71% of days. A real wildfire there can never be
reported, and `repositories/fire_history.py` already names that failure:

    A caller that finds `persistent` True should not discard the detection.
    It should stop *alerting* on it: a flare stack that also catches the brush
    around it is exactly the case where the record is misleading and the fire
    is real.

A scalar rate cannot make that distinction, because it is a property of the
cell and the question is about the detection. This module answers the second
question: given everything this cell has ever done, how unusual is *this*?

Why this is fitted rather than thresholded
------------------------------------------
Because the separating structure is not a number anyone can write down. The
documented industrial source in the Rishon LeZion belt lights between 22:52 and
00:33, at 0.5-2.0 MW, on one or two pixels, in the same spot. None of those
figures is a rule — the next flare stack has its own — so the profile has to be
learned per cell from its own history. That is what makes this a model: an
unsupervised, per-cell density estimate, used for novelty detection.

Why it is not supervised
------------------------
There are no usable labels. The only ground truth in this repo is
`build_firms_fire_rescue_ground_truth.py`, whose own documentation is explicit
that a match means "a relevant fire was officially recorded in this settlement
in this calendar month" and **not** that any individual FIRMS candidate is a
real fire. Training a false-positive classifier on that label would teach it
that an industrial site in a settlement which also had a real fire that month
is a fire — which is precisely the case that matters and precisely the case it
would get wrong. Unlabelled novelty detection is not a compromise here; it is
the only honest fit to the data that exists.

Why there is no sklearn model file
----------------------------------
Four statistics per cell, one of them circular. An IsolationForest over this
would need a versioned artifact, a retraining job, and special handling for the
hour anyway — and it could not tell an operator why it suppressed something.
Everything in this pipeline has to be arguable with; a suppressed fire most of
all. These statistics are legible, so `explain()` can say "this cell has lit 84
times, always within 40 minutes of 23:10, always near 1.2 MW" and a duty
officer can disagree with it.

The four axes
-------------
  * **hour of day** — a fixed installation runs to a schedule; a fire does not
    care what time it is. Circular, so it is fitted as a mean resultant vector:
    the concentration R says how much the hour tells us at all, and a cell that
    lights at all hours contributes nothing on this axis rather than noise.
  * **radiative power** — on a log scale, because a flare sits inside one order
    of magnitude for years while a fire crosses several in an afternoon.
  * **pixels per overpass** — industry lights the pixel it occupies. A fire
    lights the ones around it too.
  * **spatial scatter** — how far the pixels sit from their own centroid. A
    fixed source is fixed; a front is not.

Only the upward tail counts on the last three. More power, more pixels and more
spread than usual are evidence of a fire; less of any of them is just a quiet
night at the same factory, and scoring that as novel would invert the filter.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

# Below this many overpasses a profile is describing coincidence. A cell that
# clears the rate bar has lit on at least 18 days of the year, so in practice
# only quiet cells fall short — and those are not the ones being suppressed.
MIN_SAMPLES = 12

# Floors on the fitted spreads. A source that reads 1.2 MW every single time
# has a standard deviation of zero, against which 1.3 MW is infinitely
# surprising. Same failure the climatology baseline hits when MAD is zero, same
# answer: refuse to divide by a spread the data cannot support.
MIN_LOG_FRP_SD = 0.15   # ~40% in linear FRP
MIN_PIXEL_SD = 0.5
MIN_SCATTER_SD_M = 150.0

# Below this the hour of day carries no information about the cell and is not
# scored. R is the length of the mean resultant vector: 1.0 is every detection
# at the same minute, 0.0 is uniform around the clock.
MIN_HOUR_CONCENTRATION = 0.55

# z below the first is routine; at or past the second is as novel as this
# reports. Linear between. Deliberately not a tail probability — the fitted
# distributions are small-sample and not Gaussian, and a p-value would claim a
# precision they do not have.
Z_ROUTINE = 1.0
Z_NOVEL = 4.0

# Departure on the hour axis, expressed the same way: hours from the cell's
# usual time, scaled by how tightly it keeps to it.
HOURS_ROUTINE = 1.0
HOURS_NOVEL = 5.0

METRES_PER_DEGREE_LATITUDE = 111_320.0


def _squash(value: float, routine: float, novel: float) -> float:
    """Map a departure onto 0..1, flat below `routine` and at 1 past `novel`."""
    if value <= routine:
        return 0.0
    return min(1.0, (value - routine) / (novel - routine))


def _observed_at(hotspot: Mapping[str, Any]) -> datetime | None:
    """A raw FIRMS row's acquisition moment, as UTC."""
    date = hotspot.get("acquisition_date")
    time = hotspot.get("acquisition_time")
    if date is None or time is None:
        return None
    try:
        return datetime.strptime(f"{date} {str(time).zfill(4)}", "%Y-%m-%d %H%M")
    except (ValueError, TypeError):
        return None


def features_of(
    pixels: Sequence[Mapping[str, Any]], observed_at: datetime
) -> dict[str, float] | None:
    """One overpass of one cell, as the four numbers the profile is fitted on.

    Shared by the fitting path and the scoring path on purpose. A profile fitted
    on one definition of "how bright" and scored against another would be
    comparing two different quantities that happen to share a name.

    Returns None when no pixel carries usable radiative power, which is a real
    FIRMS state and must not become a zero.
    """
    powers = [
        float(pixel["frp"]) for pixel in pixels
        if pixel.get("frp") is not None and float(pixel["frp"]) >= 0
    ]
    if not powers:
        return None

    points = [
        (float(pixel["latitude"]), float(pixel["longitude"]))
        for pixel in pixels
        if pixel.get("latitude") is not None and pixel.get("longitude") is not None
    ]

    # UTC throughout, for both fitting and scoring. A fixed local-time source
    # drifts an hour across the DST boundary, which slightly widens its fitted
    # concentration; that is a smaller error than the timezone bug the
    # conversion would eventually introduce.
    hour = observed_at.hour + observed_at.minute / 60.0

    return {
        "hour": hour,
        # log10 of peak power. Peak rather than total: a fire's intensity is
        # what the hottest part of it is doing, and the sum over pixels would
        # confound intensity with area, which the pixel count already carries.
        "log_frp": math.log10(max(powers) + 1.0),
        "pixels": float(len(powers)),
        "scatter_m": _scatter_metres(points),
    }


def _scatter_metres(points: Sequence[tuple[float, float]]) -> float:
    """RMS distance of the pixels from their own centroid, in metres."""
    if len(points) < 2:
        return 0.0
    mean_lat = sum(latitude for latitude, _ in points) / len(points)
    mean_lon = sum(longitude for _, longitude in points) / len(points)
    lon_scale = METRES_PER_DEGREE_LATITUDE * math.cos(math.radians(mean_lat))
    squares = [
        ((latitude - mean_lat) * METRES_PER_DEGREE_LATITUDE) ** 2
        + ((longitude - mean_lon) * lon_scale) ** 2
        for latitude, longitude in points
    ]
    return math.sqrt(sum(squares) / len(squares))


def overpasses(hotspots: Iterable[Mapping[str, Any]]) -> dict[tuple[str, datetime], list]:
    """Raw FIRMS rows grouped the way the collector groups them: cell, moment.

    Fitting has to see what scoring will see. The live path is handed one
    stored observation, which is already one cell's pixels from one overpass,
    so the history must be cut the same way or the fitted pixel count would be
    a year's worth of pixels rather than an overpass's.
    """
    from ecoguard.shared.cells import cell_for

    grouped: dict[tuple[str, datetime], list] = defaultdict(list)
    for hotspot in hotspots:
        latitude, longitude = hotspot.get("latitude"), hotspot.get("longitude")
        moment = _observed_at(hotspot)
        if latitude is None or longitude is None or moment is None:
            continue
        cell_id = cell_for(float(latitude), float(longitude))
        if cell_id is None:
            continue
        grouped[(cell_id, moment)].append(hotspot)
    return grouped


def fit(samples: Sequence[Mapping[str, float]]) -> dict[str, Any] | None:
    """A cell's profile from its own overpasses. None when there are too few.

    None is not "this cell is quiet". It is "this cell cannot be judged this
    way", and the caller has to keep treating it the way it did before.
    """
    usable = [sample for sample in samples if sample is not None]
    if len(usable) < MIN_SAMPLES:
        return None

    count = len(usable)
    angles = [2 * math.pi * sample["hour"] / 24.0 for sample in usable]
    cosines = sum(math.cos(angle) for angle in angles) / count
    sines = sum(math.sin(angle) for angle in angles) / count
    concentration = math.hypot(cosines, sines)
    mean_hour = (math.degrees(math.atan2(sines, cosines)) / 15.0) % 24.0

    return {
        "samples": count,
        "hour_mean": round(mean_hour, 2),
        "hour_concentration": round(concentration, 3),
        "log_frp_mean": round(_mean(usable, "log_frp"), 4),
        "log_frp_sd": round(max(_sd(usable, "log_frp"), MIN_LOG_FRP_SD), 4),
        "pixels_mean": round(_mean(usable, "pixels"), 3),
        "pixels_sd": round(max(_sd(usable, "pixels"), MIN_PIXEL_SD), 3),
        "scatter_mean_m": round(_mean(usable, "scatter_m"), 1),
        "scatter_sd_m": round(max(_sd(usable, "scatter_m"), MIN_SCATTER_SD_M), 1),
    }


def _mean(samples: Sequence[Mapping[str, float]], key: str) -> float:
    return sum(sample[key] for sample in samples) / len(samples)


def _sd(samples: Sequence[Mapping[str, float]], key: str) -> float:
    if len(samples) < 2:
        return 0.0
    mean = _mean(samples, key)
    variance = sum((sample[key] - mean) ** 2 for sample in samples) / (len(samples) - 1)
    return math.sqrt(variance)


def hours_apart(first: float, second: float) -> float:
    """Distance between two clock hours, the short way round. At most 12."""
    gap = abs(first - second) % 24.0
    return min(gap, 24.0 - gap)


def novelty(
    profile: Mapping[str, Any] | None, features: Mapping[str, float] | None
) -> dict[str, Any] | None:
    """How far this detection departs from what the cell normally does, 0..1.

    Returns None when there is no profile or no usable features — which the
    caller must not read as zero. An unjudged detection is not a routine one.

    The score is the **worst** axis, not the average. Breaking one of a cell's
    regularities badly enough is the whole signal: a 60 MW reading from a source
    that has never exceeded 2 MW is a fire even if it happened at the usual
    hour, and averaging that against three matching axes would bury it.
    """
    if profile is None or features is None:
        return None

    axes: dict[str, float] = {}

    # Hour, only where the cell keeps to one. A cell that lights at all hours
    # says nothing by lighting now, and scoring it anyway would manufacture
    # novelty out of a uniform distribution.
    if profile["hour_concentration"] >= MIN_HOUR_CONCENTRATION:
        axes["hour"] = _squash(
            hours_apart(features["hour"], profile["hour_mean"]),
            HOURS_ROUTINE,
            HOURS_NOVEL,
        )

    # The remaining three, upward only. A quieter-than-usual night at the same
    # installation is not evidence of a fire, and scoring it as novel would
    # invert the filter this exists to be.
    for axis, value_key, mean_key, sd_key in (
        ("power", "log_frp", "log_frp_mean", "log_frp_sd"),
        ("pixels", "pixels", "pixels_mean", "pixels_sd"),
        ("scatter", "scatter_m", "scatter_mean_m", "scatter_sd_m"),
    ):
        z = (features[value_key] - profile[mean_key]) / profile[sd_key]
        axes[axis] = _squash(z, Z_ROUTINE, Z_NOVEL)

    worst = max(axes, key=lambda name: axes[name])
    return {
        "score": round(axes[worst], 3),
        "driver": worst,
        "axes": {name: round(value, 3) for name, value in axes.items()},
        "samples": profile["samples"],
    }


def explain(profile: Mapping[str, Any] | None) -> str:
    """The profile as a sentence, so a suppression can be argued with."""
    if profile is None:
        return "no fitted profile for this cell"
    parts = [f"{profile['samples']} overpasses"]
    if profile["hour_concentration"] >= MIN_HOUR_CONCENTRATION:
        hour = int(profile["hour_mean"])
        minute = int(round((profile["hour_mean"] - hour) * 60)) % 60
        parts.append(f"usually near {hour:02d}:{minute:02d} UTC")
    power = 10 ** profile["log_frp_mean"] - 1.0
    parts.append(f"typically {power:.1f} MW")
    parts.append(f"{profile['pixels_mean']:.1f} pixels")
    return ", ".join(parts)
