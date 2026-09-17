"""Select and reserve nearby stations requested by fire response plans."""

import math
from datetime import datetime, timezone

from ecoguard.database.repositories.fire_stations import fire_stations_geojson
from ecoguard.database.repositories.mda_stations import mda_stations_geojson
from ecoguard.database.repositories.police_stations import police_stations_geojson
from ecoguard.database.repositories.resource_allocations import (
    ResourceAllocationRepository,
)

# Temporary station counts until an operational source can provide real
# vehicle quantities. These numbers represent stations, not vehicles.
STATIONS_REQUIRED_BY_RISK = {
    "low": {
        "fire_department": 1,
        "police": 1,
        "medical_services": 1,
    },
    "medium": {
        "fire_department": 2,
        "police": 1,
        "medical_services": 1,
    },
    "high": {
        "fire_department": 3,
        "police": 2,
        "medical_services": 2,
    },
    "critical": {
        "fire_department": 4,
        "police": 2,
        "medical_services": 2,
    },
}

TIMEFRAME_PRIORITY = {
    "ongoing": 0,
    "within_6_hours": 1,
    "within_1_hour": 2,
    "immediate": 3,
}

STATION_TYPES = {
    "fire_department": ("fire_station", "fire_stations"),
    "police": ("police_station", "police_stations"),
    "medical_services": ("mda_station", "mda_stations"),
}


def _default_station_readers():
    """Return readers for the emergency-station tables already in the DB."""

    return {
        "fire_department": fire_stations_geojson,
        "police": police_stations_geojson,
        "medical_services": mda_stations_geojson,
    }


class ResourceAllocationAgent:

    def __init__(self, station_readers=None, allocation_repository=None):
        self.station_readers = (
            _default_station_readers()
            if station_readers is None
            else station_readers
        )
        self.allocation_repository = (
            allocation_repository or ResourceAllocationRepository()
        )
        self._station_catalogs = {}
        self._stations_by_key = {}
        self._station_catalog_errors = {}

        # Station rosters are static reference data. Assignment state remains
        # in PostgreSQL so it is shared by every allocator process.
        for recommended_unit, (station_type, _) in STATION_TYPES.items():
            stations, error = self._load_station_catalog(
                recommended_unit, station_type
            )
            self._station_catalogs[recommended_unit] = stations
            if error is not None:
                self._station_catalog_errors[recommended_unit] = error
            for station in stations:
                self._stations_by_key[station["resource_key"]] = station

    @staticmethod
    def _coordinates(location):
        """Validate a location and return its coordinates."""
        if not isinstance(location, dict):
            raise ValueError("location must be an object")

        latitude = location.get("latitude")
        longitude = location.get("longitude")

        for value in (latitude, longitude):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
            ):
                raise ValueError("location must contain valid coordinates")

        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("coordinates are outside their valid ranges")

        return float(latitude), float(longitude)

    @staticmethod
    def _haversine_distance(lat1, lon1, lat2, lon2):
        """Calculate the distance between two coordinates in kilometers."""
        lon1, lat1, lon2, lat2 = map(
            math.radians, (lon1, lat1, lon2, lat2)
        )
        longitude_delta = lon2 - lon1
        latitude_delta = lat2 - lat1
        value = (
            math.sin(latitude_delta / 2) ** 2
            + math.cos(lat1)
            * math.cos(lat2)
            * math.sin(longitude_delta / 2) ** 2
        )
        return 6371 * 2 * math.asin(math.sqrt(value))

    def _rank_stations(self, stations, event_lat, event_lon):
        """Return valid, unique stations sorted by straight-line distance."""
        unique = {}

        for source in stations:
            try:
                station_lat, station_lon = self._coordinates(source)
            except ValueError:
                continue

            distance = self._haversine_distance(
                event_lat, event_lon, station_lat, station_lon
            )
            station = source.copy()
            station["distance_km"] = distance

            resource_key = station["resource_key"]
            existing = unique.get(resource_key)
            if existing is None or distance < existing["distance_km"]:
                unique[resource_key] = station

        return sorted(unique.values(), key=lambda item: item["distance_km"])

    @staticmethod
    def _resource_key(recommended_unit, properties):
        """Identify every station by its stable primary key in the DB."""
        if recommended_unit not in STATION_TYPES:
            raise ValueError(f"unsupported resource type: {recommended_unit}")

        database_id = properties.get("database_id")
        if (
            not isinstance(database_id, int)
            or isinstance(database_id, bool)
            or database_id <= 0
        ):
            raise ValueError(f"{recommended_unit} database_id is missing")
        return recommended_unit, database_id

    @staticmethod
    def _utc(value=None):
        """Normalize a datetime or ISO string to an aware UTC datetime."""
        if value is None:
            return datetime.now(timezone.utc)
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("queued_at must be an ISO timestamp with a UTC offset")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _planning_status(response_plan):
        return str((response_plan.get("metadata") or {}).get("planning_status") or "")

    @staticmethod
    def _urgency(response_plan):
        """Use the most urgent planner action only as a priority tie-breaker."""
        return max(
            (
                TIMEFRAME_PRIORITY.get(str(action.get("timeframe") or ""), -1)
                for action in response_plan.get("response_actions") or []
                if isinstance(action, dict)
            ),
            default=-1,
        )

    @staticmethod
    def _required_station_count(risk_level, recommended_unit):
        return STATIONS_REQUIRED_BY_RISK[risk_level].get(recommended_unit, 1)

    def _prepare_batch_request(self, item, now):
        """Validate one Planner response before allocation starts."""
        if not isinstance(item, dict):
            raise ValueError("allocation request must be an object")

        # The Coordinator wrapper adds its canonical incident identity and
        # queue time without changing the Planner response.
        response_plan = item.get("response_plan", item)
        if not isinstance(response_plan, dict):
            raise ValueError("response_plan must be an object")

        # The Coordinator owns the incident lifecycle. Planner event_id is
        # only a fallback for callers that pass a standalone plan.
        incident_id = str(
            item.get("incident_id") or response_plan.get("event_id") or ""
        ).strip()
        if not incident_id:
            raise ValueError("incident_id is required")

        planning_status = self._planning_status(response_plan)
        if planning_status not in {"success", "failed", "skipped"}:
            raise ValueError("response plan has an invalid planning_status")

        if planning_status != "success":
            metadata = response_plan.get("metadata") or {}
            planner_error = response_plan.get("error")
            return {
                "terminal": {
                    "incident_id": incident_id,
                    "event_id": response_plan.get("event_id"),
                    "status": planning_status,
                    "reason": f"response_plan_{planning_status}",
                    "planner_status": planning_status,
                    "planner_reason": metadata.get("reason"),
                    "planner_error": planner_error,
                    "allocated_units": {},
                    "requirements": {},
                    "shortages": {},
                    "unsupported_units": [],
                    "errors": [planner_error] if planner_error else [],
                }
            }

        responding_to = response_plan.get("responding_to") or {}
        if responding_to.get("risk_semantics") != "detected_event_operational_risk":
            raise ValueError("response plan does not contain operational risk")

        risk_score = responding_to.get("risk_score")
        if (
            not isinstance(risk_score, (int, float))
            or isinstance(risk_score, bool)
            or not math.isfinite(risk_score)
            or not 0 <= risk_score <= 100
        ):
            raise ValueError("operational risk score must be between 0 and 100")

        risk_level = str(responding_to.get("risk_level") or "").lower()
        if risk_level not in STATIONS_REQUIRED_BY_RISK:
            raise ValueError("operational risk level is unavailable")

        metadata = response_plan.get("metadata") or {}
        queued_at = self._utc(
            item.get("queued_at") or metadata.get("timestamp") or now
        )
        waited_seconds = max(0, (now - queued_at).total_seconds())
        aging_bonus = int(waited_seconds // 300)

        return {
            "incident_id": incident_id,
            "response_plan": response_plan,
            "risk_score": float(risk_score),
            "risk_level": risk_level,
            "queued_at": queued_at,
            "allocation_time": now,
            "urgency": self._urgency(response_plan),
            # Aging adds one point every five minutes so old requests progress.
            "effective_priority": float(risk_score) + aging_bonus,
        }

    @staticmethod
    def _priority_key(request):
        return (
            -request["effective_priority"],
            -request["risk_score"],
            -request["urgency"],
            request["queued_at"],
            request["incident_id"],
        )

    @staticmethod
    def _stations_from_geojson(payload, recommended_unit, station_type):
        """Normalize one DB station catalog and ignore unlocated rows."""
        if not isinstance(payload, dict) or not isinstance(
            payload.get("features"), list
        ):
            raise ValueError("station catalog must be a GeoJSON FeatureCollection")

        stations = []
        for feature in payload["features"]:
            if not isinstance(feature, dict):
                continue
            geometry = feature.get("geometry") or {}
            coordinates = geometry.get("coordinates") or []
            if geometry.get("type") != "Point" or len(coordinates) < 2:
                continue

            properties = feature.get("properties") or {}
            if not isinstance(properties, dict):
                continue
            try:
                resource_key = ResourceAllocationAgent._resource_key(
                    recommended_unit, properties
                )
            except ValueError:
                continue
            station = {
                **properties,
                "latitude": coordinates[1],
                "longitude": coordinates[0],
                "unit_type": station_type,
                "recommended_unit": recommended_unit,
                "resource_key": resource_key,
            }
            try:
                ResourceAllocationAgent._coordinates(station)
            except ValueError:
                continue
            stations.append(station)

        return stations

    def _load_station_catalog(self, recommended_unit, station_type):
        """Read all located stations for one Planner unit type."""
        reader = self.station_readers.get(recommended_unit)
        if reader is None:
            return [], "station catalog reader is unavailable"
        try:
            return self._stations_from_geojson(
                reader(), recommended_unit, station_type
            ), None
        except Exception as error:
            return [], str(error)

    def _allocation_view(self, allocation, status="assigned"):
        """Combine a durable allocation with its cached station details."""
        station_key = (
            allocation["recommended_unit"],
            allocation["station_id"],
        )
        station = self._stations_by_key.get(station_key, {})
        result = {
            **station,
            "database_id": allocation["station_id"],
            "recommended_unit": allocation["recommended_unit"],
            "resource_key": station_key,
            "allocation_id": allocation.get("id"),
            "assigned_incident_id": allocation["incident_id"],
            "distance_km": allocation["distance_km"],
            "risk_score": allocation.get("risk_score"),
            "risk_level": allocation.get("risk_level"),
            "allocation_status": status,
            "available_for_ecoguard": status == "released",
            "real_world_availability": "unknown",
            "selection_reason": "nearest_available_station",
        }
        for field in ("allocated_at", "released_at"):
            value = allocation.get(field)
            result[field] = (
                value.isoformat() if isinstance(value, datetime) else value
            )
        if allocation.get("release_reason") is not None:
            result["release_reason"] = allocation["release_reason"]
        return result

    def _claim_stations(
        self,
        incident_id,
        recommended_unit,
        candidates,
        required_count,
        risk_score,
        risk_level,
        allocated_at,
    ):
        """Atomically claim stations through the allocation repository."""
        allocations = self.allocation_repository.claim_stations(
            incident_id=incident_id,
            recommended_unit=recommended_unit,
            candidates=candidates,
            required_count=required_count,
            risk_score=risk_score,
            risk_level=risk_level,
            allocated_at=allocated_at,
        )
        return sorted(
            (self._allocation_view(allocation) for allocation in allocations),
            key=lambda station: station["distance_km"],
        )

    def _allocate_batch_request(self, request):
        response_plan = request["response_plan"]
        event_lat, event_lon = self._coordinates(response_plan.get("location"))
        recommended_units = list(
            dict.fromkeys(response_plan.get("recommended_units") or [])
        )

        result = {
            "incident_id": request["incident_id"],
            "event_id": response_plan.get("event_id"),
            "status": "fulfilled",
            "risk_score": request["risk_score"],
            "risk_level": request["risk_level"],
            "effective_priority": request["effective_priority"],
            "queued_at": request["queued_at"].isoformat(),
            "allocation_needed": bool(recommended_units),
            "allocated_units": {},
            "requirements": {},
            "shortages": {},
            "unsupported_units": [],
            "errors": [],
        }

        if not recommended_units:
            result["reason"] = "no_resources_required"
            return result

        for recommended_unit in recommended_units:
            required_count = self._required_station_count(
                request["risk_level"], recommended_unit
            )
            mapping = STATION_TYPES.get(recommended_unit)
            if mapping is None:
                result["unsupported_units"].append(recommended_unit)
                result["requirements"][recommended_unit] = {
                    "requested": required_count,
                    "assigned": 0,
                    "shortfall": required_count,
                }
                continue

            station_type, output_key = mapping
            catalog_error = self._station_catalog_errors.get(recommended_unit)
            stations = self._station_catalogs.get(recommended_unit, [])
            # Every located station is eligible, including coarse points.
            candidates = self._rank_stations(
                stations,
                event_lat,
                event_lon,
            )

            try:
                assigned = self._claim_stations(
                    request["incident_id"],
                    recommended_unit,
                    candidates,
                    required_count,
                    request["risk_score"],
                    request["risk_level"],
                    request["allocation_time"],
                )
            except Exception as error:
                assigned = []
                result["errors"].append(
                    {
                        "station_type": station_type,
                        "reason": "allocation_persistence_failed",
                        "message": str(error),
                    }
                )
            result["allocated_units"][output_key] = assigned

            shortfall = max(0, required_count - len(assigned))
            result["requirements"][recommended_unit] = {
                "requested": required_count,
                "assigned": len(assigned),
                "shortfall": shortfall,
            }
            if shortfall:
                result["shortages"][station_type] = shortfall
            if catalog_error is not None:
                result["errors"].append(
                    {
                        "station_type": station_type,
                        "reason": "station_catalog_failed",
                        "message": catalog_error,
                    }
                )

        if result["shortages"] or result["unsupported_units"] or result["errors"]:
            result["status"] = "partial"
        return result

    def allocate_batch(self, requests, now=None):
        """Allocate stations to a priority-sorted batch of response plans."""
        current_time = self._utc(now)
        prepared = []
        terminal_results = []

        for request in requests or []:
            try:
                item = self._prepare_batch_request(request, current_time)
            except (TypeError, ValueError) as error:
                response_plan = (
                    request.get("response_plan", request)
                    if isinstance(request, dict)
                    else {}
                )
                if not isinstance(response_plan, dict):
                    response_plan = {}
                incident_id = str(
                    (
                        request.get("incident_id")
                        if isinstance(request, dict)
                        else None
                    )
                    or response_plan.get("event_id")
                    or "unknown"
                )
                terminal_results.append(
                    {
                        "incident_id": incident_id,
                        "status": "failed",
                        "reason": "invalid_allocation_request",
                        "allocated_units": {},
                        "requirements": {},
                        "shortages": {},
                        "unsupported_units": [],
                        "errors": [str(error)],
                    }
                )
                continue

            if "terminal" in item:
                terminal_results.append(item["terminal"])
            else:
                prepared.append(item)

        prepared.sort(key=self._priority_key)
        allocated = [self._allocate_batch_request(item) for item in prepared]
        return [*allocated, *terminal_results]

    def release_incident(
        self,
        incident_id,
        *,
        released_at=None,
        reason="incident_closed",
    ):
        """Release every station assigned to one incident; safe to call twice."""
        allocations = self.allocation_repository.release_incident(
            str(incident_id),
            released_at=self._utc(released_at),
            reason=reason,
        )
        released = [
            self._allocation_view(allocation, status="released")
            for allocation in allocations
        ]
        return sorted(released, key=lambda station: station["distance_km"])

    def active_allocations(self):
        """Return a read-only snapshot of durable active allocations."""
        grouped = {}
        for allocation in self.allocation_repository.active_allocations():
            grouped.setdefault(allocation["incident_id"], []).append(
                self._allocation_view(allocation)
            )
        return {
            incident_id: sorted(
                allocations,
                key=lambda station: station["distance_km"],
            )
            for incident_id, allocations in grouped.items()
        }
