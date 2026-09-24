"""Select and reserve nearby stations for emergency response requests."""

from ecoguard.shared.activity import live_actor

from ecoguard.database.repositories.resource_allocations import (
    ResourceAllocationRepository,
)
from ecoguard.database.repositories.towns import (
    responsible_police_stations,
    town_at_location,
)
from ecoguard.coordinator import incidents as incident_store
from ecoguard.resource_allocator.allocation_executor import AllocationExecutor
from ecoguard.resource_allocator.allocation_routing import AllocationRoutingService
from ecoguard.resource_allocator.mapbox_client import MapboxClient
from ecoguard.resource_allocator.flood_road_targets import FloodRoadTargetAgent
from ecoguard.resource_allocator.station_allocation import StationAllocationService
from ecoguard.resource_allocator.station_catalog import StationCatalog
from ecoguard.resource_allocator.station_selection import StationSelectionService
from ecoguard.resource_allocator.request_preparation import (
    AllocationRequestPreparer,
    EARTHQUAKE_MINIMUM_RESPONSE_POLICY,
    PLANNING_FAILURE_POLICE_POLICY,
    normalize_utc,
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
        town_reader = town_reader or town_at_location
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
        self.allocation_executor = AllocationExecutor(
            station_catalog=self.station_catalog,
            station_selector=self.station_selector,
            station_allocator=self.station_allocator,
            routing_service=self.routing_service,
            town_reader=town_reader,
        )

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
        allocated = [self.allocation_executor.execute(item) for item in prepared]
        return [*allocated, *terminal_results]

    @staticmethod
    def _planner_status(result, response_plan):
        """Read the explicit handler status before consulting plan metadata."""
        status = getattr(result, "planner_status", None)
        if status:
            return str(status)
        if isinstance(response_plan, dict):
            return str(
                (response_plan.get("metadata") or {}).get("planning_status")
                or "failed"
            )
        return "failed"

    def _planning_failure_request(self, result):
        """Forward analyzer-owned location and risk to the fallback policy."""
        hazard = str(getattr(result, "hazard", None) or "unknown")
        context = getattr(result, "fallback_allocation_context", None)
        if not isinstance(context, dict):
            context = {}

        response_plan = getattr(result, "planner_result", None)
        return {
            "incident_id": result.incident_id,
            "hazard": hazard,
            "queued_at": result.requested_at,
            "allocation_policy": PLANNING_FAILURE_POLICE_POLICY,
            "planner_status": self._planner_status(result, response_plan),
            "planner_reason": getattr(result, "failure_reason", None),
            "location": context.get("location"),
            "risk_context": context.get("risk_context"),
        }

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
                planning_status = self._planner_status(result, response_plan)
                if planning_status in {"failed", "skipped"}:
                    if getattr(
                        result, "requires_resource_allocation", None
                    ) is False:
                        continue
                    request = self._planning_failure_request(result)
                elif (
                    isinstance(response_plan, dict)
                    and planning_status == "success"
                ):
                    request = {
                        "incident_id": result.incident_id,
                        "hazard": "fire",
                        "queued_at": result.requested_at,
                        "response_plan": response_plan,
                    }
                else:
                    continue
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
                planning_status = self._planner_status(result, response_plan)
                if (
                    isinstance(response_plan, dict)
                    and planning_status == "success"
                ):
                    request = {
                        "incident_id": result.incident_id,
                        "hazard": "earthquake",
                        "queued_at": result.requested_at,
                        "response_plan": response_plan,
                        "allocation_policy": EARTHQUAKE_MINIMUM_RESPONSE_POLICY,
                    }
                elif planning_status in {"failed", "skipped"}:
                    if getattr(
                        result, "requires_resource_allocation", None
                    ) is False:
                        continue
                    request = self._planning_failure_request(result)
                else:
                    continue
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
