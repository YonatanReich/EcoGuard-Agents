"""Select and reserve nearby stations for emergency response requests."""

from ecoguard.shared.activity import live_actor
import math
from copy import deepcopy
from datetime import datetime, timezone

from ecoguard.database.repositories.fire_stations import fire_stations_geojson
from ecoguard.database.repositories.mda_stations import mda_stations_geojson
from ecoguard.database.repositories.police_stations import police_stations_geojson
from ecoguard.database.repositories.resource_allocations import (
    ResourceAllocationRepository,
)
from ecoguard.database.repositories.towns import (
    responsible_police_stations,
    town_at_location,
)
from ecoguard.coordinator import incidents as incident_store
from ecoguard.analyzers.flood.risk_analysis_schemas import (
    FloodRiskAssessment,
)
from ecoguard.resource_allocator.allocation_routing import AllocationRoutingService
from ecoguard.resource_allocator.geo import coordinates
from ecoguard.resource_allocator.mapbox_client import MapboxClient
from ecoguard.resource_allocator.flood_road_targets import FloodRoadTargetAgent
from ecoguard.resource_allocator.station_selection import StationSelectionService

RISK_LEVELS = frozenset({"low", "medium", "high", "critical"})

EARTHQUAKE_MINIMUM_RESPONSE_POLICY = "earthquake_minimum_response_v1"
EARTHQUAKE_ALLOCATION_BASIS = "protocol_recommended_units"
EARTHQUAKE_QUANTITY_SOURCE = "ecoguard_minimum_response_policy"

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

FLOOD_ROAD_PRIORITY = {
    "motorway": 6,
    "trunk": 5,
    "primary": 4,
    "secondary": 3,
    "tertiary": 2,
    "street": 1,
    "street_limited": 1,
}

SETTLEMENT_FIELDS = (
    "population",
    "households",
    "authority",
    "authority_type",
    "authority_phone",
    "authority_address",
    "authority_website",
    "area_km2",
)


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
        town_reader=None,
        flood_target_agent=None,
        incident_reader=None,
    ):
        """Build the allocator. Every reader and the routing client are injectable for testing."""
        self.station_readers = (
            _default_station_readers()
            if station_readers is None
            else station_readers
        )
        self.routing_client = routing_client or MapboxClient()
        self.routing_service = AllocationRoutingService(self.routing_client)
        self.allocation_repository = (
            allocation_repository or ResourceAllocationRepository()
        )
        self.police_responsibility_reader = (
            police_responsibility_reader or responsible_police_stations
        )
        self.station_selector = StationSelectionService(
            allocation_repository=self.allocation_repository,
            police_responsibility_reader=self.police_responsibility_reader,
            routing_service=self.routing_service,
        )
        self.town_reader = town_reader or town_at_location
        self.flood_target_agent = flood_target_agent or FloodRoadTargetAgent(
            mapbox_client=self.routing_client
        )
        self.incident_reader = incident_reader or incident_store.incident_by_id
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
        """Whether the plan this request came from succeeded."""
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
    def _required_station_count(
        risk_level,
        recommended_unit,
        response_plan=None,
        allocation_policy=None,
        hazard=None,
    ):
        """How many stations to commit for one unit type.

        The planner's figure wins where it supplies one. It derives team counts
        from an event grade anchored to a published threshold — ten teams is a
        national criterion in 201.02.003 §2.1.5 — whereas the table below is a
        placeholder, as its own comment says.

        The deeper reason is not which number is better. Two components
        deriving the same quantity by different logic will disagree about some
        fire eventually, and nothing here would notice: both answers are
        well-formed. So one of them has to be authoritative, and it is the one
        that can cite where its number came from.
        """
        if allocation_policy == EARTHQUAKE_MINIMUM_RESPONSE_POLICY:
            # EcoGuard product policy, not an official dispatch quantity.
            return 1
        if recommended_unit == "police":
            # Severity is sent to the responsible station; the station decides
            # how many internal units it dispatches.
            return 1
        if response_plan:
            teams = response_plan.get("teams_required")
            if recommended_unit == "fire_department" and isinstance(teams, int):
                return max(1, teams)
        explicit = (
            (response_plan or {}).get("station_requirements") or {}
        ).get(recommended_unit)
        if explicit is not None:
            return explicit
        # Nothing cited supplied a number, so one station per requested unit
        # type: the planner selects types, not fleet sizes, and the station
        # owns its internal vehicle and crew dispatch.
        #
        # This replaces a risk-level lookup table that returned two to four
        # stations. That table was invented -- its own comment said so, the
        # authority's real dispatch guidance living in the CAD system and not
        # in anything we hold. The branches above return counts that can cite
        # where they came from; when none of them applies, one station and the
        # station's own judgement beats a number nobody can source.
        return 1

    @staticmethod
    def _flood_site_priority(site):
        """How urgent one flooded road site is, relative to the others."""
        road = site.get("road") or {}
        verification = site.get("mapbox_verification") or {}
        snap_distance = verification.get("mapbox_snap_distance_m")
        return (
            int(site.get("severity_level") or 0),
            FLOOD_ROAD_PRIORITY.get(str(road.get("base_class") or ""), 0),
            int(site.get("urban") is True),
            (
                -float(snap_distance)
                if isinstance(snap_distance, (int, float))
                else -math.inf
            ),
            str(site.get("target_id") or ""),
        )

    def _prepare_flood_batch_request(self, item, now):
        """Convert Flood targets, or its gauge fallback, to a station request."""

        incident_id = str(item.get("incident_id") or "").strip()
        if not incident_id:
            raise ValueError("incident_id is required")
        targeting = item.get("flood_targeting")
        if not isinstance(targeting, dict):
            raise ValueError("flood_targeting must be an object")
        try:
            risk = FloodRiskAssessment.model_validate(item.get("risk_assessment"))
        except (TypeError, ValueError, AttributeError) as error:
            raise ValueError("flood_risk_assessment is required") from error
        if (
            risk.event_id != incident_id
            or risk.metadata.analysis_status not in {"success", "partial"}
            or risk.risk_score is None
            or risk.risk_level is None
        ):
            raise ValueError("flood_risk_assessment is unavailable")
        ready_sites = [
            site
            for site in targeting.get("allocation_ready_sites") or []
            if isinstance(site, dict)
            and site.get("allocation_eligible") is True
            and isinstance(site.get("allocation_location"), dict)
        ]
        if ready_sites:
            primary = max(ready_sites, key=self._flood_site_priority)
            severity = max(
                3,
                min(
                    6,
                    max(int(site.get("severity_level") or 3) for site in ready_sites),
                ),
            )
            requirements = {"police": 1}
            location = primary["allocation_location"]
            allocation_target = {
                "target_id": primary.get("target_id"),
                "target_type": "verified_road_site",
                "road": dict(primary.get("road") or {}),
                "allocation_location": dict(location),
                "covered_response_site_ids": [
                    site.get("target_id") for site in ready_sites
                ],
            }
            primary_target_id = primary.get("target_id")
            fallback_reason = None
        else:
            sources = [
                source
                for source in targeting.get("hydrometric_sources") or []
                if isinstance(source, dict)
                and isinstance(source.get("station"), dict)
            ]
            if not sources:
                return {
                    "terminal": {
                        "incident_id": incident_id,
                        "event_id": f"{incident_id}:flood-station-fallback",
                        "hazard": "flood",
                        "status": "skipped",
                        "reason": "hydrometric_station_location_unavailable",
                        "allocated_units": {},
                        "requirements": {"police": {
                            "requested": 1,
                            "assigned": 0,
                            "shortfall": 1,
                        }},
                        "shortages": {"police_station": 1},
                        "unsupported_units": [],
                        "errors": [],
                        "allocation_target": None,
                    }
                }
            primary_source = max(
                sources,
                key=lambda source: int(
                    (source.get("station") or {}).get("severity_level") or 3
                ),
            )
            station = primary_source["station"]
            severity = max(3, min(6, int(station.get("severity_level") or 3)))
            requirements = {"police": 1}
            location = {
                "latitude": float(station["latitude"]),
                "longitude": float(station["longitude"]),
            }
            primary_target_id = f"hydrometric-station-{station.get('id')}"
            allocation_target = {
                "target_id": primary_target_id,
                "target_type": "hydrometric_station_fallback",
                "source_station_id": station.get("id"),
                "allocation_location": dict(location),
                "covered_response_site_ids": [],
                "requires_road_access_resolution": True,
            }
            fallback_reason = "no_verified_flood_response_site"

        if risk.hydrologic_severity_level != severity:
            raise ValueError("flood risk severity does not match targeting evidence")
        risk_score = risk.risk_score
        risk_level = risk.risk_level
        event_id = (
            f"{incident_id}:flood-road-target"
            if ready_sites
            else f"{incident_id}:flood-station-fallback"
        )
        planner_plan = item.get("response_plan")
        planner_succeeded = (
            isinstance(planner_plan, dict)
            and self._planning_status(planner_plan) == "success"
        )
        if planner_succeeded:
            response_plan = deepcopy(planner_plan)
            planned_risk = response_plan.get("responding_to") or {}
            if (
                planned_risk.get("risk_score") != risk_score
                or str(planned_risk.get("risk_level") or "").lower() != risk_level
            ):
                raise ValueError("flood response plan does not match risk analyzer")
            # Road targeting owns the dispatch destination. The planner owns
            # the units and instructions, but must not replace that verified
            # operational location with the gauge centroid.
            response_plan["event_id"] = event_id
            response_plan["location"] = {
                "latitude": float(location["latitude"]),
                "longitude": float(location["longitude"]),
            }
            response_plan["responding_to"] = {
                **planned_risk,
                "primary_target_id": primary_target_id,
                "fallback_reason": fallback_reason,
            }
        else:
            response_plan = {
                "metadata": {
                    "planning_status": "success",
                    "timestamp": self._utc(item.get("queued_at") or now).isoformat(),
                    "agent": "deterministic_flood_station_fallback",
                },
                "event_id": event_id,
                "location": {
                    "latitude": float(location["latitude"]),
                    "longitude": float(location["longitude"]),
                },
                "responding_to": {
                    "risk_semantics": "detected_event_operational_risk",
                    "risk_score": risk_score,
                    "risk_level": risk_level,
                    "severity_level": severity,
                    "risk_confidence": risk.confidence,
                    "primary_target_id": primary_target_id,
                    "fallback_reason": fallback_reason,
                },
                "recommended_units": list(requirements),
                "response_actions": [
                    {
                        "action": "Secure access to the identified flood response site.",
                        "timeframe": "immediate",
                        "responsible_unit": unit,
                    }
                    for unit in requirements
                ],
            }
        prepared = self._prepare_batch_request(
            {
                "incident_id": incident_id,
                "hazard": "prepared_flood",
                "queued_at": item.get("queued_at"),
                "response_plan": response_plan,
            },
            now,
        )
        prepared["hazard"] = "flood"
        prepared["allocation_target"] = allocation_target
        return prepared

    def _prepare_batch_request(self, item, now):
        """Validate one Planner response before allocation starts."""
        if not isinstance(item, dict):
            raise ValueError("allocation request must be an object")

        if item.get("hazard") == "flood":
            return self._prepare_flood_batch_request(item, now)

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

        allocation_policy = item.get("allocation_policy")
        if allocation_policy is not None:
            if allocation_policy != EARTHQUAKE_MINIMUM_RESPONSE_POLICY:
                raise ValueError("unsupported allocation policy")
            if response_plan.get("hazard_type") != "earthquake":
                raise ValueError("earthquake allocation policy requires an earthquake plan")
            metadata = response_plan.get("metadata") or {}
            queued_at = self._utc(
                item.get("queued_at") or metadata.get("timestamp") or now
            )
            # The policy still governs how MANY stations go (one per unit
            # type); what it no longer governs is WHERE the incident sits in
            # the queue. That is now the same derived 0-100 score Fire and
            # Flood carry, so an M6.0 under a city outranks a brush fire and a
            # small tremor in open desert does not.
            responding_to = response_plan.get("responding_to") or {}
            risk_score = responding_to.get("risk_score")
            if (
                not isinstance(risk_score, (int, float))
                or isinstance(risk_score, bool)
                or not math.isfinite(risk_score)
                or not 0 <= risk_score <= 100
            ):
                raise ValueError("operational risk score must be between 0 and 100")
            risk_level = str(responding_to.get("risk_level") or "").lower()
            if risk_level not in RISK_LEVELS:
                raise ValueError("operational risk level is unavailable")
            waited_seconds = max(0, (now - queued_at).total_seconds())
            return {
                "incident_id": incident_id,
                "response_plan": response_plan,
                "risk_score": float(risk_score),
                "risk_level": risk_level,
                "queued_at": queued_at,
                "allocation_time": now,
                "urgency": self._urgency(response_plan),
                "effective_priority": float(risk_score) + int(waited_seconds // 300),
                "allocation_policy": EARTHQUAKE_MINIMUM_RESPONSE_POLICY,
                "allocation_basis": EARTHQUAKE_ALLOCATION_BASIS,
                "quantity_source": EARTHQUAKE_QUANTITY_SOURCE,
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
        if risk_level not in RISK_LEVELS:
            raise ValueError("operational risk level is unavailable")

        recommended_units = list(
            dict.fromkeys(response_plan.get("recommended_units") or [])
        )
        response_actions = response_plan.get("response_actions") or []
        if not isinstance(response_actions, list):
            raise ValueError("response_actions must be a list")
        action_units = set()
        for action in response_actions:
            if not isinstance(action, dict):
                raise ValueError("each response action must be an object")
            responsible_unit = str(action.get("responsible_unit") or "").strip()
            if responsible_unit not in recommended_units:
                raise ValueError(
                    "each response action must name a recommended responsible unit"
                )
            if not str(action.get("action") or "").strip():
                raise ValueError("each response action must contain an instruction")
            if action.get("timeframe") not in TIMEFRAME_PRIORITY:
                raise ValueError("each response action must contain a valid timeframe")
            action_units.add(responsible_unit)
        missing_action_units = set(recommended_units) - action_units
        if missing_action_units:
            raise ValueError(
                "each recommended unit must have at least one response action"
            )
        metadata = response_plan.get("metadata") or {}
        queued_at = self._utc(
            item.get("queued_at") or metadata.get("timestamp") or now
        )
        waited_seconds = max(0, (now - queued_at).total_seconds())
        aging_bonus = int(waited_seconds // 300)

        return {
            "incident_id": incident_id,
            "hazard": str(item.get("hazard") or "fire"),
            "response_plan": response_plan,
            "risk_score": float(risk_score),
            "risk_level": risk_level,
            "queued_at": queued_at,
            "allocation_time": now,
            "urgency": self._urgency(response_plan),
            # Aging adds one point every five minutes so old requests progress.
            "effective_priority": float(risk_score) + aging_bonus,
            "allocation_policy": None,
            "allocation_basis": None,
            "quantity_source": None,
        }

    @staticmethod
    def _priority_key(request):
        """How one request ranks against the rest.

        One key shape for every hazard. An earlier version gave earthquakes a
        different leading value, which put every fire and every flood above every
        earthquake at any magnitude - not ranked low, but not ranked at all.
        """
        # One key for every hazard. Earthquake used to return a leading 1 here
        # against everyone else's 0, and tuple comparison decides at index 0 --
        # so every fire and every flood outranked every earthquake, at any
        # magnitude. It was not ranked low; it was not ranked at all.
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
            point_coordinates = geometry.get("coordinates") or []
            if geometry.get("type") != "Point" or len(point_coordinates) < 2:
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
                "latitude": point_coordinates[1],
                "longitude": point_coordinates[0],
                "unit_type": station_type,
                "recommended_unit": recommended_unit,
                "resource_key": resource_key,
            }
            try:
                coordinates(station)
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
        if allocation.get("allocation_policy") is not None:
            result.update({
                "allocation_policy": allocation["allocation_policy"],
                "allocation_basis": allocation.get("allocation_basis"),
                "quantity_source": allocation.get("quantity_source"),
            })
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
        allocation_policy=None,
        allocation_basis=None,
        quantity_source=None,
    ):
        """Atomically claim stations through the shared DB repository."""
        claim = {
            "incident_id": incident_id,
            "recommended_unit": recommended_unit,
            "candidates": candidates,
            "required_count": required_count,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "allocated_at": allocated_at,
        }
        if allocation_policy is not None:
            claim.update({
                "allocation_policy": allocation_policy,
                "allocation_basis": allocation_basis,
                "quantity_source": quantity_source,
            })
        allocations = self.allocation_repository.claim_stations(
            **claim,
        )
        return [self._allocation_view(allocation) for allocation in allocations]

    def _allocate_batch_request(self, request):
        """Allocate stations for one request."""
        response_plan = request["response_plan"]
        event_lat, event_lon = coordinates(response_plan.get("location"))
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
            "hazard": request.get("hazard"),
            "status": "fulfilled",
            "risk_score": request["risk_score"],
            "risk_level": request["risk_level"],
            "severity": request["risk_level"],
            "effective_priority": request["effective_priority"],
            "queued_at": request["queued_at"].isoformat(),
            "allocation_needed": bool(recommended_units),
            "allocation_scope": "station",
            # Preserve the complete plan at the allocation boundary. Actions
            # are also copied onto every assigned station of their responsible
            # unit below, so dispatch consumers do not have to rejoin them.
            "response_actions": deepcopy(response_plan.get("response_actions") or []),
            "allocated_units": {},
            "requirements": {},
            "shortages": {},
            "unsupported_units": [],
            "errors": [],
        }
        if request.get("allocation_policy") is not None:
            result.update({
                "allocation_policy": request["allocation_policy"],
                "allocation_basis": request["allocation_basis"],
                "quantity_source": request["quantity_source"],
                "priority_basis": "fire_before_policy_then_action_timeframe_queued_at",
            })
        if request.get("allocation_target") is not None:
            result["allocation_target"] = request["allocation_target"]

        # Settlement context is resolved once per incident by the allocator,
        # using the same event coordinates that drive station selection.
        try:
            town = self.town_reader(latitude=event_lat, longitude=event_lon)
        except Exception:
            town = None
        result["settlement"] = (
            {field: town.get(field) for field in SETTLEMENT_FIELDS}
            if isinstance(town, dict)
            else None
        )

        if not recommended_units:
            result["reason"] = "no_resources_required"
            return result

        result["road_access"] = None

        for recommended_unit in recommended_units:
            required_count = self._required_station_count(
                request["risk_level"],
                recommended_unit,
                response_plan,
                request.get("allocation_policy"),
                request.get("hazard"),
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
            selection = self.station_selector.choose(
                stations=stations,
                event_location=event_location,
                incident_id=request["incident_id"],
                recommended_unit=recommended_unit,
                required_count=required_count,
            )
            candidates = selection.candidates
            if selection.police_responsibility is not None:
                result["police_responsibility"] = selection.police_responsibility
            if selection.police_responsibility_error is not None:
                result["errors"].append(
                    {
                        "station_type": station_type,
                        "reason": "police_responsibility_lookup_failed",
                        "message": selection.police_responsibility_error,
                    }
                )
            if selection.routing_failure is not None:
                result["errors"].append(
                    {
                        "station_type": station_type,
                        "reason": "road_ranking_unavailable",
                        "message": selection.routing_failure,
                    }
                )
            if result["road_access"] is None and selection.road_access is not None:
                result["road_access"] = selection.road_access

            try:
                assigned = self._claim_stations(
                    request["incident_id"],
                    recommended_unit,
                    candidates,
                    required_count,
                    request["risk_score"],
                    request["risk_level"],
                    request["allocation_time"],
                    request.get("allocation_policy"),
                    request.get("allocation_basis"),
                    request.get("quantity_source"),
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
                assigned, route_errors = self.routing_service.enrich_routes(
                    assigned,
                    candidates,
                    event_location,
                    request["allocation_time"],
                    selection.routing_failure,
                )
                if (
                    (request.get("allocation_target") or {}).get("target_type")
                    == "hydrometric_station_fallback"
                ):
                    assigned = self.routing_service.mark_unverified_field_access(
                        assigned, event_location
                    )
                result["errors"].extend(route_errors)
            assigned_actions = [
                deepcopy(action)
                for action in response_plan.get("response_actions") or []
                if action.get("responsible_unit") == recommended_unit
            ]
            for station in assigned:
                station["response_actions"] = deepcopy(assigned_actions)
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

    @live_actor("allocator")
    def allocate_processing_results(self, processing_results):
        """Build and allocate every eligible emergency request in one batch.

        Hazard-specific preparation belongs here.  In particular, Flood road
        discovery and Mapbox verification happen inside resource allocation,
        while the scheduler remains a generic orchestration boundary.

        Earthquake preparation moved here when the scheduler became a pure
        delegation. It had been inline in `allocate_resources`, which meant
        adopting that delegation without moving it would have dropped every
        earthquake request silently -- the same defect that kept Flood out
        of allocation, in the other direction.
        """

        requests = []
        bindings = []
        for result in processing_results or []:
            hazard = getattr(result, "hazard", None)
            if getattr(result, "route", None) != "emergency":
                continue

            if hazard == "fire":
                response_plan = getattr(result, "planner_result", None)
                if not isinstance(response_plan, dict):
                    continue
                request = {
                    "incident_id": result.incident_id,
                    "hazard": "fire",
                    "queued_at": result.requested_at,
                    "response_plan": response_plan,
                }
                targeting = None
            elif hazard == "flood":
                if getattr(result, "requires_resource_allocation", None) is False:
                    # De-escalation and unchanged observations preserve every
                    # durable active allocation. They do not recalculate road
                    # targets or request another station assignment.
                    continue
                incident = self.incident_reader(result.incident_id)
                if not isinstance(incident, dict):
                    result.resource_allocation_result = {
                        "incident_id": result.incident_id,
                        "hazard": "flood",
                        "status": "failed",
                        "reason": "flood_incident_input_unavailable",
                        "response_sites": [],
                        "allocation_ready_sites": [],
                        "resource_allocations": {},
                        "errors": [],
                    }
                    continue
                try:
                    targeting = self.flood_target_agent.identify(incident)
                except Exception as error:
                    targeting = {
                        "incident_id": result.incident_id,
                        "hazard": "flood",
                        "status": "failed",
                        "reason": "flood_road_targeting_failed",
                        "response_sites": [],
                        "allocation_ready_sites": [],
                        "resource_allocations": {},
                        "errors": [str(error)],
                    }
                    result.resource_allocation_result = targeting
                    continue
                result.resource_allocation_result = targeting
                request = {
                    "incident_id": result.incident_id,
                    "hazard": "flood",
                    "queued_at": result.requested_at,
                    "flood_targeting": targeting,
                    "risk_assessment": getattr(result, "risk_assessment", None),
                    "response_plan": getattr(result, "planner_result", None),
                }
            elif hazard == "earthquake":
                response_plan = getattr(result, "planner_result", None)
                if not isinstance(response_plan, dict):
                    continue
                # Only a successfully planned earthquake is allocatable. The
                # minimum-response policy commits stations on the plan's
                # authority, and a plan that failed has none to lend.
                if (response_plan.get("metadata") or {}).get(
                    "planning_status"
                ) != "success":
                    continue
                request = {
                    "incident_id": result.incident_id,
                    "hazard": "earthquake",
                    "queued_at": result.requested_at,
                    "response_plan": response_plan,
                    "allocation_policy": EARTHQUAKE_MINIMUM_RESPONSE_POLICY,
                }
                targeting = None

            else:
                continue

            requests.append(request)
            bindings.append((result, hazard, targeting))

        if not requests:
            return {}

        allocations = self.allocate_batch(requests)
        allocations_by_key = {
            (allocation.get("incident_id"), allocation.get("hazard")): allocation
            for allocation in allocations
            if isinstance(allocation, dict) and allocation.get("incident_id")
        }
        allocations_by_incident = {
            allocation["incident_id"]: allocation
            for allocation in allocations
            if isinstance(allocation, dict) and allocation.get("incident_id")
        }

        for result, hazard, targeting in bindings:
            allocation = allocations_by_key.get(
                (result.incident_id, hazard)
            ) or allocations_by_incident.get(result.incident_id)
            if hazard in {"fire", "earthquake"}:
                result.resource_allocation_result = allocation
                continue
            combined = dict(targeting)
            combined["station_allocation"] = allocation
            combined["resource_allocations"] = (
                allocation.get("allocated_units", {})
                if isinstance(allocation, dict)
                else {}
            )
            combined["allocation_target"] = (
                allocation.get("allocation_target")
                if isinstance(allocation, dict)
                else None
            )
            result.resource_allocation_result = combined

        return allocations_by_incident

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
