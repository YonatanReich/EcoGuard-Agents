"""Optional read-only IMS wind adapter smoke test.

Requires ``IMS_API_TOKEN`` in the process environment. The credential is only
sent in the Authorization header and is never printed or serialized.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.air_pollution_anomaly_schemas import GeographicCoordinate
from services.air_pollution_transport_geometry import geodesic_distance_m
from services.ims_wind_evidence_service import (
    IMS_FIXED_STANDARD_TIME,
    IMSWindEvidenceError,
    IMSWindEvidenceService,
)
from services.ims_wind_observation_client import (
    IMSHTTPDiagnostic,
    IMSWindObservationClient,
    IMSWindObservationError,
)


def _aware_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a UTC offset")
    return parsed


def _print_http_diagnostic(diagnostic: IMSHTTPDiagnostic) -> None:
    print(json.dumps({"ims_http": diagnostic.as_safe_dict()}, sort_keys=True))


def _error_category(error: Exception) -> str:
    if isinstance(error, (IMSWindObservationError, IMSWindEvidenceError)):
        return error.category
    return "validation_error"


def _probe(call: Callable[[], object]) -> object | None:
    try:
        return call()
    except (IMSWindObservationError, ValueError, TypeError) as error:
        print(
            json.dumps(
                {"ims_probe": "failed", "error_category": _error_category(error)},
                sort_keys=True,
            )
        )
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only IMS wind evidence smoke test")
    parser.add_argument("--latitude", required=True, type=float)
    parser.add_argument("--longitude", required=True, type=float)
    parser.add_argument(
        "--anomaly-time",
        type=_aware_timestamp,
        default=None,
        help="ISO-8601 anomaly time; defaults to current UTC time",
    )
    parser.add_argument("--maximum-age-minutes", type=float, default=60.0)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument(
        "--debug-http",
        action="store_true",
        help="show sanitized status/shape diagnostics and probe IMS endpoint forms",
    )
    args = parser.parse_args()

    client = IMSWindObservationClient(
        timeout=args.timeout_seconds,
        diagnostic_callback=_print_http_diagnostic if args.debug_http else None,
    )
    service = IMSWindEvidenceService(client)
    origin = GeographicCoordinate(
        latitude=args.latitude,
        longitude=args.longitude,
    )
    anomaly_time = args.anomaly_time or datetime.now(timezone.utc)
    maximum_age_seconds = args.maximum_age_minutes * 60.0

    if args.debug_http:
        station_payload = _probe(client.get_stations)
        if station_payload is None:
            return 1
        try:
            stations = service.discover_stations(station_payload)
        except (IMSWindObservationError, ValueError, TypeError) as error:
            print(
                json.dumps(
                    {
                        "ims_probe": "station_discovery_failed",
                        "error_category": _error_category(error),
                    },
                    sort_keys=True,
                )
            )
            return 1
        wind_stations = [station for station in stations if station.wind_capable]
        if not wind_stations:
            print(
                json.dumps(
                    {
                        "ims_probe": "station_discovery_failed",
                        "error_category": "no_active_wind_capable_station",
                    },
                    sort_keys=True,
                )
            )
            return 1
        probe_station = min(
            wind_stations,
            key=lambda station: (
                geodesic_distance_m(origin, station.coordinates),
                station.station_id,
            ),
        )
        print(
            json.dumps(
                {
                    "ims_probe_station": {
                        "station_id": probe_station.station_id,
                        "station_name": probe_station.name,
                    }
                },
                sort_keys=True,
            )
        )
        _probe(lambda: client.get_station(probe_station.station_id))
        _probe(lambda: client.get_station_data_latest(probe_station.station_id))
        start_wall = (
            anomaly_time.astimezone(timezone.utc)
            - timedelta(seconds=maximum_age_seconds)
        ).astimezone(IMS_FIXED_STANDARD_TIME)
        end_wall = anomaly_time.astimezone(IMS_FIXED_STANDARD_TIME)
        _probe(
            lambda: client.get_station_data_daily(
                probe_station.station_id, end_wall.date()
            )
        )
        _probe(
            lambda: client.get_station_data_range(
                probe_station.station_id,
                start_wall.date(),
                end_wall.date(),
            )
        )

    try:
        selection = service.select_wind_evidence(
            analysis_coordinates=origin,
            anomaly_observed_at=anomaly_time,
            maximum_observation_age_seconds=maximum_age_seconds,
        )
    except (IMSWindObservationError, IMSWindEvidenceError, ValueError, TypeError) as error:
        failure: dict[str, object] = {
            "smoke_test_status": "failed",
            "error_category": _error_category(error),
        }
        if isinstance(error, IMSWindEvidenceError) and error.diagnostics:
            failure["selection_diagnostics"] = error.diagnostics
        print(
            json.dumps(failure, sort_keys=True)
        )
        return 1
    evidence = selection.wind_evidence
    output = {
        "provider": evidence.provider,
        "station_id": evidence.provider_location_id,
        "station_name": evidence.provider_location_name,
        "station_coordinates": evidence.actual_provider_coordinates.model_dump(),
        "station_distance_m": selection.station_distance_m,
        "raw_provider_timestamp": evidence.raw_provider_timestamp,
        "normalized_observed_at_utc": evidence.wind_observed_at.isoformat()
        if evidence.wind_observed_at
        else None,
        "wind_from_direction_deg": evidence.wind_from_direction_deg,
        "wind_speed_mps": evidence.wind_speed_mps,
        "direction_stddev_deg": evidence.direction_stddev_deg,
        "gust_from_direction_deg": evidence.gust_from_direction_deg,
        "gust_speed_mps": evidence.gust_speed_mps,
        "optional_fields_available": {
            "STDwd": evidence.direction_stddev_deg is not None,
            "WDmax": evidence.gust_from_direction_deg is not None,
            "WSmax": evidence.gust_speed_mps is not None,
        },
        "time_offset_from_anomaly_seconds": evidence.time_offset_from_anomaly_seconds,
        "selection_rationale": selection.selection_rationale,
        "selection_diagnostics": selection.diagnostics.model_dump(mode="json"),
        "eligible_alternatives": [
            item.model_dump(mode="json") for item in selection.eligible_alternatives
        ],
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
