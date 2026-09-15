"""Select nearby facilities for the units requested by a response plan."""

import math

from ecoguard.shared.geospatial_context import GeospatialContextAgent

RADIUS_BY_RISK_KM = {
    "low": 5,
    "medium": 10,
    "high": 15,
    "critical": 20,
}
FALLBACK_RADII_KM = (30, 50)

UNIT_TYPES = {
    "fire_department": (
        "fire_station",
        "fire_stations",
        "nearby_fire_stations",
    ),
    "police": (
        "police_station",
        "police_stations",
        "nearby_police_stations",
    ),
    "medical_services": (
        "hospital",
        "hospitals",
        "nearby_hospitals",
    ),
}

class ResourceAllocationAgent:

    def __init__(self, geospatial_agent=None):
        self.geospatial_agent = geospatial_agent or GeospatialContextAgent()

    @staticmethod
    def _coordinates(location):
        """Validate a location and return its coordinates."""
        if not isinstance(location, dict):
            raise ValueError("location must be an object")

        latitude = location.get("latitude")
        longitude = location.get("longitude")

        for value in (latitude, longitude):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
            ):
                raise ValueError("location must contain valid coordinates")

        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("coordinates are outside their valid ranges")

        return float(latitude), float(longitude)

    @staticmethod
    def _haversine_distance(lat1, lon1, lat2, lon2):
        """Calculate the distance between two coordinates in kilometers."""
        lon1, lat1, lon2, lat2 = map(
            math.radians, (lon1, lat1, lon2, lat2)
        )
        longitude_delta = lon2 - lon1
        latitude_delta = lat2 - lat1
        value = (
            math.sin(latitude_delta / 2) ** 2
            + math.cos(lat1)
            * math.cos(lat2)
            * math.sin(longitude_delta / 2) ** 2
        )
        return 6371 * 2 * math.asin(math.sqrt(value))

    def _prepare_facilities(self, facilities, event_lat, event_lon, facility_type, radius_km):
        """Return valid, unique facilities sorted by distance."""
        unique = {}

        for source in facilities:
            try:
                facility_lat, facility_lon = self._coordinates(source)
            except ValueError:
                continue

            distance = self._haversine_distance(
                event_lat, event_lon, facility_lat, facility_lon
            )
            if distance > radius_km:
                continue

            facility = source.copy()
            facility["unit_type"] = facility_type
            facility["distance_km"] = distance

            identity = (
                facility.get("osm_type"),
                facility.get("osm_id"),
            )
            if identity[1] is None:
                identity = (
                    str(facility.get("name", "")).casefold(),
                    round(facility_lat, 6),
                    round(facility_lon, 6),
                )

            existing = unique.get(identity)
            if existing is None or distance < existing["distance_km"]:
                unique[identity] = facility

        return sorted(unique.values(), key=lambda item: item["distance_km"])

    def _search(
        self,
        event_lat,
        event_lon,
        facility_type,
        radius_km,
        known_facilities,
    ):
        """Search one radius, preserving known facilities if the search fails."""
        error = None
        fetched = []

        try:
            response = self.geospatial_agent.fetch_facilities(
                event_lat, event_lon, facility_type, radius_km
            )
            if response.get("status") != "success":
                raise RuntimeError(response.get("error") or "facility search failed")
            fetched = response.get("facilities") or []
        except Exception as exc:
            error = str(exc)

        facilities = self._prepare_facilities(
            [*known_facilities, *fetched],
            event_lat,
            event_lon,
            facility_type,
            radius_km,
        )
        return facilities, error

    @staticmethod
    def _select(facilities, risk_level, expanded):
        """Select one facility for lower risk, or all for higher risk."""
        high_risk = risk_level in ("high", "critical")
        selected = facilities if high_risk else facilities[:1]

        if expanded:
            reason = (
                "within_expanded_radius"
                if high_risk
                else "nearest_found_in_expanded_search"
            )
        else:
            reason = "within_initial_radius" if high_risk else "nearest_in_initial_radius"

        return [{**facility, "selection_reason": reason} for facility in selected]

    def _allocate_type(
        self,
        event_lat,
        event_lon,
        risk_level,
        facility_type,
        known_facilities,
    ):
        radii = (
            RADIUS_BY_RISK_KM[risk_level],
            *FALLBACK_RADII_KM,
        )

        for index, radius_km in enumerate(radii):
            facilities, error = self._search(
                event_lat,
                event_lon,
                facility_type,
                radius_km,
                known_facilities,
            )
            if facilities or error is not None:
                return self._select(facilities, risk_level, index > 0), error

        return [], None

    def allocate_resources(self, event_location, geospatial_context, response_plan):
        """Allocate facilities according to risk and recommended unit types."""
        event_lat, event_lon = self._coordinates(event_location)
        geospatial_context = geospatial_context or {}
        response_plan = response_plan or {}
        risk_level = str(
            (response_plan.get("responding_to") or {}).get("risk_level") or ""
        ).lower()
        recommended_units = list(
            dict.fromkeys(response_plan.get("recommended_units") or [])
        )

        allocated_units = {}
        result = {
            "status": "success",
            "allocated_units": allocated_units,
            "nearby_roads": geospatial_context.get("nearby_roads") or [],
            "shortages": {},
            "unsupported_units": [],
            "errors": [],
            "alert_radius_km": RADIUS_BY_RISK_KM.get(risk_level),
            "allocation_needed": bool(recommended_units),
        }

        if not recommended_units:
            result["reason"] = "no_resources_required"
            return result

        if risk_level not in RADIUS_BY_RISK_KM:
            result["status"] = "requirements_unavailable"
            result["reason"] = "risk_level_unavailable"
            return result

        for recommended_unit in recommended_units:
            mapping = UNIT_TYPES.get(recommended_unit)
            if mapping is None:
                result["unsupported_units"].append(recommended_unit)
                continue

            facility_type, output_key, context_key = mapping
            facilities, error = self._allocate_type(
                event_lat,
                event_lon,
                risk_level,
                facility_type,
                geospatial_context.get(context_key) or [],
            )
            allocated_units[output_key] = facilities

            if error is not None:
                result["errors"].append(
                    {
                        "facility_type": facility_type,
                        "reason": "search_failed",
                        "message": error,
                    }
                )
            elif not facilities:
                result["shortages"][facility_type] = 1

        if result["shortages"] or result["unsupported_units"] or result["errors"]:
            result["status"] = "partial"

        result["rationale"] = (
            f"Allocated facilities using the {risk_level} risk radius and "
            "fallback radii only when needed."
        )
        return result
