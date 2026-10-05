"""Locate and verify road response sites for hydrometric flood incidents."""

from __future__ import annotations

import hashlib
import logging
import math
import os
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from ecoguard.collectors.flood.road_network import ROAD_CLASSES
from ecoguard.database.repositories.flood_road_targets import (
    FloodRoadTargetRepository,
)
from ecoguard.resource_allocator.geo import haversine_distance
from ecoguard.resource_allocator.mapbox_client import MapboxClient, RoutingError


logger = logging.getLogger(__name__)

ALWAYS_RELEVANT = frozenset({"motorway", "trunk", "primary", "secondary"})
URBAN_RELEVANT = frozenset({"tertiary", "street", "street_limited"})
EXTREME_RELEVANT = frozenset({"tertiary"})
NEVER_RELEVANT = frozenset({"service", "track", "pedestrian", "path"})
POTENTIALLY_RELEVANT = tuple(sorted(ROAD_CLASSES - NEVER_RELEVANT))


STREAM_ACCESS_ADVISORY = {
    "type": "stream_access_warning",
    "action": "warn_and_restrict_stream_access",
    "scope": "affected_stream",
    "instruction": (
        "Warn the public about flash-flood danger and restrict access to the "
        "affected stream, including hikers and visitors in the channel."
    ),
}


def base_road_class(road_class: object) -> str:
    """A road class without its slip-road suffix, so a ramp counts as its road."""
    value = str(road_class or "").strip()
    return value[:-5] if value.endswith("_link") else value


def road_is_relevant(candidate: Mapping[str, Any], severity_level: int) -> bool:
    """Apply the operational road policy after point-level urban lookup."""

    road_class = str(candidate.get("road_class") or "")
    base = base_road_class(road_class)
    if road_class in NEVER_RELEVANT or base in NEVER_RELEVANT:
        return False
    if candidate.get("vehicle_access") is False:
        return False
    if base in ALWAYS_RELEVANT:
        return True
    urban = candidate.get("urban") is True
    if base in EXTREME_RELEVANT and severity_level >= 5:
        return True
    if base in URBAN_RELEVANT:
        return urban
    return False


class FloodRoadTargetAgent:
    """Turn persisted Flood detector evidence into verified road sites.

    This component identifies allocation destinations; it does not decide how
    many stations or vehicles should be dispatched to each destination.
    """

    def __init__(
        self,
        *,
        repository: object | None = None,
        mapbox_client: object | None = None,
        primary_station_radius_m: float | None = None,
        maximum_station_radius_m: float | None = None,
        mapbox_verification_radius_m: float | None = None,
        duplicate_distance_m: float | None = None,
    ) -> None:
        """Build the agent. The repository, routing client and radii are injectable for testing."""
        self.repository = repository or FloodRoadTargetRepository()
        self.mapbox_client = mapbox_client or MapboxClient()
        self.primary_station_radius_m = self._positive(
            primary_station_radius_m,
            "FLOOD_ROAD_PRIMARY_RADIUS_M",
            30.0,
        )
        self.maximum_station_radius_m = self._positive(
            maximum_station_radius_m,
            "FLOOD_ROAD_MAXIMUM_RADIUS_M",
            250.0,
        )
        self.mapbox_verification_radius_m = self._positive(
            mapbox_verification_radius_m,
            "FLOOD_MAPBOX_VERIFICATION_RADIUS_M",
            50.0,
        )
        self.duplicate_distance_m = self._positive(
            duplicate_distance_m,
            "FLOOD_ROAD_DUPLICATE_DISTANCE_M",
            75.0,
        )
        if self.primary_station_radius_m > self.maximum_station_radius_m:
            raise ValueError("primary flood road radius exceeds maximum radius")
        if self.mapbox_verification_radius_m > 50:
            raise ValueError("Mapbox verification radius cannot exceed 50 metres")

    @staticmethod
    def _positive(value: float | None, environment: str, default: float) -> float:
        """A setting that must be a positive number, from the argument or the environment."""
        selected = float(
            value if value is not None else os.getenv(environment, str(default))
        )
        if not math.isfinite(selected) or selected <= 0:
            raise ValueError(f"{environment} must be positive")
        return selected

    @staticmethod
    def _timestamp(value: object) -> float:
        """A time as a number, so two readings can be compared."""
        if isinstance(value, datetime):
            parsed = value
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return float("-inf")
        elif not isinstance(value, datetime):
            return float("-inf")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()

    @classmethod
    def _station_states(cls, incident: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Keep the latest Flood signal for every hydrometric station."""

        latest: dict[int, dict[str, Any]] = {}
        for raw_signal in incident.get("signals") or []:
            if not isinstance(raw_signal, Mapping) or raw_signal.get("hazard") != "flood":
                continue
            evidence = raw_signal.get("evidence") or {}
            location = raw_signal.get("location") or {}
            if not isinstance(evidence, Mapping) or not isinstance(location, Mapping):
                continue
            station_id = evidence.get("source_station_id", evidence.get("station_id"))
            severity = evidence.get("severity_level")
            try:
                station_id = int(station_id)
                severity = int(severity)
                latitude = float(location["latitude"])
                longitude = float(location["longitude"])
                precision_m = float(location.get("precision_m") or 100.0)
            except (KeyError, TypeError, ValueError):
                continue
            state = {
                "source_station_id": station_id,
                "severity_level": severity,
                "latitude": latitude,
                "longitude": longitude,
                "precision_m": max(0.0, precision_m),
                "observed_at": raw_signal.get("observed_at"),
            }
            previous = latest.get(station_id)
            if previous is None or cls._timestamp(state["observed_at"]) >= cls._timestamp(
                previous["observed_at"]
            ):
                latest[station_id] = state
        return [latest[key] for key in sorted(latest)]

    @staticmethod
    def _distance_m(first: Mapping[str, Any], second: Mapping[str, Any]) -> float:
        """Distance between two coordinates, in metres."""
        return haversine_distance(
            float(first["latitude"]),
            float(first["longitude"]),
            float(second["latitude"]),
            float(second["longitude"]),
        ) * 1000

    @staticmethod
    def _road_identity(candidate: Mapping[str, Any]) -> tuple[str, str]:
        """A stable identity for one road, preferring its official number."""
        road_ref = str(candidate.get("road_ref") or "").strip().casefold()
        if road_ref:
            return "ref", road_ref
        source_id = str(candidate.get("source_feature_id") or "").strip()
        return "feature", f"{candidate.get('source')}:{source_id}"

    def _deduplicate(self, candidates: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        """Collapse only duplicate representations of the same road crossing."""

        kept: list[dict[str, Any]] = []
        ordered = sorted(
            candidates,
            key=lambda item: (
                self._road_identity(item),
                float(item["latitude"]),
                float(item["longitude"]),
                int(item.get("road_segment_id") or 0),
            ),
        )
        for candidate in ordered:
            duplicate_index = next(
                (
                    index
                    for index, existing in enumerate(kept)
                    if self._road_identity(existing) == self._road_identity(candidate)
                    and self._distance_m(existing, candidate)
                    <= self.duplicate_distance_m
                ),
                None,
            )
            if duplicate_index is None:
                kept.append(candidate)
            elif int(candidate["_state"]["severity_level"]) > int(
                kept[duplicate_index]["_state"]["severity_level"]
            ):
                # The same physical crossing may be reported by two gauges.
                # Preserve the more severe current evidence deterministically.
                kept[duplicate_index] = candidate
        return kept

    def _station_candidates(
        self, state: Mapping[str, Any]
    ) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]]]:
        """The road crossings near one gauge, and how they were found."""
        station_id = int(state["source_station_id"])
        stream = self.repository.stream_identity(station_id)
        if stream is not None and stream.get("has_geometry") is True:
            candidates = self.repository.stream_crossings(
                water_source_id=int(stream["water_source_id"]),
                road_classes=POTENTIALLY_RELEVANT,
            )
            return "matched_stream", stream, candidates

        # Start with the precise 30 m search.  Expand only when it found
        # nothing, and never beyond the configured safety cap.
        candidates = self.repository.roads_near_station(
            source_station_id=station_id,
            radius_m=self.primary_station_radius_m,
            road_classes=POTENTIALLY_RELEVANT,
        )
        if candidates:
            return "station_buffer_primary", None, candidates
        expanded_radius = min(
            max(self.primary_station_radius_m, float(state["precision_m"])),
            self.maximum_station_radius_m,
        )
        if expanded_radius <= self.primary_station_radius_m:
            return "station_buffer_primary", None, []
        candidates = self.repository.roads_near_station(
            source_station_id=station_id,
            radius_m=expanded_radius,
            road_classes=POTENTIALLY_RELEVANT,
        )
        return "station_buffer_expanded", None, candidates

    @staticmethod
    def _target_id(
        incident_id: str,
        station_id: int,
        candidate: Mapping[str, Any],
    ) -> str:
        """A stable identifier for one flooded road site."""
        identity = "|".join(
            [
                incident_id,
                str(station_id),
                str(candidate.get("source") or ""),
                str(candidate.get("source_feature_id") or ""),
                f"{float(candidate['latitude']):.6f}",
                f"{float(candidate['longitude']):.6f}",
            ]
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        return f"flood-road-{digest}"

    def _verify(
        self,
        incident_id: str,
        state: Mapping[str, Any],
        strategy: str,
        stream: Mapping[str, Any] | None,
        candidate: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Check a candidate crossing against the road network before reporting it."""
        crossing_location = {
            "latitude": float(candidate["latitude"]),
            "longitude": float(candidate["longitude"]),
        }
        try:
            verification = self.mapbox_client.verify_road_candidate(
                dict(candidate),
                radius_m=self.mapbox_verification_radius_m,
            )
        except (RoutingError, ValueError) as error:
            verification = {
                "status": "unavailable",
                "verified": False,
                "reason": "mapbox_verification_unavailable",
                "mapbox_access_location": None,
                "mapbox_snap_distance_m": None,
                "error": str(error),
            }
        verified = verification.get("verified") is True
        local_distance = float(candidate.get("distance_from_station_m") or 0.0)
        local_confidence = (
            "high"
            if strategy == "matched_stream" or local_distance <= self.primary_station_radius_m
            else "low"
        )
        return {
            "target_id": self._target_id(
                incident_id, int(state["source_station_id"]), candidate
            ),
            "source_station_id": int(state["source_station_id"]),
            "severity_level": int(state["severity_level"]),
            "strategy": strategy,
            "stream": dict(stream) if stream is not None else None,
            "road": {
                "segment_id": candidate.get("road_segment_id"),
                "source": candidate.get("source"),
                "source_feature_id": candidate.get("source_feature_id"),
                "class": candidate.get("road_class"),
                "base_class": base_road_class(candidate.get("road_class")),
                "name": candidate.get("road_name"),
                "ref": candidate.get("road_ref"),
                "bridge": candidate.get("bridge") is True,
                "tunnel": candidate.get("tunnel") is True,
                "vehicle_access": candidate.get("vehicle_access"),
            },
            "crossing_type": candidate.get("crossing_type"),
            "urban": candidate.get("urban") is True,
            "crossing_location": crossing_location,
            "distance_from_station_m": local_distance,
            "local_match_confidence": local_confidence,
            "mapbox_verification": verification,
            "allocation_location": verification.get("mapbox_access_location"),
            "allocation_eligible": verified,
        }

    def identify(self, incident: Mapping[str, Any]) -> dict[str, Any]:
        """Return distinct, Mapbox-verified road sites for one Flood incident."""

        incident_id = str(incident.get("id") or "").strip()
        if not incident_id:
            raise ValueError("flood incident id is required")
        states = self._station_states(incident)
        result: dict[str, Any] = {
            "incident_id": incident_id,
            "hazard": "flood",
            "status": "targets_identified",
            "response_sites": [],
            "allocation_ready_sites": [],
            "hydrometric_sources": [],
            "resource_allocations": [],
            "advisories": [dict(STREAM_ACCESS_ADVISORY)],
            "errors": [],
        }
        if not states:
            result["status"] = "not_evaluated"
            result["reason"] = "hydrometric_station_evidence_unavailable"
            return result

        raw: list[dict[str, Any]] = []
        context_by_station: dict[int, tuple[str, dict[str, Any] | None]] = {}
        for state in states:
            station_id = int(state["source_station_id"])
            try:
                strategy, stream, candidates = self._station_candidates(state)
            except Exception as error:
                logger.exception(
                    "flood road targeting failed for incident %s station %s",
                    incident_id,
                    station_id,
                )
                result["errors"].append(
                    {
                        "source_station_id": station_id,
                        "reason": "spatial_lookup_failed",
                        "message": str(error),
                    }
                )
                result["hydrometric_sources"].append(
                    {
                        "station": {
                            "id": station_id,
                            "latitude": float(state["latitude"]),
                            "longitude": float(state["longitude"]),
                            "precision_m": float(state["precision_m"]),
                            "severity_level": int(state["severity_level"]),
                            "observed_at": state.get("observed_at"),
                            "stream_match": "unmatched",
                        },
                        "strategy": "spatial_lookup_failed",
                        "stream": None,
                    }
                )
                continue
            context_by_station[station_id] = (strategy, stream)
            result["hydrometric_sources"].append(
                {
                    "station": {
                        "id": station_id,
                        "latitude": float(state["latitude"]),
                        "longitude": float(state["longitude"]),
                        "precision_m": float(state["precision_m"]),
                        "severity_level": int(state["severity_level"]),
                        "observed_at": state.get("observed_at"),
                        "stream_match": (
                            "matched" if stream is not None else "unmatched"
                        ),
                    },
                    "strategy": strategy,
                    "stream": dict(stream) if stream is not None else None,
                }
            )
            for candidate in candidates:
                if road_is_relevant(candidate, int(state["severity_level"])):
                    raw.append({**candidate, "_state": state})

        distinct = self._deduplicate(raw)
        sites = []
        for candidate in distinct:
            state = candidate.pop("_state")
            station_id = int(state["source_station_id"])
            strategy, stream = context_by_station[station_id]
            sites.append(
                self._verify(
                    incident_id,
                    state,
                    strategy,
                    stream,
                    candidate,
                )
            )

        result["response_sites"] = sites
        result["allocation_ready_sites"] = [
            site for site in sites if site["allocation_eligible"]
        ]
        if not sites and result["errors"]:
            result["status"] = "failed"
            result["reason"] = "spatial_lookup_failed"
        elif not sites:
            result["status"] = "no_road_targets"
            result["reason"] = "no_relevant_road_crossings"
            logger.info(
                "flood road targeting: incident %s has no relevant road sites; "
                "stream access advisory retained",
                incident_id,
            )
        elif not result["allocation_ready_sites"]:
            result["status"] = "verification_incomplete"
            result["reason"] = "no_mapbox_verified_road_sites"
        return result


__all__ = [
    "FloodRoadTargetAgent",
    "base_road_class",
    "road_is_relevant",
]
