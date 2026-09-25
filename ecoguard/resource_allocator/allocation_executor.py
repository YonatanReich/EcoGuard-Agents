"""Execute prepared requests through station selection and allocation."""

from copy import deepcopy

from ecoguard.resource_allocator.geo import coordinates
from ecoguard.resource_allocator.station_catalog import STATION_TYPES


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

STATIONS_PER_REQUESTED_UNIT = 1


class AllocationExecutor:
    """Run the allocation flow after request validation and normalization."""

    def __init__(
        self,
        *,
        station_catalog,
        station_selector,
        station_allocator,
        routing_service,
        town_reader,
    ):
        self.station_catalog = station_catalog
        self.station_selector = station_selector
        self.station_allocator = station_allocator
        self.routing_service = routing_service
        self.town_reader = town_reader

    def execute(self, request):
        """Execute one prepared request and return its allocation result."""
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
            # A recommendation selects one responsible station of each unit
            # type. The station decides how many internal teams to dispatch.
            required_count = STATIONS_PER_REQUESTED_UNIT
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
