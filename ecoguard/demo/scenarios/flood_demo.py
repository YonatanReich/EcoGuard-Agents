"""Flood demo: two historical events, replayed through the real detector.

Only measured hydrometric observations are seeded. The historical clock is
rebased near the demo start so the detector's freshness checks remain exactly
the same as in production, while the intervals between readings stay intact.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from ecoguard.database.engine import Session


HYDROMETRIC_SOURCE = "water_authority_hydrometric_observations"

HADERA = (32.439826965332, 34.9532470703125)
ZEELIM = (31.3522, 35.3503)

HADERA_CELL = "risk-05000m-r0067-c0014"
ZEELIM_CELL = "risk-05000m-r0043-c0021"

HADERA_THRESHOLDS = (32.0, 91.0, 138.0, 190.0, 270.0, 330.0)
ZEELIM_THRESHOLDS = (5.0, 20.0, 48.0, 92.0, 165.0, 240.0)


GROUND_TRUTH: list[dict[str, Any]] = [
    {
        "id": "FD1",
        "event": (
            "Nahal Hadera flood on 8 January 2013, detected at Q2 and then "
            "escalating into the Q5 severity band."
        ),
        "hazard": "flood",
        "latitude": HADERA[0],
        "longitude": HADERA[1],
        "expect_detected": True,
        "expect_route": "emergency",
        "expect_marker_within_km": 4.0,
        "expect_min_signals": 2,
        "expect_notes": (
            "Nahal Hadera is a perennial (flowing-baseline) stream. Its flood "
            "is confirmed by two consecutive readings at or above the "
            "station's Q2: 66.14 and 77.78 m3/s, measured at 11:09:45 and "
            "11:22:41. The next measured reading, 92.15 m3/s at 11:44:01, "
            "crosses Q5 and updates severity; Q5 is not the detection rule. "
            "For an ephemeral stream the rule is instead two consecutive "
            "readings at or above 1 m3/s."
        ),
    },
    {
        "id": "FD2",
        "event": (
            "Nahal Zeelim flood on 1 November 2023, detected at 16:35 before "
            "the first reported wave reached the road at 16:52."
        ),
        "hazard": "flood",
        "latitude": ZEELIM[0],
        "longitude": ZEELIM[1],
        "expect_detected": True,
        "expect_route": "emergency",
        "expect_marker_within_km": 6.0,
        "expect_min_signals": 1,
        "expect_notes": (
            "Nahal Zeelim is ephemeral, so two consecutive readings at or "
            "above 1 m3/s confirm a flood. The 3.835 and 3.375 m3/s readings "
            "at 16:17:54 and 16:35:00 therefore produce an alert at 16:35, "
            "17 minutes before the documented first wave at 16:52. Q2 and "
            "higher return-period thresholds describe severity; they are not "
            "the detection rule here. For a perennial (flowing-baseline) "
            "stream, two consecutive readings at or above Q2 are required."
        ),
    },
]


EXPECTED_BYPRODUCTS: list[dict[str, str]] = []
EXPECTED_SILENCE: list[dict[str, str]] = []


def _gauge(
    station_id: int,
    name_en: str,
    name_he: str,
    lat: float,
    lon: float,
    discharge: float,
    height: float,
    *,
    basin: int | None,
    regime: str,
    thresholds: tuple[float, float, float, float, float, float],
    flow_start: float | None,
) -> dict[str, Any]:
    """One hydrometric reading in the exact shape production persists."""
    q2, q5, q10, q20, q50, q100 = thresholds
    return {
        "stations": [
            {
                "name_en": name_en,
                "name_he": name_he,
                "latitude": lat,
                "longitude": lon,
                "discharge_m3s": discharge,
                "water_height_m": height,
                "drainage_basin_id": basin,
                "source_station_id": station_id,
                "operational_flow_regime": regime,
                "flow_threshold_2y_m3s": q2,
                "flow_threshold_5y_m3s": q5,
                "flow_threshold_status": "complete_thresholds",
                "flow_threshold_10y_m3s": q10,
                "flow_threshold_20y_m3s": q20,
                "flow_threshold_50y_m3s": q50,
                "flow_threshold_100y_m3s": q100,
                "flow_start_water_level_m": flow_start,
            }
        ]
    }


def build_rows(now: datetime) -> list[tuple[str, str, datetime, dict[str, Any]]]:
    """Return the six measured rows, with their historical intervals intact."""
    # Hadera's final seeded reading is five minutes before the demo start.
    # Offsets are measured from the historical 11:44:01 reading.
    hadera_q5 = now - timedelta(minutes=5)
    hadera_rows = (
        (hadera_q5 - timedelta(minutes=34, seconds=16), 66.14, 14.08),
        (hadera_q5 - timedelta(minutes=21, seconds=20), 77.78, 14.22),
        (hadera_q5, 92.15, 14.39),
    )

    # Zeelim's confirming reading is ten minutes before the demo start.
    # Offsets are measured from the historical 16:35:00 reading.
    zeelim_confirmation = now - timedelta(minutes=10)
    zeelim_rows = (
        (zeelim_confirmation - timedelta(minutes=25), 0.0, 9.10),
        (zeelim_confirmation - timedelta(minutes=17, seconds=6), 3.835, 9.59),
        (zeelim_confirmation, 3.375, 9.55),
    )

    rows: list[tuple[str, str, datetime, dict[str, Any]]] = []
    for observed, discharge, height in hadera_rows:
        rows.append(
            (
                HYDROMETRIC_SOURCE,
                HADERA_CELL,
                observed,
                _gauge(
                    254,
                    "HADERA - GAN SHEMU'EL",
                    "חדרה - גן שמואל",
                    *HADERA,
                    discharge,
                    height,
                    basin=None,
                    regime="flowing_baseline",
                    thresholds=HADERA_THRESHOLDS,
                    flow_start=None,
                ),
            )
        )

    for observed, discharge, height in zeelim_rows:
        rows.append(
            (
                HYDROMETRIC_SOURCE,
                ZEELIM_CELL,
                observed,
                _gauge(
                    349,
                    "TZE'ELIM",
                    "צאלים",
                    *ZEELIM,
                    discharge,
                    height,
                    basin=97,
                    regime="ephemeral",
                    thresholds=ZEELIM_THRESHOLDS,
                    flow_start=0.06,
                ),
            )
        )

    return rows


INSERT = text(
    'INSERT INTO "{schema}".observations '
    "(source, cell_id, location, observed_at, ingested_at, payload) "
    "VALUES (:source, :cell_id, NULL, :observed_at, :ingested_at, "
    "CAST(:payload AS jsonb))"
)


def seed(schema: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Write the flood observations into the isolated demo schema."""
    moment = now or datetime.now(timezone.utc)
    rows = build_rows(moment)
    statement = text(str(INSERT).replace("{schema}", schema))

    with Session() as session:
        for source, cell_id, observed_at, payload in rows:
            session.execute(
                statement,
                {
                    "source": source,
                    "cell_id": cell_id,
                    "observed_at": observed_at,
                    "ingested_at": moment,
                    "payload": json.dumps(payload, ensure_ascii=False),
                },
            )
        session.commit()

    return {
        "observations": len(rows),
        "by_source": {HYDROMETRIC_SOURCE: len(rows)},
        "seeded_at": moment.isoformat(),
        "expectations": {
            "events": GROUND_TRUTH,
            "silence": EXPECTED_SILENCE,
        },
    }


__all__ = [
    "GROUND_TRUTH",
    "EXPECTED_BYPRODUCTS",
    "EXPECTED_SILENCE",
    "build_rows",
    "seed",
]
