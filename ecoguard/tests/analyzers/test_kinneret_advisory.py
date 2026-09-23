"""The band lookup, the trend fit, and the provider parser.

No database and no HTTP: the advisory is a pure function of a list of
readings, and the parser is a pure function of a decoded JSON body.
"""

from datetime import datetime, timedelta, timezone

import pytest

from ecoguard.analyzers.water_level.advisory import (
    BAND_ABOVE_UPPER_RED,
    BAND_BELOW_BLACK,
    BAND_BELOW_LOWER_RED,
    BAND_NORMAL,
    BLACK_LINE_M,
    LOWER_RED_LINE_M,
    UPPER_RED_LINE_M,
    LevelReading,
    advise,
    band_for,
)
from ecoguard.collectors.water_level.kinneret import (
    KinneretLevelError,
    parse_kinneret_records,
)

DAY = timedelta(days=1)
START = datetime(2026, 9, 1, tzinfo=timezone.utc)


def series(*levels, start=START, step=DAY):
    """Readings one step apart, oldest first."""
    return [
        LevelReading(observed_at=start + index * step, level_m=level)
        for index, level in enumerate(levels)
    ]


# --- bands -----------------------------------------------------------------


@pytest.mark.parametrize(
    "level,expected",
    [
        (-205.0, BAND_ABOVE_UPPER_RED),
        (UPPER_RED_LINE_M, BAND_ABOVE_UPPER_RED),
        (UPPER_RED_LINE_M - 0.01, BAND_NORMAL),
        (-211.0, BAND_NORMAL),
        (LOWER_RED_LINE_M, BAND_NORMAL),
        (LOWER_RED_LINE_M - 0.01, BAND_BELOW_LOWER_RED),
        (-214.0, BAND_BELOW_LOWER_RED),
        (BLACK_LINE_M + 0.01, BAND_BELOW_LOWER_RED),
        (BLACK_LINE_M, BAND_BELOW_BLACK),
        (-216.0, BAND_BELOW_BLACK),
    ],
)
def test_every_band_and_both_sides_of_every_line(level, expected):
    assert band_for(level) == expected


def test_a_level_exactly_on_a_line_stays_on_the_safe_side_of_it():
    # Reaching the lower red line is not crossing it, and the advisory must
    # not call for pumping a day early.
    assert band_for(LOWER_RED_LINE_M) == BAND_NORMAL
    assert band_for(UPPER_RED_LINE_M) == BAND_ABOVE_UPPER_RED


# --- the advisory itself ---------------------------------------------------


def test_todays_real_level_recommends_pumping_water_in():
    # -213.47 m, the Water Authority's published level for 2026-09-17.
    advisory = advise(series(-213.41, -213.45, -213.47))

    assert advisory.band == BAND_BELOW_LOWER_RED
    assert "pump desalinated water in" in advisory.action
    assert advisory.level_m == -213.47


def test_a_high_lake_is_told_to_release_and_explicitly_not_to_pump_in():
    advisory = advise(series(-208.9, -208.7))

    assert advisory.band == BAND_ABOVE_UPPER_RED
    assert "Degania" in advisory.action
    assert "Do not pump water in" in advisory.action


def test_a_normal_lake_is_told_to_do_nothing():
    assert advise(series(-211.0, -211.1)).action.startswith("No action required")


def test_the_latest_reading_decides_the_band_whatever_order_they_arrive_in():
    readings = series(-214.0, -211.0)
    assert advise(list(reversed(readings))).band == BAND_NORMAL


def test_distances_are_signed_towards_the_line():
    advisory = advise(series(-213.0, -214.0))

    # A metre below the lower red line and five above the black one.
    assert advisory.distance_to_lower_red_m == pytest.approx(1.0)
    assert advisory.distance_to_upper_red_m == pytest.approx(5.2)


def test_an_empty_series_is_refused_rather_than_given_a_default():
    with pytest.raises(ValueError):
        advise([])


# --- trend -----------------------------------------------------------------


def test_a_falling_lake_yields_a_negative_slope():
    advisory = advise(series(-213.0, -213.1, -213.2, -213.3))

    assert advisory.trend_m_per_day == pytest.approx(-0.1)
    assert advisory.trend_m_per_year == pytest.approx(-36.5)


def test_a_rising_lake_yields_a_positive_slope():
    assert advise(series(-213.3, -213.2, -213.1)).trend_m_per_day > 0


def test_irregular_spacing_does_not_distort_the_fit():
    # The real series skips days — Sep 14 then Sep 10. A first-minus-last
    # difference over this window would read -0.02 m/day instead of -0.01.
    readings = [
        LevelReading(START, -213.00),
        LevelReading(START + 4 * DAY, -213.04),
        LevelReading(START + 5 * DAY, -213.05),
        LevelReading(START + 6 * DAY, -213.06),
    ]
    assert advise(readings).trend_m_per_day == pytest.approx(-0.01)


def test_a_single_reading_reports_no_trend_rather_than_a_flat_one():
    advisory = advise(series(-213.47))

    assert advisory.trend_m_per_day is None
    assert advisory.trend_m_per_year is None
    assert advisory.days_to_black_line is None
    assert "Trend not assessed" in advisory.rationale


def test_readings_older_than_the_window_are_left_out_of_the_fit():
    # A steep old decline and a flat recent month: the advisory reports the
    # month, not the decline.
    old = [LevelReading(START - 200 * DAY, -200.0)]
    recent = series(-213.00, -213.00, -213.00)
    assert advise(old + recent).trend_m_per_day == pytest.approx(0.0)


def test_days_to_the_black_line_is_projected_only_while_falling():
    falling = advise(series(-213.87, -214.87 + 1.0 - 0.1))
    assert falling.days_to_black_line == 9

    assert advise(series(-213.2, -213.1)).days_to_black_line is None


# --- provider parsing ------------------------------------------------------


def body(*records):
    return {"success": True, "result": {"records": list(records)}}


def test_a_ckan_body_becomes_observation_records():
    rows = parse_kinneret_records(
        body(
            {"_id": 1, "Survey_Date": "2026-09-17T00:00:00", "Kinneret_Level": -213.470},
            {"_id": 2, "Survey_Date": "2026-09-16T00:00:00", "Kinneret_Level": -213.465},
        )
    )

    assert len(rows) == 2
    assert rows[0]["payload"]["level_m"] == -213.470
    assert rows[0]["payload"]["survey_date"] == "2026-09-16"
    assert rows[0]["cell_id"]
    # upsert_observations rejects a naive datetime, so the parser must not
    # hand one on.
    assert rows[0]["observed_at"].tzinfo is not None


def test_a_survey_date_is_read_as_an_israeli_calendar_day_not_as_utc():
    # Midnight in Jerusalem is the previous evening in UTC. Reading it as UTC
    # would file every survey under the wrong local day.
    row = parse_kinneret_records(
        body({"Survey_Date": "2026-09-17T00:00:00", "Kinneret_Level": -213.47})
    )[0]
    assert row["observed_at"] == datetime(2026, 9, 16, 21, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "record",
    [
        {"Survey_Date": "2026-09-17T00:00:00", "Kinneret_Level": "not a number"},
        {"Survey_Date": "2026-09-17T00:00:00", "Kinneret_Level": None},
        {"Survey_Date": "", "Kinneret_Level": -213.47},
        {"Kinneret_Level": -213.47},
    ],
)
def test_a_malformed_record_is_refused(record):
    with pytest.raises(KinneretLevelError):
        parse_kinneret_records(body(record))


@pytest.mark.parametrize("level", [-999.0, 213.47, 0.0])
def test_a_level_outside_the_plausible_envelope_is_refused(level):
    # A sign flip or a unit change must not become a pumping recommendation.
    with pytest.raises(KinneretLevelError):
        parse_kinneret_records(
            body({"Survey_Date": "2026-09-17T00:00:00", "Kinneret_Level": level})
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"success": False, "result": {"records": []}},
        {"success": True, "result": {"records": []}},
        {"success": True},
        "not a body",
    ],
)
def test_an_unusable_body_is_refused(payload):
    with pytest.raises(KinneretLevelError):
        parse_kinneret_records(payload)
