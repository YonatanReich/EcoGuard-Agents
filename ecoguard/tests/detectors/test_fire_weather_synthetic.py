"""A world whose anomalies are known in advance, to see if the detector agrees.

Testing a detector on real weather can only ever ask "is what it found
defensible". It cannot ask the question that matters - did it find everything
there was to find, and nothing else - because nobody knows the right answer for
a real day.

So this builds one. Twelve cells are given invented climates, two of them very
different (a humid mild "coast" and a dry hot "interior"), across two times of
year with different distributions again. Every reading is then planted at a
position chosen from the *specification* of rarity, not by running the code:

    a value below the record minimum        is at percentile 0.0
    a value at the median                   is at percentile 0.5
    a value at p95                          is at percentile 0.95
    a value f of the way from p95 to max    is at percentile 0.95 + f * 0.05

Those come from `percentile_of`'s documented interpolation. The expected verdict
for each planting is worked out from that arithmetic alone, so a bug in
`rarity_from_baseline` cannot hide by agreeing with the test.

The two boundary plantings are the point of the exercise. One sits at percentile
0.9995 and must be reported; the other at 0.995 and must not. They differ by a
fifth of a percent of the distribution, and nothing but correct interpolation
separates them.

What this proves and what it does not: it proves the statistics are right - that
"unusual for this place at this time of year" is computed and thresholded
correctly. It does not prove that a statistical fire-weather anomaly is an
active fire; that requires separate fire-detection evidence.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from ecoguard.detectors.fire import weather
from ecoguard.shared.signals import HIGH, REPORTING_RARITY

HOUR = 15
WINTER = datetime(2026, 2, 20, HOUR, 0, tzinfo=timezone.utc)
SUMMER = datetime(2026, 7, 20, HOUR, 0, tzinfo=timezone.utc)
SEASONS = {"winter": WINTER, "summer": SUMMER}

BASELINE_COLUMNS = (
    "cell_id, variable, month, hour, samples, mean, std, median, mad, "
    "p05, p25, p75, p95, minimum, maximum"
)


def _quantiles(minimum, p05, p25, median, p75, p95, maximum):
    return {"minimum": minimum, "p05": p05, "p25": p25, "median": median,
            "p75": p75, "p95": p95, "maximum": maximum}


# Two invented climates. They differ enough that the same raw reading has to
# mean different things in each, which is the whole claim being tested.
CLIMATES = {
    "coast": {
        "winter": {
            "temperature_2m": _quantiles(2, 8, 12, 15, 18, 21, 27),
            "relative_humidity_2m": _quantiles(30, 45, 60, 72, 82, 92, 100),
            "wind_speed_10m": _quantiles(0, 3, 8, 14, 21, 30, 48),
            "vapour_pressure_deficit": _quantiles(0.0, 0.1, 0.2, 0.4, 0.7, 1.1, 2.0),
        },
        "summer": {
            "temperature_2m": _quantiles(20, 24, 27, 29, 31, 34, 40),
            "relative_humidity_2m": _quantiles(35, 50, 62, 70, 78, 86, 96),
            "wind_speed_10m": _quantiles(0, 4, 9, 15, 22, 31, 50),
            "vapour_pressure_deficit": _quantiles(0.2, 0.6, 1.0, 1.4, 1.9, 2.6, 4.0),
        },
    },
    "interior": {
        "winter": {
            "temperature_2m": _quantiles(-2, 4, 9, 13, 17, 22, 29),
            "relative_humidity_2m": _quantiles(12, 22, 34, 45, 58, 72, 90),
            "wind_speed_10m": _quantiles(0, 2, 5, 9, 14, 21, 36),
            "vapour_pressure_deficit": _quantiles(0.0, 0.2, 0.4, 0.8, 1.3, 2.0, 3.2),
        },
        "summer": {
            "temperature_2m": _quantiles(24, 29, 33, 36, 39, 42, 48),
            "relative_humidity_2m": _quantiles(5, 10, 16, 22, 30, 40, 60),
            "wind_speed_10m": _quantiles(0, 3, 6, 10, 16, 24, 40),
            "vapour_pressure_deficit": _quantiles(1.0, 2.0, 3.2, 4.4, 5.8, 7.5, 11.0),
        },
    },
}


# --- plantings, positioned by the specification of percentile_of -------------
#
# Each returns the value to store and whether the detector must report it.

def at_median(q, direction):
    """Percentile 0.5. Rarity 0.5 either way. The most ordinary reading there is."""
    return q["median"], False


def at_p95(q, direction):
    """Percentile 0.95 -> rarity 0.95 for HIGH, 0.05 for LOW. Never reportable."""
    return q["p95"], False


def at_p05(q, direction):
    """Percentile 0.05 -> rarity 0.95 for LOW. Unusual, and still under the bar."""
    return q["p05"], False


def beyond_record(q, direction):
    """Outside everything on record: percentile saturates at 0.0 or 1.0."""
    if direction == HIGH:
        return q["maximum"] + 5, True
    return q["minimum"] - 5, True


def just_over_threshold(q, direction):
    """Percentile 0.9995 on the concerning side - a hair past the bar.

    HIGH: 99% of the way from p95 to the record high is 0.95 + 0.99*0.05.
    LOW:  1% of the way from the record low to p05 is 0.05 * 0.01, and
          rarity is one minus that.
    """
    if direction == HIGH:
        return q["p95"] + 0.99 * (q["maximum"] - q["p95"]), True
    return q["minimum"] + 0.01 * (q["p05"] - q["minimum"]), True


def just_under_threshold(q, direction):
    """Percentile 0.995 - unmistakably rare, and still below the bar.

    The companion to the planting above, and the only one that can tell a
    correct interpolation from a plausible one.
    """
    if direction == HIGH:
        return q["p95"] + 0.90 * (q["maximum"] - q["p95"]), False
    return q["minimum"] + 0.10 * (q["p05"] - q["minimum"]), False


PLANTINGS = {
    "median": at_median,
    "p95": at_p95,
    "p05": at_p05,
    "beyond_record": beyond_record,
    "just_over": just_over_threshold,
    "just_under": just_under_threshold,
}

# Which planting each cell gets for each variable. Rotated so that every
# variable meets every planting somewhere, and most cells are entirely
# ordinary - a detector that reports everything must fail loudly.
PLAN = [
    #  cell index: (temperature, humidity, wind, vpd)
    ("median", "median", "median", "median"),
    ("median", "median", "median", "median"),
    ("beyond_record", "median", "median", "median"),
    ("median", "beyond_record", "median", "median"),
    ("median", "median", "beyond_record", "median"),
    ("median", "median", "median", "beyond_record"),
    ("just_over", "median", "median", "median"),
    ("median", "just_over", "median", "median"),
    ("just_under", "median", "median", "median"),
    ("median", "just_under", "median", "median"),
    ("p95", "p05", "p95", "p95"),
    ("median", "median", "just_over", "just_under"),
]

VARIABLE_ORDER = (
    "temperature_2m", "relative_humidity_2m",
    "wind_speed_10m", "vapour_pressure_deficit",
)


@pytest.fixture
def world(database):
    """Build the artificial world, and dismantle it exactly.

    The baselines it needs occupy (month, hour) buckets the real climatology
    already fills, so the real rows are lifted out and put back afterwards.
    Nothing real is destroyed by running these tests.
    """
    weather._baseline_cells.cache_clear()
    mapping = weather._baseline_cells()
    if not mapping:
        pytest.skip("no weather baselines loaded")

    # One observation cell per baseline cell, so every planting is judged by a
    # distribution no other planting shares.
    one_per_baseline = {}
    for cell_id, baseline_cell in sorted(mapping.items()):
        one_per_baseline.setdefault(baseline_cell, cell_id)
    pairs = sorted(one_per_baseline.items())[: len(PLAN)]
    if len(pairs) < len(PLAN):
        pytest.skip(f"need {len(PLAN)} baseline cells, found {len(pairs)}")

    # First half coast, second half interior.
    cells = [
        {
            "cell_id": cell_id,
            "baseline_cell": baseline_cell,
            "climate": "coast" if i < len(pairs) // 2 else "interior",
            "plan": dict(zip(VARIABLE_ORDER, PLAN[i])),
        }
        for i, (baseline_cell, cell_id) in enumerate(pairs)
    ]

    months = {season: when.month for season, when in SEASONS.items()}

    with database.connect() as connection:
        borrowed = [
            dict(row)
            for row in connection.execute(
                text(f"SELECT {BASELINE_COLUMNS} FROM weather_baselines "
                     "WHERE month = ANY(:months) AND hour = :hour"),
                {"months": list(months.values()), "hour": HOUR},
            ).mappings().all()
        ]

    def _clear():
        with database.connect() as connection:
            connection.execute(
                text("DELETE FROM weather_baselines "
                     "WHERE month = ANY(:months) AND hour = :hour"),
                {"months": list(months.values()), "hour": HOUR},
            )
            connection.execute(
                text("DELETE FROM observations WHERE observed_at = ANY(:whens)"),
                {"whens": list(SEASONS.values())},
            )
            connection.commit()

    _clear()

    baseline_rows, observation_rows, expected = [], [], set()
    for cell in cells:
        for season, when in SEASONS.items():
            quantiles = CLIMATES[cell["climate"]][season]
            payload = {}
            for variable in VARIABLE_ORDER:
                q = quantiles[variable]
                direction = weather.DIRECTIONS[variable]
                value, reportable = PLANTINGS[cell["plan"][variable]](q, direction)
                payload[variable] = round(value, 4)
                if reportable:
                    expected.add((cell["cell_id"], variable, when))
                baseline_rows.append({
                    "cell_id": cell["baseline_cell"], "variable": variable,
                    "month": when.month, "hour": HOUR, "samples": 300,
                    "mean": q["median"], "std": 1.0, "mad": 1.0, **q,
                })
            observation_rows.append({
                "cell_id": cell["cell_id"], "when": when,
                "payload": json.dumps(payload),
            })

    placeholders = ", ".join(f":{name.strip()}" for name in BASELINE_COLUMNS.split(","))
    with database.connect() as connection:
        connection.execute(
            text(f"INSERT INTO weather_baselines ({BASELINE_COLUMNS}) "
                 f"VALUES ({placeholders})"),
            baseline_rows,
        )
        connection.execute(
            text("INSERT INTO observations "
                 "  (source, cell_id, observed_at, ingested_at, issued_at, payload) "
                 "VALUES ('weather', :cell_id, :when, :when, NULL, :payload)"),
            observation_rows,
        )
        connection.commit()

    yield {"cells": cells, "expected": expected}

    _clear()
    if borrowed:
        with database.connect() as connection:
            connection.execute(
                text(f"INSERT INTO weather_baselines ({BASELINE_COLUMNS}) "
                     f"VALUES ({placeholders})"),
                borrowed,
            )
            connection.commit()


def _found(season):
    return {
        (s.cell_id, s.variable, s.observed_at)
        for s in weather.detect(at=SEASONS[season])
    }


# --- the whole point --------------------------------------------------------

def test_it_finds_every_planted_anomaly_and_nothing_else(world):
    """Exact set equality across both seasons. No misses, no extras."""
    found = _found("winter") | _found("summer")
    expected = world["expected"]

    assert found - expected == set(), "reported something that was not planted"
    assert expected - found == set(), "missed a planted anomaly"
    assert found == expected


def test_the_planting_is_not_trivially_easy(world):
    """Guard the guard: most readings must be ordinary, or 'only them' is cheap.

    A test where everything is an anomaly would pass for a detector that
    reports unconditionally.
    """
    total = len(PLAN) * len(SEASONS) * len(VARIABLE_ORDER)
    planted = len(world["expected"])
    assert planted >= 8, "too few anomalies to be convincing"
    assert planted < total * 0.25, "too many anomalies - a yes-man would pass"


# --- the boundary -----------------------------------------------------------

def test_the_threshold_separates_readings_a_fifth_of_a_percent_apart(world):
    """percentile 0.9995 is reported, 0.995 is not. Nothing else distinguishes them."""
    reported = {(s.cell_id, s.variable) for s in weather.detect(at=WINTER)}

    over = [c for c in world["cells"] if "just_over" in c["plan"].values()]
    under = [c for c in world["cells"] if "just_under" in c["plan"].values()]
    assert over and under, "the plan must contain both boundary cases"

    for cell in over:
        for variable, planting in cell["plan"].items():
            if planting == "just_over":
                assert (cell["cell_id"], variable) in reported
    for cell in under:
        for variable, planting in cell["plan"].items():
            if planting == "just_under":
                assert (cell["cell_id"], variable) not in reported


def test_a_reading_at_p95_is_never_reported(world):
    """p95 is rarity 0.95 - rare, and two orders of magnitude short of the bar."""
    reported = {(s.cell_id, s.variable) for s in weather.detect(at=WINTER)}
    for cell in world["cells"]:
        for variable, planting in cell["plan"].items():
            if planting in ("p95", "p05"):
                assert (cell["cell_id"], variable) not in reported


# --- area and time of year --------------------------------------------------

def test_the_same_reading_means_different_things_in_different_places(world):
    """The claim the whole design rests on, tested directly.

    35 C is the record high on the invented coast and an ordinary summer
    afternoon inland. One reading, two verdicts, decided only by where it is.
    """
    coast = next(c for c in world["cells"] if c["climate"] == "coast")
    interior = next(c for c in world["cells"] if c["climate"] == "interior")

    from ecoguard.detectors.fire.weather import _baselines
    loaded = _baselines(
        {coast["baseline_cell"], interior["baseline_cell"]}, {SUMMER.month}, {HOUR}
    )
    from ecoguard.shared.signals import rarity_from_baseline

    reading = 41.0
    coast_rarity = rarity_from_baseline(
        reading, loaded[(coast["baseline_cell"], "temperature_2m", SUMMER.month, HOUR)],
        HIGH,
    )
    interior_rarity = rarity_from_baseline(
        reading,
        loaded[(interior["baseline_cell"], "temperature_2m", SUMMER.month, HOUR)],
        HIGH,
    )

    assert coast_rarity >= REPORTING_RARITY, "41 C beats the coast's record of 40"
    assert interior_rarity < REPORTING_RARITY, "41 C is a normal interior summer day"


def test_the_same_reading_means_different_things_in_different_seasons(world):
    """Same cell, same value, different time of year, opposite verdicts."""
    cell = next(c for c in world["cells"] if c["climate"] == "coast")

    from ecoguard.detectors.fire.weather import _baselines
    from ecoguard.shared.signals import rarity_from_baseline

    winter = _baselines({cell["baseline_cell"]}, {WINTER.month}, {HOUR})
    summer = _baselines({cell["baseline_cell"]}, {SUMMER.month}, {HOUR})

    # 26 C: just under the coast's winter record of 27, and a mild summer day.
    reading = 26.0
    winter_rarity = rarity_from_baseline(
        reading, winter[(cell["baseline_cell"], "temperature_2m", WINTER.month, HOUR)],
        HIGH,
    )
    summer_rarity = rarity_from_baseline(
        reading, summer[(cell["baseline_cell"], "temperature_2m", SUMMER.month, HOUR)],
        HIGH,
    )

    assert winter_rarity > 0.95, "26 C in winter is near the record"
    assert summer_rarity < 0.5, "26 C in summer is below the median"


# --- the sweep is not leaking ----------------------------------------------

def test_only_the_planted_cells_are_assessed(world):
    """Nothing real leaks into the artificial world.

    The seasons are chosen outside the range of any stored observation, so a
    signal from a cell that was never planted would mean the time window is
    not doing its job.
    """
    planted = {c["cell_id"] for c in world["cells"]}
    for season in SEASONS:
        for signal in weather.detect(at=SEASONS[season]):
            assert signal.cell_id in planted


def test_a_planted_world_one_hour_stale_reports_nothing(world):
    """The freshness window still applies to artificial data."""
    assert weather.detect(at=WINTER + weather.MAX_AGE + timedelta(minutes=1)) == []
