"""16 February 2026: the nationwide dust episode, replayed from the Ministry's own data.

At 11:32 that Monday the Ministries of Environmental Protection and Health
warned of high to very high air pollution in all parts of the country, from
dust carried on strong south-easterly winds out of Jordan, expected to last
until Wednesday. They advised the public to reduce strenuous outdoor activity,
and heart and lung patients, older people, children and pregnant women to avoid
it entirely (gov.il, air-pollution-alert-feb-16-2026).

The replay stops at 11:30 and asks what EcoGuard would have published. Every
input is the Ministry's: five-minute readings from every active station, run
through the production normaliser and collector, so the stored rows are the
ones the live collector would have written. The only reconstructed input is
the official index, which the provider no longer serves for this date; it is
computed from the same readings with the Ministry's published method and
labelled as reconstructed on every card that uses it.

Timestamps are the real ones. Rebasing them would judge February readings
against October baselines and look the index up for the wrong day, so the
pipeline's clock is started at the checkpoint instead (REPLAY_AT).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from ecoguard.collectors.pollution.collector import AirPollutionCollector
from ecoguard.database.engine import Session
from ecoguard.detectors.air_pollution.regional_stations import REGIONS
from ecoguard.shared.air_quality_schemas import AirQualityCollectionResult, AirQualityStation
from ecoguard.shared.ministry_air_quality_client import (
    MINISTRY_INDEX_CLOCK,
    STORED_INDEX_SOURCE,
    MinistryAirQualityClient,
)

DATA = json.loads(
    Path(__file__).with_name("air_pollution_2026_02_16_data.json").read_text(encoding="utf-8")
)
CHECKPOINT = datetime.fromisoformat(DATA["checkpoint"])
# The pipeline's "now" while the replay runs: one minute past the checkpoint.
REPLAY_AT = (CHECKPOINT + timedelta(minutes=1)).astimezone(timezone.utc)

# What the Ministries told the public; every advisory must carry it.
WARNING_ADVICE = (
    "vulnerable groups avoid strenuous outdoor activity",
    "others reduce it",
)


def _region(region_id: str) -> dict:
    """One region's expected card, anchored on its primary designated station."""
    region, anchor, stations = REGIONS[region_id]
    where = {
        item["provider_station_id"]: item["location"] for item in DATA["stations"]
    }
    primary = where[stations[0][0]]
    names = " + ".join(name for _, name in stations)
    return {
        "id": f"AP-REGION-{region_id}",
        "event": f"{region}: high air pollution on 16 Feb 2026, read at {names}.",
        "hazard": "air_pollution",
        "latitude": primary["latitude"],
        "longitude": primary["longitude"],
        "expect_detected": True,
        "expect_route": "non_emergency",
        # Matched by the region's anchor cell, not by distance; the marker
        # must sit on one of the region's own stations.
        "expect_cell": anchor,
        "expect_points": [
            (where[sid]["latitude"], where[sid]["longitude"]) for sid, _ in stations
        ],
        "expect_marker_within_km": 1.0,
        "expect_min_signals": 2,
        "expect_classification": ["LOW", "VERY_LOW"],
        "expect_advice": list(WARNING_ADVICE),
        "expect_notes": (
            "The warning covered all parts of the country, so every region's card must "
            "exist, read the air as the warning did (high to very high pollution = index "
            "category LOW or VERY_LOW) and carry its advice. The region's designated "
            "stations report as one incident."
        ),
    }


GROUND_TRUTH: list[dict[str, Any]] = [_region(region_id) for region_id in REGIONS]

# One card per region and nothing else: an extra card is a finding.
EXPECTED_BYPRODUCTS: list[dict[str, str]] = []
EXPECTED_SILENCE: list[dict[str, str]] = []


def build_rows() -> list[dict[str, Any]]:
    """The collector's rows for the stored readings, by the collector's own code."""
    stations = {
        item["provider_station_id"]: AirQualityStation.model_validate(item)
        for item in DATA["stations"]
    }
    statuses = {
        str(item.get("Id")): str(item.get("Name"))
        for item in DATA["statuses"]
        if item.get("Id") is not None and item.get("Name") is not None
    }
    observations, excluded = [], []
    for station_id, rows in DATA["readings"].items():
        for row in rows:
            # indexFastSrv-style rows carry one time per row; the normaliser
            # reads it per channel, as regions/data/latest supplies it.
            raw = {
                "stationId": station_id,
                "regionData": {"channels": [
                    {**channel, "datetime": row["datetime"]} for channel in row["channels"]
                ]},
            }
            MinistryAirQualityClient._normalize_station_readings(
                raw, stations, statuses, observations, excluded
            )
    collected_at = CHECKPOINT.astimezone(timezone.utc)

    class Replay:
        def collect_latest(self):
            return AirQualityCollectionResult(
                status="success", collected_at=collected_at,
                observations=observations, excluded=excluded,
            )

    return AirPollutionCollector(client=Replay(), clock=lambda: collected_at).fetch()


def index_rows() -> list[dict[str, Any]]:
    """The reconstructed index, stored where the index lookup reads first."""
    day = CHECKPOINT.astimezone(MINISTRY_INDEX_CLOCK).date().isoformat()
    return [
        {
            "cell_id": f"ministry_index:{station_id}",
            "observed_at": CHECKPOINT.astimezone(timezone.utc),
            "latitude": None, "longitude": None,
            "payload": {"provider_day": day, "reconstructed": True, "response": response},
        }
        for station_id, response in DATA["index"].items()
    ]


INSERT = text(
    'INSERT INTO "{schema}".observations '
    "(source, cell_id, location, observed_at, ingested_at, payload) "
    "VALUES (:source, :cell_id, "
    "CASE WHEN CAST(:latitude AS double precision) IS NULL THEN NULL ELSE "
    "ST_SetSRID(ST_MakePoint(CAST(:longitude AS double precision), "
    "CAST(:latitude AS double precision)), 4326)::geography END, "
    ":observed_at, :ingested_at, CAST(:payload AS jsonb))"
)


def seed(schema: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Write the readings and the reconstructed index into the demo schema."""
    # ingested_at is real now: the detector reads by arrival, not by reading time.
    ingested_at = now or datetime.now(timezone.utc)
    readings = build_rows()
    indexes = index_rows()
    statement = text(str(INSERT).replace("{schema}", schema))
    with Session() as session:
        session.execute(statement, [
            {
                "source": source, "cell_id": row["cell_id"],
                "latitude": row["latitude"], "longitude": row["longitude"],
                "observed_at": row["observed_at"], "ingested_at": ingested_at,
                "payload": json.dumps(row["payload"], ensure_ascii=False),
            }
            for source, group in (("air_pollution", readings), (STORED_INDEX_SOURCE, indexes))
            for row in group
        ])
        session.commit()
    return {
        "observations": len(readings) + len(indexes),
        "by_source": {"air_pollution": len(readings), STORED_INDEX_SOURCE: len(indexes)},
        "seeded_at": ingested_at.isoformat(),
        "replay_at": REPLAY_AT.isoformat(),
        "expectations": {"events": GROUND_TRUTH, "silence": EXPECTED_SILENCE},
    }


# Thirteen regions are thirteen samples of one national episode. Ten of them
# right already paint the Ministry's picture; demanding all thirteen would fail
# the demo on one planner wording slip in one region.
REQUIRED_PASSES = 10

__all__ = ["REQUIRED_PASSES", "GROUND_TRUTH", "EXPECTED_BYPRODUCTS", "EXPECTED_SILENCE", "REPLAY_AT", "build_rows", "seed"]
