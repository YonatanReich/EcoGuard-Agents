"""Choose and rank station candidates without reserving them."""

from __future__ import annotations

from dataclasses import dataclass

from ecoguard.resource_allocator.geo import coordinates, haversine_distance
from ecoguard.resource_allocator.mapbox_client import RoutingError


@dataclass(frozen=True)
class StationSelectionResult:
    """The ranked candidates and context produced by station selection."""

    candidates: list[dict]
    road_access: dict | None
    police_responsibility: dict | None
    police_responsibility_error: str | None
    routing_failure: str | None


class StationSelectionService:
    """Select the best station candidates without creating DB allocations."""

    def __init__(
        self,
        *,
        active_allocations_reader,
        police_responsibility_reader,
        routing_service,
    ):
        self.active_allocations_reader = active_allocations_reader
        self.police_responsibility_reader = police_responsibility_reader
        self.routing_service = routing_service

    def choose(
        self,
        *,
        stations,
        event_location,
        incident_id,
        recommended_unit,
        required_count,
    ) -> StationSelectionResult:
        """Return ranked candidates and metadata without claiming them."""
        selection_reason = "shortest_road_travel_time"
        responsibility = None
        responsibility_error = None

        if recommended_unit == "police":
            stations, responsibility, responsibility_error = (
                self._police_candidates_for_event(stations, event_location)
            )
            selection_reason = (
                responsibility["reason"]
                if responsibility["status"] == "matched"
                else "nearest_police_station_fallback"
            )

        event_lat, event_lon = coordinates(event_location)
        candidates = self._rank_stations(stations, event_lat, event_lon)
        candidates = self._available_candidates(
            candidates,
            incident_id,
            recommended_unit,
        )

        road_access = None
        routing_failure = None
        try:
            candidates, road_access = self.routing_service.rank_stations_by_road(
                candidates,
                event_location,
                required_count,
                selection_reason,
            )
        except RoutingError as error:
            routing_failure = str(error)
            candidates = [
                {
                    **candidate,
                    "distance_km": candidate["straight_line_distance_km"],
                    "_routing_metric": None,
                    "selection_reason": (
                        "straight_line_fallback"
                        if selection_reason == "shortest_road_travel_time"
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

        return StationSelectionResult(
            candidates=candidates,
            road_access=road_access,
            police_responsibility=responsibility,
            police_responsibility_error=responsibility_error,
            routing_failure=routing_failure,
        )

    @staticmethod
    def _rank_stations(stations, event_lat, event_lon):
        """Return valid, unique stations sorted by straight-line distance."""
        unique = {}
        for source in stations:
            try:
                station_lat, station_lon = coordinates(source)
            except ValueError:
                continue
            distance = haversine_distance(
                event_lat,
                event_lon,
                station_lat,
                station_lon,
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
            return candidates
        occupied = {
            allocation["station_id"]
            for allocation in self.active_allocations_reader()
            if allocation["recommended_unit"] == recommended_unit
            and allocation["incident_id"] != incident_id
        }
        return [
            candidate
            for candidate in candidates
            if candidate["database_id"] not in occupied
        ]

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
