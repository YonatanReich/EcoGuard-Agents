"""NDVI drives live fuel moisture, and the calendar is only the fallback."""

from ecoguard.analyzers.fire.spread import (
    LIVE_FUEL_MOISTURE_CURED,
    LIVE_FUEL_MOISTURE_GREEN,
    NDVI_CURED,
    NDVI_GREEN,
    live_moisture_from_ndvi,
    rate_of_spread,
)

SHRUBLAND = {"shrubland": 1.0}


def test_anchors_match_the_seasonal_endpoints():
    """The ramp starts and ends where the calendar switch used to jump."""
    assert live_moisture_from_ndvi(NDVI_CURED) == LIVE_FUEL_MOISTURE_CURED
    assert live_moisture_from_ndvi(NDVI_GREEN) == LIVE_FUEL_MOISTURE_GREEN


def test_clamped_outside_the_anchors():
    """A burnt scar is cured, not drier than cured; an irrigated field is green."""
    assert live_moisture_from_ndvi(-0.2) == LIVE_FUEL_MOISTURE_CURED
    assert live_moisture_from_ndvi(0.95) == LIVE_FUEL_MOISTURE_GREEN


def test_greener_ground_is_wetter():
    """Monotonic, and strictly so between the anchors."""
    midpoint = live_moisture_from_ndvi((NDVI_CURED + NDVI_GREEN) / 2)
    assert LIVE_FUEL_MOISTURE_CURED < midpoint < LIVE_FUEL_MOISTURE_GREEN


def test_curing_makes_the_same_hillside_spread_faster():
    """The reason this is wired at all: it has to move the rate of spread.

    Same fuel, same weather, same slope — only the greenness differs, which is
    the September the calendar cannot see.
    """
    conditions = dict(
        dead_fuel_moisture=0.06, wind_speed_kmh=20.0, slope_deg=10.0,
    )
    green = rate_of_spread(
        SHRUBLAND, live_fuel_moisture=live_moisture_from_ndvi(NDVI_GREEN), **conditions
    )
    cured = rate_of_spread(
        SHRUBLAND, live_fuel_moisture=live_moisture_from_ndvi(NDVI_CURED), **conditions
    )
    assert cured["head_ros_m_per_min"] > green["head_ros_m_per_min"]
