"""Select and reserve nearby stations requested by fire response plans."""

import math
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from ecoguard.database.repositories.fire_stations import fire_stations_geojson
from ecoguard.database.repositories.mda_stations import mda_stations_geojson
from ecoguard.database.repositories.police_stations import police_stations_geojson
from ecoguard.database.repositories.resource_allocations import (
    ResourceAllocationRepository,
)
from ecoguard.database.repositories.towns import responsible_police_stations
from ecoguard.resource_allocator.mapbox_client import MapboxClient, RoutingError

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

    def __init__(
        self,
        station_readers=None,
        routing_client=None,
        allocation_repository=None,
        police_responsibility_reader=None,
    ):
        self.station_readers = (
            _default_station_readers()
            if station_readers is None
            else station_readers
        )
        self.routing_client = routing_client or MapboxClient()
        self.allocation_repository = (
            allocation_repository or ResourceAllocationRepository()
        )
        self.police_responsibility_reader = (
            police_responsibility_reader or responsible_police_stations
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
            station["straight_line_distance_km"] = distance

            resource_key = station["resource_key"]
            existing = unique.get(resource_key)
            if (
                existing is None
                or distance < existing["straight_line_distance_km"]
            ):
                unique[resource_key] = station

        return sorted(
            unique.values(),
            key=lambda item: item["straight_line_distance_km"],
        )

    def _available_candidates(
        self,
        candidates,
        incident_id,
        recommended_unit,
    ):
        """Exclude stations currently claimed by another incident in the DB."""
        if recommended_unit == "police":
            # A police allocation assigns the responsible station, not one of
            # its vehicles. The station may receive several incidents.
            return candidates

        occupied = {
            allocation["station_id"]
            for allocation in self.allocation_repository.active_allocations()
            if allocation["recommended_unit"] == recommended_unit
            and allocation["incident_id"] != incident_id
        }
        return [
            candidate
            for candidate in candidates
            if candidate["database_id"] not in occupied
        ]

    def _rank_stations_by_road(
        self,
        stations,
        event_location,
        required_count,
        selection_reason="shortest_road_travel_time",
    ):
        """Search nearby batches until enough road-reachable stations exist."""
        batch_size = getattr(self.routing_client, "matrix_max_sources", 9)
        if not isinstance(batch_size, int) or batch_size < 1:
            batch_size = 9
        ranked = []
        road_access = None

        # Haversine order is only used to avoid paid requests for very distant
        # stations after a nearby batch can already fulfil the requirement.
        for start in range(0, len(stations), batch_size):
            batch = stations[start : start + batch_size]
            routing_result = self.routing_client.travel_metrics(
                batch,
                event_location,
            )
            metrics = routing_result["metrics"]
            if len(metrics) != len(batch):
                raise RoutingError("routing table does not match station batch")
            if road_access is None:
                road_access = routing_result.get("road_access")

            for station, metric in zip(batch, metrics):
                if metric is None:
                    continue
                candidate = station.copy()
                candidate["_routing_metric"] = metric
                candidate["selection_reason"] = selection_reason
                ranked.append(candidate)

            if len(ranked) >= required_count:
                break

        if stations and not ranked:
            raise RoutingError("Mapbox found no road route from any station")

        return (
            sorted(
                ranked,
                key=lambda station: (
                    station["_routing_metric"]["duration_s"],
                    station["_routing_metric"]["distance_m"],
                    station["straight_line_distance_km"],
                ),
            ),
            road_access,
        )

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
        if recommended_unit == "police":
            # Severity is sent to the responsible station; the station decides
            # how many internal units it dispatches.
            return 1
        return STATIONS_REQUIRED_BY_RISK[risk_level].get(recommended_unit, 1)

    def _police_candidates_for_event(self, stations, event_location):
        """Prefer the event town's responsible police stations."""

        fallback = [
            station
            for station in stations
            if (station.get("kind") or "station") == "station"
        ]
        try:
            responsibility = self.police_responsibility_reader(
                latitude=event_location["latitude"],
                longitude=event_location["longitude"],
            )
        except Exception as error:
            return (
                fallback,
                {
                    "status": "fallback",
                    "reason": "responsibility_lookup_unavailable",
                    "town_id": None,
                    "town_name": None,
                    "responsible_station_ids": [],
                },
                str(error),
            )

        if responsibility is not None:
            responsible_ids = set(
                responsibility.get("police_station_ids") or []
            )
            responsible = [
                station
                for station in stations
                if station["database_id"] in responsible_ids
            ]
            if responsible:
                selection_reason = (
                    "responsible_for_area"
                    if len(responsible) == 1
                    else "nearest_responsible_station"
                )
                return (
                    responsible,
                    {
                        "status": "matched",
                        "reason": selection_reason,
                        "town_id": responsibility.get("town_id"),
                        "town_name": responsibility.get("town_name"),
                        "responsible_station_ids": sorted(responsible_ids),
                    },
                    None,
                )

            fallback_reason = (
                "town_has_no_mapped_police_station"
                if not responsible_ids
                else "responsible_station_not_in_catalog"
            )
            return (
                fallback,
                {
                    "status": "fallback",
                    "reason": fallback_reason,
                    "town_id": responsibility.get("town_id"),
                    "town_name": responsibility.get("town_name"),
                    "responsible_station_ids": sorted(responsible_ids),
                },
                None,
            )

        return (
            fallback,
            {
                "status": "fallback",
                "reason": "event_outside_town",
                "town_id": None,
                "town_name": None,
                "responsible_station_ids": [],
            },
            None,
        )

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
            "allocation_scope": "station",
            "resource_key": station_key,
            "allocation_id": allocation.get("id"),
            "assigned_incident_id": allocation["incident_id"],
            "distance_km": allocation["distance_km"],
            "risk_score": allocation.get("risk_score"),
            "risk_level": allocation.get("risk_level"),
            "severity": allocation.get("risk_level"),
            "allocation_status": status,
            "available_for_ecoguard": (
                allocation["recommended_unit"] == "police"
                or status == "released"
            ),
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
        """Atomically claim stations through the shared DB repository."""
        allocations = self.allocation_repository.claim_stations(
            incident_id=incident_id,
            recommended_unit=recommended_unit,
            candidates=candidates,
            required_count=required_count,
            risk_score=risk_score,
            risk_level=risk_level,
            allocated_at=allocated_at,
        )
        return [self._allocation_view(allocation) for allocation in allocations]

    def _unavailable_route(self, metric, message):
        metric = metric or {}
        return {
            "status": "unavailable",
            "provider": getattr(self.routing_client, "provider", "mapbox"),
            "profile": getattr(
                self.routing_client,
                "profile",
                "mapbox/driving-traffic",
            ),
            "distance_m": metric.get("distance_m"),
            "duration_s": metric.get("duration_s"),
            "estimated_arrival_at": None,
            "geometry": None,
            "road_access_verified": False,
            "requires_field_access_confirmation": True,
            "offroad_segment": None,
            "steps_he": [],
            "error": message,
        }

    def _enrich_routes(
        self,
        assigned,
        candidates,
        event_location,
        allocation_time,
        routing_failure,
    ):
        """Fetch full routes only after the DB has accepted the station claim."""
        errors = []
        candidates_by_id = {
            candidate["database_id"]: candidate for candidate in candidates
        }
        enriched = []

        for allocation in assigned:
            station = deepcopy(allocation)
            candidate = candidates_by_id.get(station["database_id"], station)
            metric = deepcopy(candidate.get("_routing_metric"))

            if metric is None:
                route = self._unavailable_route(
                    metric,
                    routing_failure or "road route is unavailable",
                )
            else:
                try:
                    route = self.routing_client.route(
                        candidate,
                        event_location,
                    )
                    route["estimated_arrival_at"] = (
                        allocation_time
                        + timedelta(seconds=route["duration_s"])
                    ).isoformat()
                except RoutingError as error:
                    route = self._unavailable_route(metric, str(error))
                    errors.append(
                        {
                            "station_key": station["resource_key"],
                            "reason": "route_details_unavailable",
                            "message": str(error),
                        }
                    )
            station["straight_line_distance_km"] = candidate.get(
                "straight_line_distance_km"
            )
            station["distance_km"] = (
                route["distance_m"] / 1000
                if route.get("distance_m") is not None
                else station["distance_km"]
            )
            station["route"] = route
            station["selection_reason"] = candidate.get(
                "selection_reason",
                "shortest_road_travel_time",
            )
            enriched.append(station)

        return sorted(enriched, key=self._allocation_sort_key), errors

    @staticmethod
    def _allocation_sort_key(station):
        route = station.get("route") or {}
        duration = route.get("duration_s")
        distance = station.get("distance_km")
        return (
            duration if isinstance(duration, (int, float)) else math.inf,
            distance if isinstance(distance, (int, float)) else math.inf,
        )

    def _allocate_batch_request(self, request):
        response_plan = request["response_plan"]
        event_lat, event_lon = self._coordinates(response_plan.get("location"))
        event_location = {
            "latitude": event_lat,
            "longitude": event_lon,
        }
        recommended_units = list(
            dict.fromkeys(response_plan.get("recommended_units") or [])
        )

        result = {
            "incident_id": request["incident_id"],
            "event_id": response_plan.get("event_id"),
            "status": "fulfilled",
            "risk_score": request["risk_score"],
            "risk_level": request["risk_level"],
            "severity": request["risk_level"],
            "effective_priority": request["effective_priority"],
            "queued_at": request["queued_at"].isoformat(),
            "allocation_needed": bool(recommended_units),
            "allocation_scope": "station",
            "allocated_units": {},
            "requirements": {},
            "shortages": {},
            "unsupported_units": [],
            "errors": [],
        }

        if not recommended_units:
            result["reason"] = "no_resources_required"
            return result

        result["road_access"] = None

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
            unit_routing_failure = None
            catalog_error = self._station_catalog_errors.get(recommended_unit)
            stations = self._station_catalogs.get(recommended_unit, [])
            selection_reason = "shortest_road_travel_time"
            if recommended_unit == "police":
                stations, responsibility, responsibility_error = (
                    self._police_candidates_for_event(
                        stations,
                        event_location,
                    )
                )
                result["police_responsibility"] = responsibility
                selection_reason = (
                    responsibility["reason"]
                    if responsibility["status"] == "matched"
                    else "nearest_police_station_fallback"
                )
                if responsibility_error is not None:
                    result["errors"].append(
                        {
                            "station_type": station_type,
                            "reason": "police_responsibility_lookup_failed",
                            "message": responsibility_error,
                        }
                    )
            # Every located station is eligible, including coarse points.
            candidates = self._rank_stations(
                stations,
                event_lat,
                event_lon,
            )
            try:
                candidates = self._available_candidates(
                    candidates,
                    request["incident_id"],
                    recommended_unit,
                )
                candidates, road_access = self._rank_stations_by_road(
                    candidates,
                    event_location,
                    required_count,
                    selection_reason,
                )
                if result["road_access"] is None and road_access is not None:
                    result["road_access"] = road_access
            except RoutingError as error:
                unit_routing_failure = str(error)
                result["errors"].append(
                    {
                        "station_type": station_type,
                        "reason": "road_ranking_unavailable",
                        "message": unit_routing_failure,
                    }
                )
                candidates = [
                    {
                        **candidate,
                        "distance_km": candidate["straight_line_distance_km"],
                        "_routing_metric": None,
                        "selection_reason": (
                            "straight_line_fallback"
                            if selection_reason
                            == "shortest_road_travel_time"
                            else f"{selection_reason}_straight_line_fallback"
                        ),
                    }
                    for candidate in candidates
                ]

            for candidate in candidates:
                metric = candidate.get("_routing_metric") or {}
                candidate["distance_km"] = (
                    metric["distance_m"] / 1000
                    if metric.get("distance_m") is not None
                    else candidate["straight_line_distance_km"]
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
            else:
                assigned, route_errors = self._enrich_routes(
                    assigned,
                    candidates,
                    event_location,
                    request["allocation_time"],
                    unit_routing_failure,
                )
                result["errors"].extend(route_errors)
            result["allocated_units"][output_key] = assigned
            if result["road_access"] is None:
                for station in assigned:
                    route = station.get("route") or {}
                    if route.get("destination"):
                        result["road_access"] = route["destination"]
                        break

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

        route_statuses = [
            station["route"]["status"]
            for stations in result["allocated_units"].values()
            for station in stations
            if station.get("route")
        ]
        if route_statuses and all(
            status == "unavailable" for status in route_statuses
        ):
            result["routing_status"] = "unavailable"
        elif "unavailable" in route_statuses:
            result["routing_status"] = "partial"
        elif "partial_offroad" in route_statuses:
            result["routing_status"] = "partial_offroad"
        elif not route_statuses:
            result["routing_status"] = "not_available"
        else:
            result["routing_status"] = "complete"

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
