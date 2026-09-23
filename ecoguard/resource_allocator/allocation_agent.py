"""Select and reserve nearby stations for emergency response requests."""

from ecoguard.shared.activity import live_actor
from copy import deepcopy

from ecoguard.database.repositories.resource_allocations import (
    ResourceAllocationRepository,
)
from ecoguard.database.repositories.towns import (
    responsible_police_stations,
    town_at_location,
)
from ecoguard.coordinator import incidents as incident_store
from ecoguard.resource_allocator.allocation_routing import AllocationRoutingService
from ecoguard.resource_allocator.geo import coordinates
from ecoguard.resource_allocator.mapbox_client import MapboxClient
from ecoguard.resource_allocator.flood_road_targets import FloodRoadTargetAgent
from ecoguard.resource_allocator.station_allocation import StationAllocationService
from ecoguard.resource_allocator.station_catalog import (
    STATION_TYPES,
    StationCatalog,
)
from ecoguard.resource_allocator.station_selection import StationSelectionService
from ecoguard.resource_allocator.request_preparation import (
    AllocationRequestPreparer,
    EARTHQUAKE_MINIMUM_RESPONSE_POLICY,
    normalize_utc,
)

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
        self.routing_client = routing_client or MapboxClient()
        self.routing_service = AllocationRoutingService(self.routing_client)
        allocation_repository = (
            allocation_repository or ResourceAllocationRepository()
        )
        self.police_responsibility_reader = (
            police_responsibility_reader or responsible_police_stations
        )
        self.town_reader = town_reader or town_at_location
        self.flood_target_agent = flood_target_agent or FloodRoadTargetAgent(
            mapbox_client=self.routing_client
        )
        self.incident_reader = incident_reader or incident_store.incident_by_id
        self.station_catalog = StationCatalog(station_readers)
        self.station_allocator = StationAllocationService(
            allocation_repository=allocation_repository,
            station_catalog=self.station_catalog,
        )
        self.station_selector = StationSelectionService(
            active_allocations_reader=self.station_allocator.active_claims,
            police_responsibility_reader=self.police_responsibility_reader,
            routing_service=self.routing_service,
        )
        self.request_preparer = AllocationRequestPreparer()

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
            catalog_error = self.station_catalog.errors.get(recommended_unit)
            stations = self.station_catalog.catalogs.get(recommended_unit, [])
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
                assigned = self.station_allocator.claim(
                    incident_id=request["incident_id"],
                    recommended_unit=recommended_unit,
                    candidates=candidates,
                    required_count=required_count,
                    risk_score=request["risk_score"],
                    risk_level=request["risk_level"],
                    allocated_at=request["allocation_time"],
                    allocation_policy=request.get("allocation_policy"),
                    allocation_basis=request.get("allocation_basis"),
                    quantity_source=request.get("quantity_source"),
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
        current_time = normalize_utc(now)
        prepared = []
        terminal_results = []

        for request in requests or []:
            try:
                item = self.request_preparer.prepare(request, current_time)
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
        return self.station_allocator.release_incident(
            incident_id,
            released_at=normalize_utc(released_at),
            reason=reason,
        )

    def active_allocations(self):
        """Return a read-only snapshot of durable active allocations."""
        return self.station_allocator.active_allocations()
