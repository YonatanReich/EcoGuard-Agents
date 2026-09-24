"""Road ranking and route enrichment for allocated emergency stations."""

from __future__ import annotations

import math
from copy import deepcopy
from datetime import datetime, timedelta

from ecoguard.resource_allocator.geo import haversine_distance
from ecoguard.resource_allocator.mapbox_client import RoutingError


class AllocationRoutingService:
    """Rank candidate stations and attach routes to accepted allocations."""

    def __init__(self, routing_client):
        """Build the service around an injectable routing provider."""
        self.routing_client = routing_client

    def rank_stations_by_road(
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

    def enrich_routes(
        self,
        assigned,
        candidates,
        event_location,
        allocation_time: datetime,
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
                    route = self.routing_client.route(candidate, event_location)
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

        return sorted(enriched, key=self._assigned_station_display_key), errors

    def mark_unverified_field_access(self, stations, event_location):
        """Preserve the routed road leg and add an explicitly unverified gap."""
        marked = []
        for original in stations:
            station = deepcopy(original)
            route = station.get("route")
            if not isinstance(route, dict):
                marked.append(station)
                continue
            route["road_access_verified"] = False
            route["requires_field_access_confirmation"] = True
            if route.get("status") != "unavailable":
                route["status"] = "partial_offroad"
            destination = route.get("destination") or {}
            snapped = destination.get("snapped_location")
            if isinstance(snapped, dict):
                try:
                    snap_lat = float(snapped["latitude"])
                    snap_lon = float(snapped["longitude"])
                    target_lat = float(event_location["latitude"])
                    target_lon = float(event_location["longitude"])
                except (KeyError, TypeError, ValueError):
                    pass
                else:
                    reported_distance = destination.get("snap_distance_m")
                    distance_m = (
                        float(reported_distance)
                        if isinstance(reported_distance, (int, float))
                        and not isinstance(reported_distance, bool)
                        else haversine_distance(
                            snap_lat,
                            snap_lon,
                            target_lat,
                            target_lon,
                        )
                        * 1000
                    )
                    route["offroad_segment"] = {
                        "distance_m": max(0.0, distance_m),
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [
                                [snap_lon, snap_lat],
                                [target_lon, target_lat],
                            ],
                        },
                        "access_verified": False,
                    }
            station["route"] = route
            marked.append(station)
        return marked

    def _unavailable_route(self, metric, message):
        """Build a route result saying no route could be obtained, and why."""
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

    @staticmethod
    def _assigned_station_display_key(station):
        """Sort an allocated station by travel time, then distance."""
        route = station.get("route") or {}
        duration = route.get("duration_s")
        distance = station.get("distance_km")
        return (
            duration if isinstance(duration, (int, float)) else math.inf,
            distance if isinstance(distance, (int, float)) else math.inf,
        )
