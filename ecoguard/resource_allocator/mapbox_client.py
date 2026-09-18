"""Small synchronous client for Mapbox Matrix and Directions APIs."""

from __future__ import annotations

import math
import os
from typing import Any, Iterable

import httpx


class RoutingError(RuntimeError):
    """Mapbox could not produce a usable routing result."""


class RouteNotFoundError(RoutingError):
    """Mapbox is available, but no road route exists for the coordinates."""


class MapboxClient:
    provider = "mapbox"

    def __init__(
        self,
        access_token: str | None = None,
        *,
        base_url: str | None = None,
        profile: str | None = None,
        timeout_seconds: float | None = None,
        matrix_max_sources: int | None = None,
        event_road_tolerance_m: float | None = None,
        http_client: httpx.Client | None = None,
    ):
        self.access_token = access_token or os.getenv("MAPBOX_ACCESS_TOKEN")
        self.base_url = (
            base_url or os.getenv("MAPBOX_BASE_URL") or "https://api.mapbox.com"
        ).rstrip("/")
        self.profile = profile or os.getenv(
            "MAPBOX_ROUTING_PROFILE", "mapbox/driving-traffic"
        )
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else float(os.getenv("MAPBOX_ROUTING_TIMEOUT_SECONDS", "5"))
        )
        default_sources = 9 if self.profile == "mapbox/driving-traffic" else 24
        self.matrix_max_sources = (
            matrix_max_sources
            if matrix_max_sources is not None
            else int(os.getenv("MAPBOX_MATRIX_MAX_SOURCES", str(default_sources)))
        )
        self.event_road_tolerance_m = (
            event_road_tolerance_m
            if event_road_tolerance_m is not None
            else float(os.getenv("MAPBOX_EVENT_ROAD_TOLERANCE_M", "100"))
        )
        self.http_client = http_client or httpx.Client()

        allowed_profiles = {
            "mapbox/driving",
            "mapbox/driving-traffic",
            "mapbox/walking",
            "mapbox/cycling",
        }
        if self.profile not in allowed_profiles:
            raise ValueError("unsupported Mapbox routing profile")
        if self.timeout_seconds <= 0:
            raise ValueError("Mapbox timeout must be positive")
        if not 1 <= self.matrix_max_sources <= default_sources:
            raise ValueError(
                f"Mapbox {self.profile} supports at most {default_sources} "
                "station sources per request"
            )
        if self.event_road_tolerance_m < 0:
            raise ValueError("Mapbox road tolerance cannot be negative")

    @staticmethod
    def _point(coordinates: Any) -> dict[str, float]:
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            raise RoutingError("Mapbox returned invalid coordinates")
        longitude, latitude = coordinates[:2]
        if not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            for value in (latitude, longitude)
        ):
            raise RoutingError("Mapbox returned invalid coordinates")
        return {"latitude": float(latitude), "longitude": float(longitude)}

    @staticmethod
    def _number(value: Any, field: str) -> float:
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < 0
        ):
            raise RoutingError(f"Mapbox returned invalid {field}")
        return float(value)

    def _request(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.access_token:
            raise RoutingError("MAPBOX_ACCESS_TOKEN is not configured")

        try:
            response = self.http_client.get(
                f"{self.base_url}/{path.lstrip('/')}",
                params={**params, "access_token": self.access_token},
                timeout=self.timeout_seconds,
            )
        except httpx.RequestError as error:
            # Do not include the request URL because it contains the token.
            raise RoutingError(
                f"Mapbox request failed: {type(error).__name__}"
            ) from error

        try:
            payload = response.json()
        except ValueError as error:
            raise RoutingError("Mapbox returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise RoutingError("Mapbox returned a non-object response")

        code = payload.get("code")
        if response.is_error or code != "Ok":
            message = payload.get("message") or code or f"HTTP {response.status_code}"
            error_type = (
                RouteNotFoundError
                if code in {"NoRoute", "NoSegment"}
                else RoutingError
            )
            raise error_type(f"Mapbox could not route coordinates: {message}")
        return payload

    @staticmethod
    def _coordinates(points: Iterable[dict[str, Any]]) -> str:
        return ";".join(
            f"{point['longitude']},{point['latitude']}" for point in points
        )

    def _road_access(
        self,
        waypoint: dict[str, Any],
        input_location: dict[str, float],
    ) -> dict[str, Any]:
        if not isinstance(waypoint, dict):
            raise RoutingError("Mapbox returned an invalid waypoint")
        snap_distance = waypoint.get("distance")
        return {
            "input_location": input_location.copy(),
            "snapped_location": self._point(waypoint.get("location")),
            "snap_distance_m": (
                self._number(snap_distance, "snap distance")
                if snap_distance is not None
                else None
            ),
            "road_name": waypoint.get("name") or None,
        }

    def travel_metrics(
        self,
        stations: list[dict[str, Any]],
        event_location: dict[str, float],
    ) -> dict[str, Any]:
        """Return road metrics and the event point snapped by Mapbox."""
        if not stations:
            return {"metrics": [], "road_access": None}

        metrics: list[dict[str, Any] | None] = []
        road_access = None

        for start in range(0, len(stations), self.matrix_max_sources):
            chunk = stations[start : start + self.matrix_max_sources]
            points = [
                {
                    "latitude": station["latitude"],
                    "longitude": station["longitude"],
                }
                for station in chunk
            ]
            points.append(event_location)
            destination_index = len(points) - 1
            source_indices = list(range(len(chunk)))
            # Mapbox bills and accepts a minimum of two matrix elements.
            if len(source_indices) == 1:
                source_indices.append(destination_index)

            payload = self._request(
                (
                    f"directions-matrix/v1/{self.profile}/"
                    f"{self._coordinates(points)}"
                ),
                {
                    "sources": ";".join(str(index) for index in source_indices),
                    "destinations": str(destination_index),
                    "annotations": "duration,distance",
                },
            )
            durations = payload.get("durations") or []
            distances = payload.get("distances") or []
            sources = payload.get("sources") or []
            destinations = payload.get("destinations") or []
            if (
                len(durations) < len(chunk)
                or len(distances) < len(chunk)
                or not destinations
            ):
                raise RoutingError("Mapbox returned an incomplete route matrix")

            chunk_access = self._road_access(destinations[0], event_location)
            if road_access is None:
                road_access = chunk_access

            for index in range(len(chunk)):
                duration_row = durations[index]
                distance_row = distances[index]
                if not isinstance(duration_row, list) or not isinstance(
                    distance_row, list
                ):
                    raise RoutingError("Mapbox returned an invalid route matrix")
                duration = duration_row[0] if duration_row else None
                distance = distance_row[0] if distance_row else None
                if duration is None or distance is None:
                    metrics.append(None)
                    continue

                source = sources[index] if index < len(sources) else {}
                metrics.append(
                    {
                        "duration_s": self._number(duration, "travel duration"),
                        "distance_m": self._number(distance, "route distance"),
                        "origin_snapped_location": (
                            self._point(source.get("location"))
                            if isinstance(source, dict) and source.get("location")
                            else None
                        ),
                        "origin_snap_distance_m": (
                            self._number(source.get("distance"), "snap distance")
                            if isinstance(source, dict)
                            and source.get("distance") is not None
                            else None
                        ),
                    }
                )

        return {"metrics": metrics, "road_access": road_access}

    @staticmethod
    def _hebrew_steps(steps: list[Any]) -> list[dict[str, Any]]:
        result = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            maneuver = step.get("maneuver") or {}
            result.append(
                {
                    "instruction": maneuver.get("instruction") or "",
                    "distance_m": step.get("distance"),
                    "duration_s": step.get("duration"),
                    "road_name": step.get("name") or None,
                    "maneuver_type": maneuver.get("type"),
                    "modifier": maneuver.get("modifier"),
                }
            )
        return result

    def route(
        self,
        station: dict[str, Any],
        event_location: dict[str, float],
    ) -> dict[str, Any]:
        points = [
            {
                "latitude": station["latitude"],
                "longitude": station["longitude"],
            },
            event_location,
        ]
        payload = self._request(
            f"directions/v5/{self.profile}/{self._coordinates(points)}",
            {
                "steps": "true",
                "language": "he",
                "roundabout_exits": "true",
                "geometries": "geojson",
                "overview": "full",
                "alternatives": "false",
            },
        )
        routes = payload.get("routes") or []
        waypoints = payload.get("waypoints") or []
        if not routes:
            raise RouteNotFoundError("Mapbox returned no route")
        if len(waypoints) < 2:
            raise RoutingError("Mapbox returned incomplete route waypoints")

        route = routes[0]
        if not isinstance(route, dict):
            raise RoutingError("Mapbox returned an invalid route")
        geometry = route.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
            raise RoutingError("Mapbox returned invalid route geometry")

        origin = self._road_access(waypoints[0], points[0])
        destination = self._road_access(waypoints[1], event_location)
        snap_distance = destination["snap_distance_m"]
        access_unverified = (
            snap_distance is None
            or snap_distance > self.event_road_tolerance_m
        )
        offroad_segment = None
        if snap_distance is not None and snap_distance > self.event_road_tolerance_m:
            snapped = destination["snapped_location"]
            offroad_segment = {
                "distance_m": snap_distance,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [snapped["longitude"], snapped["latitude"]],
                        [event_location["longitude"], event_location["latitude"]],
                    ],
                },
                "access_verified": False,
            }

        legs = route.get("legs") or []
        first_leg = legs[0] if legs and isinstance(legs[0], dict) else {}
        return {
            "status": "partial_offroad" if access_unverified else "complete",
            "provider": self.provider,
            "profile": self.profile,
            "distance_m": self._number(route.get("distance"), "route distance"),
            "duration_s": self._number(route.get("duration"), "route duration"),
            "geometry": geometry,
            "origin": origin,
            "destination": destination,
            "road_access_verified": not access_unverified,
            "requires_field_access_confirmation": access_unverified,
            "offroad_segment": offroad_segment,
            "steps_he": self._hebrew_steps(first_leg.get("steps") or []),
        }
