"""Historical replay of Israel's 11 May 2024 PM10 dust episode.

Only source observations and external-provider responses are replayed.  The
incident, qualification, analysis, plan and frontend projection are produced
by the normal pipeline.  Baseline lookup deliberately falls through to the
current public active 2021-2025 baselines, making this a retrospective current-
pipeline evaluation rather than a claim about the baseline deployed in 2024.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sqlalchemy import text

from ecoguard.database.engine import Session
from ecoguard.analyzers.air_pollution.transport_prediction_service import (
    AirPollutionTransportPredictionService,
    load_air_pollution_transport_configuration,
)
from ecoguard.analyzers.air_pollution.wind_evidence_service import (
    PersistedFirstWindEvidenceService,
)
from ecoguard.shared.air_quality_schemas import LIVE_QUALITY_POLICY
from ecoguard.shared.ministry_air_quality_client import (
    MinistryAirQualityClient,
    MinistryAirQualityError,
)

SCENARIO_ID = "air_pollution_2024_05_11"
DISPLAY_NAME = "Israel PM10 Dust Episode — 11 May 2024"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / SCENARIO_ID

GROUND_TRUTH: list[dict[str, Any]] = [{
    "id": "AP-2024-05-11",
    "event": "Israeli PM10 dust episode observed at Neve Shaanan and Nesher.",
    "hazard": "air_pollution",
    "latitude": 32.78739964,
    "longitude": 35.02128889,
    "expect_detected": True,
    "expect_route": "non_emergency",
    "expect_marker_within_km": 1.0,
    "expect_min_signals": 2,
    "expect_notes": (
        "Two authentic Ministry PM10 observations in one EcoGuard cell must "
        "independently exceed their current active May/hour p95 buckets and "
        "qualify through unchanged Path A. Official index evidence is clearly "
        "labelled reconstructed demo evidence because the provider no longer "
        "retains the raw 2024 indexFastSrv response."
    ),
}]

EXPECTED_SILENCE: list[dict[str, str]] = []


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _observation_payload(station: dict[str, Any]) -> tuple[datetime, dict[str, Any]]:
    """Normalize one authentic cached point into the collector's stored contract."""
    point = station["point"]
    channel = point["channels"][0]
    provider_time = datetime.fromisoformat(point["datetime"])
    observed_at = provider_time.astimezone(timezone.utc)
    unit = str(channel["units"])
    payload = {
        "pollutant": str(channel["name"]),
        "provider_pollutant_id": str(channel["PollutantId"]),
        "value": float(channel["value"]),
        "unit": unit,
        "provider_unit": unit,
        "observed_at": observed_at.isoformat(),
        "source_id": f"station:{station['station_id']}",
        "provider": "israel_ministry_environment_air_monitoring",
        "measurement_unit": unit,
        "unit_source": "reading",
        "metadata_unit": unit,
        "reading_unit": unit,
        "quality_policy": LIVE_QUALITY_POLICY,
        "provider_station_id": str(station["station_id"]),
        "provider_channel_id": str(channel["id"]),
        "location": {
            "latitude": float(station["latitude"]),
            "longitude": float(station["longitude"]),
        },
        "provider_timestamp": point["datetime"],
        "valid": bool(channel["valid"]),
        "provider_status_id": str(channel["status"]),
        "provider_status": str(channel["status"]),
        "quality_control": "preliminary_unvalidated",
    }
    return observed_at, payload


def build_rows() -> list[dict[str, Any]]:
    """Build only persisted source observations; no downstream result is authored."""
    historical = _fixture("historical_observations.json")
    rows: list[dict[str, Any]] = []
    # Station 86 is deliberately first.  Both readings have the same timestamp,
    # and Python's stable max/order semantics then make station 86 the projected
    # analysis origin whose exact official fixture is available.
    for station in historical["stations"]:
        observed_at, payload = _observation_payload(station)
        unit_id = quote(str(payload["unit"]), safe="")
        rows.append({
            "source": "air_pollution",
            "cell_id": (
                f"ministry:{station['station_id']}:{station['channel_id']}:"
                f"PM10:{unit_id}"
            ),
            "latitude": float(station["latitude"]),
            "longitude": float(station["longitude"]),
            "observed_at": observed_at,
            "payload": payload,
        })

    metar = _fixture("llha_metar.json")
    metar_observed_at = datetime.fromisoformat(
        metar["observed_at"].replace("Z", "+00:00")
    )
    rows.append({
        "source": "metar_wind",
        "cell_id": "metar:LLHA:wind",
        "latitude": float(metar["latitude"]),
        "longitude": float(metar["longitude"]),
        "observed_at": metar_observed_at,
        "payload": {
            "provider": "METAR",
            "evidence_id": f"metar:LLHA:{metar_observed_at.isoformat()}",
            "provider_location_id": "LLHA",
            "provider_location_name": "Haifa Airport",
            "wind_direction_10m": float(metar["wind_from_direction_deg"]),
            "wind_speed_10m": float(metar["wind_speed_kmh"]),
            "wind_gusts_10m": None,
            "wind_direction_unit": "degrees",
            "wind_speed_unit": "km/h",
            "provider_status": "historical_measured_metar",
            "provider_channel_validity": {
                "wind_direction_10m": "valid",
                "wind_speed_10m": "valid",
            },
            "reference": metar["reference"],
            "raw_metar": metar["raw_metar"],
            "variable_direction_from_deg": metar["variable_direction_from_deg"],
            "variable_direction_to_deg": metar["variable_direction_to_deg"],
        },
    })
    return rows


INSERT = text(
    'INSERT INTO "{schema}".observations '
    '(source, cell_id, location, observed_at, ingested_at, payload) '
    'VALUES (:source, :cell_id, '
    'ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography, '
    ':observed_at, :ingested_at, CAST(:payload AS jsonb))'
)


def seed(schema: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Seed historical inputs into the explicit isolated scenario schema."""
    ingested_at = now or datetime.now(timezone.utc)
    rows = build_rows()
    statement = text(str(INSERT).replace("{schema}", schema))
    with Session() as session:
        for row in rows:
            session.execute(statement, {
                **row,
                "ingested_at": ingested_at,
                "payload": json.dumps(row["payload"], ensure_ascii=False),
            })
        session.commit()
    return {
        "observations": len(rows),
        "by_source": {"air_pollution": 2, "metar_wind": 1},
        "seeded_at": ingested_at.isoformat(),
        "expectations": {"events": GROUND_TRUTH, "silence": EXPECTED_SILENCE},
        "reconstructed_official_evidence": True,
        "baseline_mode": "current_active_2021_2025_retrospective",
    }


class ReconstructedIndexReplayClient(MinistryAirQualityClient):
    """Fixture transport; production matching/classification remains inherited."""

    def __init__(self) -> None:
        super().__init__()
        self.fixture = _fixture("reconstructed_index_fast_srv.json")

    def _get_json(self, endpoint: str, *, params=None):
        if endpoint == "stations/86/indexFastSrv":
            return copy.deepcopy({"data": self.fixture["data"]})
        if endpoint == "regions":
            return copy.deepcopy(self.fixture["station_metadata_response"])
        raise MinistryAirQualityError(
            "scenario_fixture_endpoint_unavailable", transient=False
        )


class RecordedPlannerModel:
    """Replay only the external model answer; production grounding still runs."""

    available = True

    def parse_structured(self, *, output_format, **_kwargs):
        return output_format.model_validate(_fixture("planner_response.json"))


class _OfflineHistoricalWindBoundary:
    """Fail closed if the stored historical fixture cannot satisfy policy."""

    def select_wind_evidence(self, **_kwargs):
        raise RuntimeError("historical_scenario_live_wind_disabled")


def ministry_index_client() -> MinistryAirQualityClient:
    return ReconstructedIndexReplayClient()


def planner_model_service() -> RecordedPlannerModel:
    return RecordedPlannerModel()


def transport_prediction_service() -> AirPollutionTransportPredictionService | None:
    """Use the real transport stack with the explicit METAR replay window.

    The deployment freshness window is 30 minutes, while the authentic LLHA
    observation is 55 minutes before the anomaly. A scenario-local 60-minute
    window is explicit replay configuration, not a changed detector threshold.
    All suitability, corridor, settlement and population calculations remain
    production code. Live wind fails closed so it cannot replace the fixture.
    """
    configuration = load_air_pollution_transport_configuration()
    if configuration is None:
        return None
    configuration = configuration.model_copy(update={"wind_max_age_minutes": 60.0})
    return AirPollutionTransportPredictionService(
        wind_evidence_service=PersistedFirstWindEvidenceService(
            _OfflineHistoricalWindBoundary()
        ),
        configuration=configuration,
    )


__all__ = [
    "DISPLAY_NAME", "EXPECTED_SILENCE", "GROUND_TRUTH", "SCENARIO_ID",
    "ReconstructedIndexReplayClient", "RecordedPlannerModel", "build_rows",
    "ministry_index_client", "planner_model_service", "seed",
    "transport_prediction_service",
]
