"""Allen, Wald & Worden (2012) intensity, in the hypocentral form.

These assert behaviour the old radius model could not express at all: that
depth changes the answer, that an earthquake can fail to produce a band
rather than producing it at radius zero, and that the rings nest.
"""

import math

import pytest

from ecoguard.analyzers.earthquake.intensity import (
    epicentral_radius_for_mmi,
    intensity_rings,
    mmi_at,
    sigma_at,
)


def test_intensity_falls_with_distance():
    near = mmi_at(6.0, 10.0)
    mid = mmi_at(6.0, 50.0)
    far = mmi_at(6.0, 200.0)

    assert near > mid > far


def test_intensity_rises_with_magnitude_at_the_same_distance():
    assert mmi_at(4.0, 20.0) < mmi_at(5.0, 20.0) < mmi_at(6.0, 20.0)


def test_depth_changes_the_answer():
    """The defect this module exists to fix.

    The old model took magnitude alone, so an M5.0 at 5 km and at 60 km got
    the same 25 km circle. Depth was collected, stored, and never used.
    """
    shallow = mmi_at(5.0, 5.0)
    deep = mmi_at(5.0, 60.0)

    assert shallow > deep
    assert shallow - deep > 2.0  # not a rounding difference


def test_a_deep_moderate_earthquake_produces_no_damaging_band():
    """Absent, not zero. A band nobody experiences is not a band of radius 0."""
    assert epicentral_radius_for_mmi(5.0, 60.0, 6) is None
    assert intensity_rings(5.0, 60.0) == []


def test_a_shallow_earthquake_of_the_same_size_does():
    rings = intensity_rings(5.0, 5.0)

    levels = [ring["mmi"] for ring in rings]
    assert 6 in levels


def test_rings_nest_and_are_ordered_strongest_first():
    rings = intensity_rings(7.0, 15.0)

    levels = [ring["mmi"] for ring in rings]
    radii = [ring["radius_km"] for ring in rings]
    assert levels == sorted(levels, reverse=True)
    assert radii == sorted(radii), "a weaker band must reach further"


def test_the_ground_radius_accounts_for_depth():
    """A contour at some slant range reaches less far across the ground.

    This is the geometry that makes depth matter: the ring an operator sees
    is the hypocentral distance projected to the surface.
    """
    depth = 25.0
    radius = epicentral_radius_for_mmi(6.0, depth, 6)

    assert radius is not None
    hypocentral = math.sqrt(radius**2 + depth**2)
    assert mmi_at(6.0, hypocentral) == pytest.approx(6.0, abs=0.05)
    assert radius < hypocentral  # the projection always shortens it


def test_uncertainty_is_widest_at_the_source():
    """Reported so a band is not read as an exact boundary."""
    assert sigma_at(0.0) > sigma_at(100.0)
    assert sigma_at(0.0) > 0.8  # most of a whole intensity unit


def test_a_negative_distance_is_rejected():
    with pytest.raises(ValueError):
        mmi_at(5.0, -1.0)
