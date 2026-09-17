"""Select and reserve nearby stations requested by fire response plans."""

import math
import threading
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from ecoguard.database.repositories.fire_stations import fire_stations_geojson
from ecoguard.database.repositories.mda_stations import mda_stations_geojson
from ecoguard.database.repositories.police_stations import police_stations_geojson
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

    def __init__(self, station_readers=None, routing_client=None):
        self.station_readers = (_default_station_readers() if station_readers is None else station_readers )
        self.routing_client = routing_client or MapboxClient()
        self._allocation_lock = threading.Lock()
        self._station_catalogs = {}
        self._stations_by_key = {}
        self._station_catalog_errors = {}
        self._incident_station_keys = {}

        # Station rosters are static reference data. Load them once and keep
        # EcoGuard's assignment state on the in-memory station records.
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

    def _available_candidates(self, candidates):
        """Return a snapshot of stations that EcoGuard has not assigned."""
        with self._allocation_lock:
            return [
                candidate
                for candidate in candidates
                if self._stations_by_key[candidate["resource_key"]][
                    "assigned_incident_id"
                ]
                is None
            ]

    def _rank_stations_by_road(
        self,
        stations,
        event_location,
        required_count,
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
                candidate["selection_reason"] = "shortest_road_travel_time"
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
        """Use identities already protected by unique constraints in the DB."""
        if recommended_unit == "fire_department":
            district = str(properties.get("district") or "").strip()
            name = str(properties.get("name") or "").strip()
            if not district or not name:
                raise ValueError("fire station identity is incomplete")
            return recommended_unit, district, name

        station_id = properties.get("station_id")
        if station_id is None:
            raise ValueError(f"{recommended_unit} station_id is missing")
        return recommended_unit, str(station_id)

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
                "assigned_incident_id": None,
                "_assigned_straight_line_distance_km": None,
                "_assigned_routing_metric": None,
                "_assigned_route": None,
                "_assigned_selection_reason": None,
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

    @staticmethod
    def _allocation_view(station):
        """Return station data without exposing mutable catalog internals."""
        result = {
            key: value
            for key, value in station.items()
            if not key.startswith("_assigned_")
        }
        straight_line_distance = station.get(
            "_assigned_straight_line_distance_km"
        )
        routing_metric = station.get("_assigned_routing_metric") or {}
        route = deepcopy(station.get("_assigned_route"))

        result["straight_line_distance_km"] = straight_line_distance
        result["distance_km"] = (
            routing_metric["distance_m"] / 1000
            if routing_metric.get("distance_m") is not None
            else straight_line_distance
        )
        result["route"] = route
        result["allocation_status"] = "assigned"
        result["available_for_ecoguard"] = False
        result["real_world_availability"] = "unknown"
        result["selection_reason"] = station.get(
            "_assigned_selection_reason"
        )
        return result

    @staticmethod
    def _allocation_sort_key(station):
        route = station.get("route") or {}
        duration = route.get("duration_s")
        distance = station.get("distance_km")
        return (
            duration if isinstance(duration, (int, float)) else math.inf,
            distance if isinstance(distance, (int, float)) else math.inf,
        )

    def _existing_allocations(self, incident_id, recommended_unit):
        with self._allocation_lock:
            station_keys = self._incident_station_keys.get(incident_id, set())
            stations = [
                self._stations_by_key[station_key]
                for station_key in station_keys
                if self._stations_by_key[station_key]["recommended_unit"]
                == recommended_unit
            ]
            return sorted(
                (self._allocation_view(station) for station in stations),
                key=self._allocation_sort_key,
            )

    def _claim_stations(
        self,
        incident_id,
        recommended_unit,
        candidates,
        required_count,
    ):
        """Atomically claim free stations and preserve existing incident claims."""
        with self._allocation_lock:
            station_keys = self._incident_station_keys.setdefault(
                incident_id, set()
            )
            selected = [
                self._stations_by_key[station_key]
                for station_key in station_keys
                if self._stations_by_key[station_key]["recommended_unit"]
                == recommended_unit
            ]

            for candidate in candidates:
                if len(selected) >= required_count:
                    break

                station_key = candidate["resource_key"]
                station = self._stations_by_key[station_key]
                owner = station["assigned_incident_id"]
                if owner not in (None, incident_id):
                    continue

                if station_key in station_keys:
                    continue

                station["assigned_incident_id"] = incident_id
                station["_assigned_straight_line_distance_km"] = candidate[
                    "straight_line_distance_km"
                ]
                station["_assigned_routing_metric"] = deepcopy(
                    candidate.get("_routing_metric")
                )
                station["_assigned_route"] = None
                station["_assigned_selection_reason"] = candidate[
                    "selection_reason"
                ]
                station_keys.add(station_key)
                selected.append(station)

            if not station_keys:
                self._incident_station_keys.pop(incident_id, None)

            return [station["resource_key"] for station in selected]

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
        incident_id,
        recommended_unit,
        station_keys,
        event_location,
        allocation_time,
        routing_failure,
    ):
        """Fetch full routes only for stations that won the atomic claim."""
        errors = []

        for station_key in station_keys:
            with self._allocation_lock:
                station = self._stations_by_key[station_key]
                if station["assigned_incident_id"] != incident_id:
                    continue
                if station["_assigned_route"] is not None:
                    continue
                station_snapshot = station.copy()
                metric = deepcopy(station["_assigned_routing_metric"])

            if metric is None:
                route = self._unavailable_route(
                    metric,
                    routing_failure or "road route is unavailable",
                )
            else:
                try:
                    route = self.routing_client.route(
                        station_snapshot,
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
                            "station_key": station_key,
                            "reason": "route_details_unavailable",
                            "message": str(error),
                        }
                    )

            with self._allocation_lock:
                station = self._stations_by_key[station_key]
                if station["assigned_incident_id"] != incident_id:
                    continue
                station["_assigned_route"] = route
                if route.get("distance_m") is not None:
                    station["_assigned_routing_metric"] = {
                        **(station["_assigned_routing_metric"] or {}),
                        "distance_m": route["distance_m"],
                        "duration_s": route.get("duration_s"),
                    }

        return self._existing_allocations(incident_id, recommended_unit), errors

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
            existing = self._existing_allocations(
                request["incident_id"], recommended_unit
            )
            candidates = []
            unit_routing_failure = None
            catalog_error = self._station_catalog_errors.get(recommended_unit)
            if len(existing) < required_count:
                stations = self._station_catalogs.get(recommended_unit, [])
                # Every located station is eligible, including coarse points.
                candidates = self._rank_stations(
                    stations,
                    event_lat,
                    event_lon,
                )
                candidates = self._available_candidates(candidates)
                missing_count = required_count - len(existing)
                try:
                    candidates, road_access = self._rank_stations_by_road(
                        candidates,
                        event_location,
                        missing_count,
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

                if unit_routing_failure is not None:
                    candidates = [
                        {
                            **candidate,
                            "_routing_metric": None,
                            "selection_reason": "straight_line_fallback",
                        }
                        for candidate in candidates
                    ]

            station_keys = self._claim_stations(
                request["incident_id"],
                recommended_unit,
                candidates,
                required_count,
            )
            assigned, route_errors = self._enrich_routes(
                request["incident_id"],
                recommended_unit,
                station_keys,
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

    def release_incident(self, incident_id):
        """Release every station assigned to one incident; safe to call twice."""
        released = []
        with self._allocation_lock:
            station_keys = self._incident_station_keys.pop(incident_id, set())
            for station_key in station_keys:
                station = self._stations_by_key[station_key]
                if station["assigned_incident_id"] != incident_id:
                    continue

                released_station = self._allocation_view(station)
                released_station["allocation_status"] = "released"
                released_station["available_for_ecoguard"] = True
                released.append(released_station)
                station["assigned_incident_id"] = None
                station["_assigned_straight_line_distance_km"] = None
                station["_assigned_routing_metric"] = None
                station["_assigned_route"] = None
                station["_assigned_selection_reason"] = None

        return sorted(released, key=self._allocation_sort_key)

    def active_allocations(self):
        """Return a read-only snapshot useful to callers and tests."""
        with self._allocation_lock:
            return {
                incident_id: sorted(
                    (
                        self._allocation_view(self._stations_by_key[station_key])
                        for station_key in station_keys
                    ),
                    key=self._allocation_sort_key,
                )
                for incident_id, station_keys in self._incident_station_keys.items()
            }
