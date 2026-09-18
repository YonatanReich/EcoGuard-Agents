"""Additional verification for already-qualified significant pollution events."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from ecoguard.analyzers.non_emergency.air_pollution.event_analysis_schemas import (
    AirPollutionAdditionalVerification,
    AirPollutionEventAnalysis,
    AirPollutionEventQualification,
    OfficialPollutantClassification,
    PossibleSourceCorrelation,
)

CollectorRunReader = Callable[[], dict[str, Any] | None]

LIMITATION = (
    "Fire evidence indicates possible source correlation only; it does not confirm "
    "causation, an emission source, a plume, or exposure."
)


def _default_firms_run_reader() -> dict[str, Any] | None:
    from ecoguard.database.repositories.air_pollution_verification import (
        latest_firms_collector_run,
    )

    return latest_firms_collector_run()


class AirPollutionAdditionalVerificationService:
    """Reuse Coordinator links and shared provider state; never collect again."""

    def __init__(
        self,
        *,
        firms_run_reader: CollectorRunReader = _default_firms_run_reader,
    ) -> None:
        self._firms_run_reader = firms_run_reader

    def verify(
        self,
        *,
        incident: Mapping[str, Any],
        analysis: AirPollutionEventAnalysis,
        qualification: AirPollutionEventQualification,
        classification: OfficialPollutantClassification,
        checked_at: datetime,
    ) -> AirPollutionAdditionalVerification | None:
        checked_at = self._utc(checked_at)
        if not qualification.qualified:
            return None
        if classification.classification == "MODERATE":
            return AirPollutionAdditionalVerification(
                status="CONTEXT_ONLY",
                checked_at=checked_at,
                reason="additional_verification_not_triggered_for_moderate",
                limitations=[LIMITATION],
            )
        if classification.classification not in {"LOW", "VERY_LOW"}:
            return None

        links = incident.get("links")
        links = links if isinstance(links, list) else []
        correlations = [
            self._correlation(link)
            for link in links
            if isinstance(link, Mapping)
            and link.get("cause_hazard") == "fire"
            and link.get("effect_hazard") == "air_pollution"
        ]
        correlations = [item for item in correlations if item is not None]
        if correlations:
            return AirPollutionAdditionalVerification(
                status="CORROBORATED",
                checked_at=checked_at,
                providers_checked=["shared_coordinator_fire_air_pollution_links"],
                evidence_references=[
                    f"incident:{item.source_incident_id}" for item in correlations
                ],
                reason="existing_fire_air_pollution_correlation_rule_satisfied",
                limitations=[LIMITATION],
                possible_source_correlations=correlations,
            )

        wind = analysis.transport_analysis.result
        if wind is None:
            return self._unavailable(
                checked_at,
                "compatible_wind_evidence_unavailable",
                ["shared_coordinator_fire_air_pollution_links"],
            )
        try:
            firms_run = self._firms_run_reader()
        except Exception:
            return self._unavailable(
                checked_at,
                "firms_collection_state_unavailable",
                ["shared_coordinator_fire_air_pollution_links", "IMS"],
            )
        providers = [
            "shared_coordinator_fire_air_pollution_links",
            "NASA FIRMS",
            wind.wind_evidence.provider,
        ]
        if firms_run is None or firms_run.get("status") != "ok":
            return self._unavailable(
                checked_at,
                "firms_evidence_unavailable",
                providers,
            )
        return AirPollutionAdditionalVerification(
            status="NO_EXTERNAL_EVIDENCE",
            checked_at=checked_at,
            providers_checked=providers,
            reason="available_evidence_has_no_existing_supporting_correlation",
            limitations=[
                LIMITATION,
                "No supporting external evidence does not mean the qualified event is false.",
            ],
        )

    @staticmethod
    def _correlation(link: Mapping[str, Any]) -> PossibleSourceCorrelation | None:
        source_incident = link.get("cause_incident")
        if not isinstance(source_incident, str) or not source_incident:
            return None
        fields = {
            name: value
            for name, value in (
                ("distance_km", link.get("distance_km")),
                ("bearing_deg", link.get("bearing_deg")),
                ("lag_hours", link.get("lag_hours")),
            )
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        return PossibleSourceCorrelation(
            source_incident_id=source_incident,
            evidence={
                "rule": "existing_fire_to_air_pollution_coordinator_correlation",
                "link_rationale_retained_for_audit": link.get("rationale"),
            },
            **fields,
        )

    @staticmethod
    def _unavailable(
        checked_at: datetime,
        reason: str,
        providers: list[str],
    ) -> AirPollutionAdditionalVerification:
        return AirPollutionAdditionalVerification(
            status="VERIFICATION_UNAVAILABLE",
            checked_at=checked_at,
            providers_checked=providers,
            reason=reason,
            limitations=[LIMITATION],
        )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("verification clock must carry a UTC offset")
        return value.astimezone(timezone.utc)
