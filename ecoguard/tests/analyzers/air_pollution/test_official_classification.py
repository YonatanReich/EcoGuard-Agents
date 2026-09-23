"""EA-371 official pollutant classification and display policy tests."""

import pytest

from ecoguard.analyzers.air_pollution.event_analysis_schemas import (
    AirPollutionEventQualification,
)
from ecoguard.analyzers.air_pollution.official_classification import (
    classify_official_pollutant_sub_index,
    publication_policy,
)


@pytest.mark.parametrize(("value", "expected"), [
    (100, "GOOD"),
    (51, "GOOD"),
    (50, "MODERATE"),
    (0, "MODERATE"),
    (-1, "LOW"),
    (-200, "LOW"),
    (-201, "VERY_LOW"),
    (-400, "VERY_LOW"),
    (101, "UNKNOWN"),
    (-401, "UNKNOWN"),
    (None, "UNKNOWN"),
])
def test_approved_official_pollutant_sub_index_bands(value, expected):
    result = classify_official_pollutant_sub_index(
        pollutant="NO2", pollutant_sub_index=value
    )

    assert result.classification == expected
    assert result.pollutant == "NO2"


def test_display_policy_applies_only_after_event_qualification():
    moderate = classify_official_pollutant_sub_index(
        pollutant="NO2", pollutant_sub_index=25
    )
    unqualified = AirPollutionEventQualification(
        qualified=False,
        reason="air_pollution_event_qualification_not_satisfied",
    )

    assert publication_policy(
        unqualified, moderate
    ).publish_to_operational_dashboard is False


@pytest.mark.parametrize(("value", "published", "emphasis"), [
    (75, False, "none"),
    (25, True, "standard"),
    (-25, True, "strong"),
    (-250, True, "strong"),
    (None, False, "none"),
])
def test_qualified_display_policy(value, published, emphasis):
    qualified = AirPollutionEventQualification(
        qualified=True,
        path="PATH_A",
        reason="same_pollutant_different_station_spatial_corroboration",
    )
    classification = classify_official_pollutant_sub_index(
        pollutant="NO2", pollutant_sub_index=value
    )

    policy = publication_policy(qualified, classification)

    assert policy.publish_to_operational_dashboard is published
    assert policy.emphasis == emphasis
