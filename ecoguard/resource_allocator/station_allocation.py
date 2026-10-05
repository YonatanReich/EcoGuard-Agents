"""Persist station claims and present their durable allocation state."""

from datetime import datetime


class StationAllocationService:
    """Own station-allocation persistence and result shaping."""

    def __init__(self, *, allocation_repository, station_catalog):
        self.allocation_repository = allocation_repository
        self.station_catalog = station_catalog

    def claim(
        self,
        *,
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
        """Atomically claim candidates and return enriched allocation views."""
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
        allocations = self.allocation_repository.claim_stations(**claim)
        return [self._allocation_view(allocation) for allocation in allocations]

    def release_incident(
        self,
        incident_id,
        *,
        released_at,
        reason="incident_closed",
    ):
        """Release every station assigned to an incident; safe to call twice."""
        allocations = self.allocation_repository.release_incident(
            str(incident_id),
            released_at=released_at,
            reason=reason,
        )
        released = [
            self._allocation_view(allocation, status="released")
            for allocation in allocations
        ]
        return sorted(released, key=lambda station: station["distance_km"])

    def active_claims(self):
        """Return raw active claims for availability checks."""
        return self.allocation_repository.active_allocations()

    def active_allocations(self):
        """Return active claims grouped by incident and enriched with stations."""
        grouped = {}
        for allocation in self.active_claims():
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

    def _allocation_view(self, allocation, status="assigned"):
        """Combine a durable allocation with its cached station details."""
        station_key = (
            allocation["recommended_unit"],
            allocation["station_id"],
        )
        station = self.station_catalog.stations_by_key.get(station_key, {})
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
