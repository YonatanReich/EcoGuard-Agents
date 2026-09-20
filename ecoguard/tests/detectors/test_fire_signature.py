"""The one case this exists for: a real fire inside an industrial cell.

Built from the source the module docstrings describe — the Rishon LeZion belt
cell that lights most nights between 22:52 and 00:33 at 0.5-2.0 MW. The test
is that its usual behaviour stays suppressed and a wildfire in the same cell
does not, because before the signature existed both were suppressed forever.
"""

from datetime import datetime, timedelta, timezone

from ecoguard.detectors.fire import signature


def _flare_night(day: int, minute_offset: int = 0, frp: float = 1.2) -> dict:
    """One overpass of the standing source: one pixel, same spot, same hour."""
    moment = datetime(2026, 1, 1, 23, 10, tzinfo=timezone.utc) + timedelta(
        days=day, minutes=minute_offset
    )
    return {
        "pixels": [{"latitude": 31.9700, "longitude": 34.8000, "frp": frp}],
        "observed_at": moment,
    }


def _fitted_profile():
    nights = [
        _flare_night(day, minute_offset=(day % 7) - 3, frp=0.5 + (day % 4) * 0.5)
        for day in range(90)
    ]
    samples = [signature.features_of(n["pixels"], n["observed_at"]) for n in nights]
    profile = signature.fit(samples)
    assert profile is not None, "90 nights should be enough to fit a profile"
    return profile


def test_profile_learns_the_sources_schedule_and_power():
    profile = _fitted_profile()

    # It lights at one time of night, so the hour is informative.
    assert profile["hour_concentration"] > signature.MIN_HOUR_CONCENTRATION
    assert signature.hours_apart(profile["hour_mean"], 23.17) < 0.5

    # And at one order of magnitude. log10(1.25 + 1) is about 0.35.
    assert 0.2 < profile["log_frp_mean"] < 0.5
    assert profile["pixels_mean"] == 1.0


def test_the_usual_night_shift_is_routine():
    profile = _fitted_profile()
    tonight = _flare_night(91, minute_offset=2, frp=1.5)

    departure = signature.novelty(
        profile, signature.features_of(tonight["pixels"], tonight["observed_at"])
    )

    assert departure["score"] < 0.35, departure


def test_a_wildfire_in_the_same_cell_is_not_routine():
    """The case the flat rate could never report."""
    profile = _fitted_profile()
    afternoon = datetime(2026, 4, 2, 14, 5, tzinfo=timezone.utc)
    fire = [
        {"latitude": 31.9700 + 0.004 * i, "longitude": 34.8000 + 0.003 * i, "frp": 60.0}
        for i in range(9)
    ]

    departure = signature.novelty(profile, signature.features_of(fire, afternoon))

    assert departure["score"] >= 0.35, departure
    # Every axis it broke should be visible, not just the verdict.
    assert departure["axes"]["power"] > 0.5
    assert departure["axes"]["pixels"] > 0.5


def test_power_alone_is_enough_at_the_usual_hour():
    """A flare that catches the brush around it still lights at 23:10."""
    profile = _fitted_profile()
    same_hour = datetime(2026, 4, 2, 23, 12, tzinfo=timezone.utc)
    blaze = [{"latitude": 31.9700, "longitude": 34.8000, "frp": 80.0}]

    departure = signature.novelty(profile, signature.features_of(blaze, same_hour))

    # The worst axis carries it. An average over four axes would have buried a
    # 60x power jump under three that matched.
    assert departure["driver"] == "power"
    assert departure["score"] >= 0.35, departure


def test_too_little_history_is_not_a_clearance():
    """No profile must never read as 'judged and routine'."""
    samples = [
        signature.features_of(_flare_night(d)["pixels"], _flare_night(d)["observed_at"])
        for d in range(signature.MIN_SAMPLES - 1)
    ]
    assert signature.fit(samples) is None
    assert signature.novelty(None, samples[0]) is None


def test_a_cell_with_no_schedule_is_not_scored_on_the_hour():
    """A cell lighting around the clock says nothing by lighting now."""
    scattered = []
    for day in range(60):
        moment = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(
            days=day, hours=(day * 7) % 24
        )
        scattered.append(
            signature.features_of(
                [{"latitude": 32.0, "longitude": 35.0, "frp": 3.0}], moment
            )
        )
    profile = signature.fit(scattered)

    assert profile["hour_concentration"] < signature.MIN_HOUR_CONCENTRATION
    departure = signature.novelty(
        profile,
        signature.features_of(
            [{"latitude": 32.0, "longitude": 35.0, "frp": 3.0}],
            datetime(2026, 4, 1, 3, 0, tzinfo=timezone.utc),
        ),
    )
    assert "hour" not in departure["axes"]


def test_a_quieter_than_usual_night_is_not_novel():
    """Less power than normal is not evidence of a fire."""
    profile = _fitted_profile()
    quiet = _flare_night(95, frp=0.2)

    departure = signature.novelty(
        profile, signature.features_of(quiet["pixels"], quiet["observed_at"])
    )

    assert departure["score"] < 0.35, departure


def test_a_fixed_spread_never_divides_by_zero():
    """A source reading exactly the same value forever still has to be scored."""
    identical = [
        signature.features_of(
            [{"latitude": 32.0, "longitude": 35.0, "frp": 1.0}],
            datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc) + timedelta(days=d),
        )
        for d in range(40)
    ]
    profile = signature.fit(identical)

    assert profile["log_frp_sd"] >= signature.MIN_LOG_FRP_SD
    departure = signature.novelty(
        profile,
        signature.features_of(
            [{"latitude": 32.0, "longitude": 35.0, "frp": 1.05}],
            datetime(2026, 3, 1, 23, 0, tzinfo=timezone.utc),
        ),
    )
    assert departure["score"] == 0.0


def test_features_refuse_to_invent_power():
    """No usable FRP is a real FIRMS state and must not become a zero."""
    assert signature.features_of(
        [{"latitude": 32.0, "longitude": 35.0, "frp": None}],
        datetime(2026, 1, 1, tzinfo=timezone.utc),
    ) is None
