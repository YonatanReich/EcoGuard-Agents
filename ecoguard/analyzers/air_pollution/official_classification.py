"""Typed representation of official Ministry pollutant sub-index bands."""

from __future__ import annotations

import math

from ecoguard.analyzers.air_pollution.event_analysis_schemas import (
    AirPollutionEventQualification,
    AirPollutionPublicationPolicy,
    OfficialPollutantClassification,
)


def classify_official_pollutant_sub_index(
    *,
    pollutant: str,
    pollutant_sub_index: float | None,
) -> OfficialPollutantClassification:
    """Classify only values inside the approved official Ministry bands."""

    value = pollutant_sub_index
    if (
        value is None
        or isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        return OfficialPollutantClassification(
            classification="UNKNOWN",
            pollutant=pollutant,
            pollutant_sub_index=None,
            reason="pollutant_sub_index_unavailable",
        )
    value = float(value)
    if 51 <= value <= 100:
        category = "GOOD"
    elif 0 <= value <= 50:
        category = "MODERATE"
    elif -200 <= value <= -1:
        category = "LOW"
    elif -400 <= value <= -201:
        category = "VERY_LOW"
    else:
        category = "UNKNOWN"
    return OfficialPollutantClassification(
        classification=category,
        pollutant=pollutant,
        pollutant_sub_index=value,
        reason=(
            "official_ministry_pollutant_sub_index_band"
            if category != "UNKNOWN"
            else "pollutant_sub_index_outside_approved_official_bands"
        ),
    )


def publication_policy(
    qualification: AirPollutionEventQualification,
    classification: OfficialPollutantClassification,
) -> AirPollutionPublicationPolicy:
    """Decide operational visibility after, and never instead of, qualification."""

    if not qualification.qualified:
        return AirPollutionPublicationPolicy(
            publish_to_operational_dashboard=False,
            emphasis="none",
            reason="event_not_path_a_or_path_b_qualified",
        )
    if classification.classification == "MODERATE":
        return AirPollutionPublicationPolicy(
            publish_to_operational_dashboard=True,
            emphasis="standard",
            reason="qualified_event_meets_official_moderate_display_threshold",
        )
    if classification.classification in {"LOW", "VERY_LOW"}:
        return AirPollutionPublicationPolicy(
            publish_to_operational_dashboard=True,
            emphasis="strong",
            reason="qualified_event_has_significant_official_pollutant_classification",
        )
    return AirPollutionPublicationPolicy(
        publish_to_operational_dashboard=False,
        emphasis="none",
        reason=(
            "qualified_good_event_retained_internally"
            if classification.classification == "GOOD"
            else "official_pollutant_classification_unavailable"
        ),
    )
