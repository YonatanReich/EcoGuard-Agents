"""Read-only population screening for an existing Air Pollution corridor."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from datetime import datetime, timezone

from ecoguard.analyzers.non_emergency.air_pollution.event_analysis_schemas import (
    AnalysisComponent,
    PopulationImpactContext,
    RelevantSettlementPopulationContext,
)
from ecoguard.analyzers.non_emergency.air_pollution.transport_schemas import TransportEvidenceReference
from ecoguard.analyzers.non_emergency.air_pollution.transport_spatial_output import (
    PollutionTransportSpatialOutput,
)

PopulationQuery = Callable[[dict], Mapping[str, object]]

POPULATION_LIMITATIONS = [
    "This is estimated population geographically located within a screening corridor, not an affected or exposed population count.",
    "The screening corridor is not a physical plume and does not confirm pollutant transport or inhalation.",
    "Dataset source, version, reference year, and checksum are not currently available through the shared database layer.",
    "Per-settlement population is unavailable because authoritative locality polygons and codes are not integrated.",
]


class AirPollutionPopulationAnalysisService:
    """Adapt shared PostGIS population aggregation to the Analyzer contract."""

    def __init__(self, population_query: PopulationQuery | None = None) -> None:
        if population_query is None:
            # Lazy import keeps offline Analyzer composition independent from
            # database configuration until this optional service is enabled.
            from ecoguard.database.repositories.area_summary import (
                population_intersection,
            )

            population_query = population_intersection
        self._population_query = population_query

    def analyze(
        self,
        spatial_output: PollutionTransportSpatialOutput,
        *,
        geometry_reference: str,
        evidence_id: str,
        queried_at: datetime,
    ) -> AnalysisComponent[PopulationImpactContext]:
        spatial = PollutionTransportSpatialOutput.model_validate(
            spatial_output.model_dump(round_trip=True)
        )
        if spatial.data_status == "unavailable" or spatial.corridor_polygon is None:
            return AnalysisComponent[PopulationImpactContext](
                status="unavailable",
                unavailable_reason="transport_corridor_unavailable",
            )
        if queried_at.utcoffset() is None:
            raise ValueError("population query time must be timezone-aware")
        try:
            result = self._population_query(
                spatial.corridor_polygon.model_dump(mode="json")
            )
        except Exception:
            return AnalysisComponent[PopulationImpactContext](
                status="unavailable",
                unavailable_reason="shared_population_query_failed",
            )
        if result.get("grid_available") is not True:
            return AnalysisComponent[PopulationImpactContext](
                status="unavailable",
                unavailable_reason="shared_population_grid_unavailable_or_unloaded",
            )
        try:
            cell_count = int(result["intersected_cell_count"])
            weighted_population = float(result["weighted_population"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return AnalysisComponent[PopulationImpactContext](
                status="unavailable",
                unavailable_reason="shared_population_query_malformed",
            )
        if (
            cell_count < 0
            or not math.isfinite(weighted_population)
            or weighted_population < 0
        ):
            return AnalysisComponent[PopulationImpactContext](
                status="unavailable",
                unavailable_reason="shared_population_query_malformed",
            )

        settlements = [
            RelevantSettlementPopulationContext(
                settlement_id=item.settlement_id,
                name=item.name,
                rank=item.rank,
            )
            for item in spatial.settlements
            if item.inside_transport_corridor
        ]
        population = round(weighted_population)
        assessment = PopulationImpactContext(
            geometry_reference=geometry_reference,
            queried_at=queried_at.astimezone(timezone.utc),
            intersected_cell_count=cell_count,
            total_relevant_population=population,
            relevant_settlements=settlements,
            limitations=list(POPULATION_LIMITATIONS),
        )
        evidence = TransportEvidenceReference(
            evidence_id=evidence_id,
            source_name="EcoGuard shared population layer",
            source_type="postgis_population_intersection",
            reference="population_cells",
            metadata={
                "query_method": assessment.query_method,
                "geometry_reference": geometry_reference,
                "intersected_cell_count": cell_count,
                "dataset_metadata_available": False,
                "population_is_affected_count": False,
                "exposure_not_confirmed": True,
            },
        )
        # Partial is deliberate: the spatial estimate is available, while
        # dataset metadata and per-settlement attribution are not.
        return AnalysisComponent[PopulationImpactContext](
            status="partial",
            result=assessment,
            evidence=[evidence],
            limitations=list(POPULATION_LIMITATIONS),
        )
