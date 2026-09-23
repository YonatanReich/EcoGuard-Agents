"""Conservative station-to-stream matching and downstream route building."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class StreamTopologyPolicy:
    """Keep uncertain stream matches out of downstream routing."""

    stream_candidate_limit: int = 20
    strong_stream_distance_m: float = 100.0
    max_reliable_stream_distance_m: float = 1_000.0
    stream_ambiguity_distance_m: float = 50.0
    stream_name_override_distance_factor: float = 3.0
    max_downstream_hops: int = 20


_GENERIC_STREAM_NAME_TOKENS = frozenset(
    {"נחל", "נהר", "ואדי", "wadi", "nahal", "river", "stream"}
)


def _name_tokens(value: Any) -> tuple[str, ...]:
    """A name split into comparable words."""
    if not isinstance(value, str):
        return ()
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return tuple(
        token
        for token in re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)
        if token not in _GENERIC_STREAM_NAME_TOKENS
    )


def _stream_name_matches_station(
    candidate: Mapping[str, Any], station: Mapping[str, Any]
) -> bool:
    """Whether a stream's name matches the gauge's, allowing for spelling."""
    stream_tokens = _name_tokens(candidate.get("name_he"))
    if not stream_tokens:
        return False
    for field in ("station_name_he", "station_name_en"):
        station_tokens = set(_name_tokens(station.get(field)))
        if station_tokens and all(token in station_tokens for token in stream_tokens):
            return True
    return False


def _stream_identity(candidate: Mapping[str, Any]) -> tuple[str, Any]:
    """A stable key for one stream, used to remove duplicates."""
    if candidate.get("water_source_id") is not None:
        return "water_source_id", candidate["water_source_id"]
    name = _name_tokens(candidate.get("name_he"))
    if name:
        return "name", name
    return "object_id", candidate.get("object_id")


def unavailable_stream_context(reason: str) -> dict[str, Any]:
    """A stream result saying why nothing could be determined."""
    return {
        "association": "unavailable",
        "matched": False,
        "confidence": "unavailable",
        "method": None,
        "candidate_count": 0,
        "distinct_candidate_count": 0,
        "stream": None,
        "nearest_candidate": None,
        "warnings": [reason],
    }


def build_stream_context(
    station: Mapping[str, Any],
    raw_candidates: Sequence[Mapping[str, Any]],
    policy: StreamTopologyPolicy | None = None,
) -> dict[str, Any]:
    """Match a gauge to one stream using the same conservative legacy rules."""
    selected_policy = policy or StreamTopologyPolicy()
    if station.get("latitude") is None or station.get("longitude") is None:
        return unavailable_stream_context("station_location_unavailable")
    if station.get("basin_id") is None:
        return unavailable_stream_context("drainage_basin_unavailable")

    candidates: list[dict[str, Any]] = []
    for raw in raw_candidates:
        try:
            distance = float(raw["distance_m"])
        except (KeyError, TypeError, ValueError):
            continue
        if distance < 0:
            continue
        candidate = {**dict(raw), "distance_m": distance}
        candidate["name_matches_station"] = _stream_name_matches_station(
            candidate, station
        )
        candidates.append(candidate)
    candidates.sort(
        key=lambda item: (
            item["distance_m"],
            item.get("object_id") is None,
            str(item.get("object_id")),
        )
    )

    distinct: dict[tuple[str, Any], dict[str, Any]] = {}
    for candidate in candidates:
        distinct.setdefault(_stream_identity(candidate), candidate)
    streams = list(distinct.values())
    result = {
        "association": "same_drainage_basin",
        "matched": False,
        "confidence": "low",
        "method": None,
        "candidate_count": len(candidates),
        "distinct_candidate_count": len(streams),
        "stream": None,
        "nearest_candidate": None,
        "warnings": [],
    }
    if len(candidates) >= selected_policy.stream_candidate_limit:
        result["warnings"].append("stream_candidate_limit_reached")
    if not streams:
        result["warnings"].append("no_stream_candidate_in_same_basin")
        return result

    nearest = streams[0]
    reliable = [
        item
        for item in streams
        if item["distance_m"] <= selected_policy.max_reliable_stream_distance_m
    ]
    if not reliable:
        result["nearest_candidate"] = _public_stream(nearest)
        result["warnings"].append("nearest_stream_beyond_reliable_distance")
        return result

    selected = reliable[0]
    method = "same_basin_distance_only"
    name_matches = [item for item in reliable if item["name_matches_station"]]
    if name_matches:
        named = name_matches[0]
        maximum_distance = max(
            selected_policy.strong_stream_distance_m,
            selected["distance_m"]
            * selected_policy.stream_name_override_distance_factor,
        )
        if named["distance_m"] <= maximum_distance:
            selected = named
            method = "same_basin_name_and_distance"
        else:
            result["warnings"].append("name_matching_stream_is_much_farther")

    comparable = [
        item
        for item in reliable
        if _stream_identity(item) != _stream_identity(selected)
        and (not selected["name_matches_station"] or item["name_matches_station"])
    ]
    if any(
        abs(item["distance_m"] - selected["distance_m"])
        <= selected_policy.stream_ambiguity_distance_m
        for item in comparable
    ):
        result["method"] = method
        result["nearest_candidate"] = _public_stream(selected)
        result["warnings"].append("multiple_similarly_close_streams")
        return result

    if not selected["name_matches_station"]:
        result["warnings"].append("station_and_stream_names_do_not_match")
    if (
        selected["distance_m"] <= selected_policy.strong_stream_distance_m
        and selected["name_matches_station"]
    ):
        confidence = "high"
    elif (
        selected["distance_m"] <= selected_policy.strong_stream_distance_m
        or selected["name_matches_station"]
    ):
        confidence = "medium"
    else:
        confidence = "low"

    result["confidence"] = confidence
    result["method"] = method
    if confidence in {"high", "medium"}:
        result["matched"] = True
        result["stream"] = _public_stream(selected)
    else:
        result["nearest_candidate"] = _public_stream(selected)
        result["warnings"].append("distance_only_match_is_not_reliable")
    return result


def _public_stream(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """One stream reduced to the fields the frontend is given."""
    return {**dict(candidate), "distance_m": round(float(candidate["distance_m"]), 1)}


def unavailable_downstream_route(reason: str) -> dict[str, Any]:
    """A downstream result saying why nothing could be determined."""
    return {
        "status": "unavailable",
        "confidence": "unavailable",
        "method": "water_authority_draining_water_id",
        "origin_water_source_id": None,
        "segment_count": 0,
        "segments": [],
        "termination": reason,
        "limitations": [
            "route_uses_declared_connections_not_hydraulic_simulation",
            "coordinate_order_is_not_used_as_flow_direction",
            "route_does_not_predict_inundation_extent_or_travel_time",
            "representative_points_are_not_flood_boundaries",
        ],
    }


def build_downstream_route(
    stream_context: Mapping[str, Any],
    network: Mapping[int, Mapping[str, Any]],
    policy: StreamTopologyPolicy | None = None,
) -> dict[str, Any]:
    """Follow every provider-declared downstream id until the network ends."""
    selected_policy = policy or StreamTopologyPolicy()
    stream = stream_context.get("stream")
    if not stream_context.get("matched") or not isinstance(stream, Mapping):
        return unavailable_downstream_route("origin_stream_unmatched")
    try:
        origin_id = int(stream["water_source_id"])
    except (KeyError, TypeError, ValueError):
        return unavailable_downstream_route("origin_water_source_id_unavailable")
    if not network:
        return unavailable_downstream_route("stream_network_empty")

    result = unavailable_downstream_route("maximum_hops_reached")
    result["origin_water_source_id"] = origin_id
    result["confidence"] = stream_context.get("confidence", "unavailable")
    current_id = origin_id
    visited: set[int] = set()
    segments: list[dict[str, Any]] = []
    status = "partial"
    termination = "maximum_hops_reached"
    for hop in range(selected_policy.max_downstream_hops + 1):
        if current_id in visited:
            termination = "cycle_detected"
            result["confidence"] = "low"
            break
        node = network.get(current_id)
        if node is None:
            termination = (
                "origin_stream_missing_from_network"
                if hop == 0
                else "downstream_stream_missing_from_network"
            )
            break
        visited.add(current_id)
        segment = {"hop": hop, **dict(node)}
        if hop == 0:
            segment["matched_object_id"] = stream.get("object_id")
        segments.append(segment)
        if node.get("topology_conflict"):
            termination = "conflicting_downstream_connections"
            result["confidence"] = "low"
            break
        downstream_id = node.get("draining_water_id")
        if downstream_id is None:
            termination = "declared_network_end"
            status = "complete"
            break
        if hop == selected_policy.max_downstream_hops:
            break
        current_id = int(downstream_id)

    result.update(
        status=status if segments else "unavailable",
        segment_count=len(segments),
        segments=segments,
        termination=termination,
    )
    return result
