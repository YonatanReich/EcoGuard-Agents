"""Normalize hazard inputs into station-allocation requests."""

import math
from copy import deepcopy
from datetime import datetime, timezone

from ecoguard.analyzers.flood.risk_analysis_schemas import FloodRiskAssessment


RISK_LEVELS = frozenset({"low", "medium", "high", "critical"})
OPERATIONAL_RISK_SEMANTICS = "detected_event_operational_risk"

EARTHQUAKE_MINIMUM_RESPONSE_POLICY = "earthquake_minimum_response_v1"
EARTHQUAKE_ALLOCATION_BASIS = "protocol_recommended_units"
EARTHQUAKE_QUANTITY_SOURCE = "ecoguard_minimum_response_policy"

PLANNING_FAILURE_POLICE_POLICY = "planning_failure_police_minimum_v1"
PLANNING_FAILURE_ALLOCATION_BASIS = "planner_unavailable_emergency_minimum"
PLANNING_FAILURE_QUANTITY_SOURCE = "ecoguard_fallback_policy"

TIMEFRAME_PRIORITY = {
    "ongoing": 0,
    "within_6_hours": 1,
    "within_1_hour": 2,
    "immediate": 3,
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


def normalize_utc(value=None):
    """Normalize a datetime or ISO string to an aware UTC datetime."""
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("queued_at must be an ISO timestamp with a UTC offset")
    return value.astimezone(timezone.utc)


class AllocationRequestPreparer:
    """Prepare Fire, Flood, and Earthquake inputs for one allocation queue."""

    def prepare(self, item, now):
        """Return a normalized allocation request or a terminal result."""
        if not isinstance(item, dict):
            raise ValueError("allocation request must be an object")

        if item.get("allocation_policy") == PLANNING_FAILURE_POLICE_POLICY:
            return self._prepare_planning_failure_police(item, now)

        # Flood first resolves its operational destination from road or gauge
        # evidence. Every other hazard already arrives with a dispatch plan.
        if item.get("hazard") == "flood":
            return self._prepare_flood(item, now)
        return self._prepare_response_plan(item, now)

    def _prepare_planning_failure_police(self, item, now):
        """Build the explicit one-police-station emergency fallback.

        This is an allocation policy, not a successful response plan. The
        original Planner status remains on the synthetic plan so downstream
        consumers can see why the minimum allocation was used.
        """
        incident_id = str(item.get("incident_id") or "").strip()
        if not incident_id:
            raise ValueError("incident_id is required")

        planner_status = str(item.get("planner_status") or "failed")
        if planner_status not in {"failed", "skipped"}:
            raise ValueError(
                "planning-failure fallback requires a failed or skipped plan"
            )

        location = item.get("location")
        if not isinstance(location, dict):
            raise ValueError("planning-failure fallback requires a location")
        latitude = location.get("latitude")
        longitude = location.get("longitude")
        if (
            not isinstance(latitude, (int, float))
            or isinstance(latitude, bool)
            or not math.isfinite(latitude)
            or not isinstance(longitude, (int, float))
            or isinstance(longitude, bool)
            or not math.isfinite(longitude)
        ):
            raise ValueError(
                "planning-failure fallback requires finite coordinates"
            )

        risk_context = item.get("risk_context")
        if not isinstance(risk_context, dict):
            raise ValueError(
                "planning-failure fallback requires operational risk"
            )
        if risk_context.get("risk_semantics") != OPERATIONAL_RISK_SEMANTICS:
            raise ValueError(
                "planning-failure fallback requires operational risk semantics"
            )
        risk_score, risk_level = self._validated_risk(risk_context)
        queued_at = normalize_utc(item.get("queued_at") or now)
        waited_seconds = max(0, (now - queued_at).total_seconds())

        fallback_plan = {
            "metadata": {
                "planning_status": planner_status,
                "reason": item.get("planner_reason") or "planning_unavailable",
                "agent": "deterministic_planning_failure_fallback",
            },
            "event_id": incident_id,
            "hazard_type": str(item.get("hazard") or "unknown"),
            "location": {
                "latitude": float(latitude),
                "longitude": float(longitude),
            },
            "responding_to": dict(risk_context),
            "recommended_units": ["police"],
            "response_actions": [{
                "action": (
                    "Establish police presence and coordinate an initial "
                    "on-scene assessment while the response plan is unavailable."
                ),
                "responsible_unit": "police",
                "timeframe": "immediate",
            }],
        }
        return {
            "incident_id": incident_id,
            "hazard": str(item.get("hazard") or "unknown"),
            "response_plan": fallback_plan,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "queued_at": queued_at,
            "allocation_time": now,
            "urgency": TIMEFRAME_PRIORITY["immediate"],
            "effective_priority": risk_score + int(waited_seconds // 300),
            "allocation_policy": PLANNING_FAILURE_POLICE_POLICY,
            "allocation_basis": PLANNING_FAILURE_ALLOCATION_BASIS,
            "quantity_source": PLANNING_FAILURE_QUANTITY_SOURCE,
        }

    @staticmethod
    def _planning_status(response_plan):
        """Read the planner outcome used to decide whether allocation may run."""
        return str(
            (response_plan.get("metadata") or {}).get("planning_status") or ""
        )

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
    def _flood_site_priority(site):
        """Rank eligible flood sites by severity and operational road impact."""
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

    def _prepare_flood(self, item, now):
        """Resolve Flood evidence before applying the common plan validation."""
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

        target = self._resolve_flood_target(
            incident_id=incident_id,
            targeting=targeting,
        )
        if "terminal" in target:
            return target

        if risk.hydrologic_severity_level != target["severity"]:
            raise ValueError(
                "flood risk severity does not match targeting evidence"
            )

        response_plan = self._build_flood_response_plan(
            item=item,
            now=now,
            risk=risk,
            target=target,
        )

        # Call the common core directly. This avoids re-entering the hazard
        # dispatcher and removes the old synthetic `prepared_flood` hazard.
        prepared = self._prepare_response_plan(
            {
                "incident_id": incident_id,
                "hazard": "flood",
                "queued_at": item.get("queued_at"),
                "response_plan": response_plan,
            },
            now,
        )
        prepared["allocation_target"] = target["allocation_target"]
        return prepared

    def _resolve_flood_target(self, *, incident_id, targeting):
        """Choose a verified road destination or a hydrometric fallback."""
        ready_sites = self._eligible_flood_sites(targeting)
        if ready_sites:
            return self._verified_road_target(
                incident_id=incident_id,
                ready_sites=ready_sites,
            )
        return self._hydrometric_fallback_target(
            incident_id=incident_id,
            targeting=targeting,
        )

    @staticmethod
    def _eligible_flood_sites(targeting):
        """Return only road sites that are ready to receive an allocation."""
        return [
            site
            for site in targeting.get("allocation_ready_sites") or []
            if isinstance(site, dict)
            and site.get("allocation_eligible") is True
            and isinstance(site.get("allocation_location"), dict)
        ]

    def _verified_road_target(self, *, incident_id, ready_sites):
        """Build the allocation context for the highest-priority road site."""
        primary = max(ready_sites, key=self._flood_site_priority)
        severity = max(
            3,
            min(
                6,
                max(
                    int(site.get("severity_level") or 3)
                    for site in ready_sites
                ),
            ),
        )
        location = primary["allocation_location"]
        return {
            "event_id": f"{incident_id}:flood-road-target",
            "severity": severity,
            "location": location,
            "requirements": {"police": 1},
            "primary_target_id": primary.get("target_id"),
            "fallback_reason": None,
            "allocation_target": {
                "target_id": primary.get("target_id"),
                "target_type": "verified_road_site",
                "road": dict(primary.get("road") or {}),
                "allocation_location": dict(location),
                "covered_response_site_ids": [
                    site.get("target_id") for site in ready_sites
                ],
            },
        }

    def _hydrometric_fallback_target(self, *, incident_id, targeting):
        """Build an explicitly marked fallback from hydrometric evidence."""
        sources = [
            source
            for source in targeting.get("hydrometric_sources") or []
            if isinstance(source, dict)
            and isinstance(source.get("station"), dict)
        ]
        if not sources:
            return self._missing_flood_location(incident_id)

        primary_source = max(
            sources,
            key=lambda source: int(
                (source.get("station") or {}).get("severity_level") or 3
            ),
        )
        station = primary_source["station"]
        severity = max(3, min(6, int(station.get("severity_level") or 3)))
        location = {
            "latitude": float(station["latitude"]),
            "longitude": float(station["longitude"]),
        }
        primary_target_id = f"hydrometric-station-{station.get('id')}"
        return {
            "event_id": f"{incident_id}:flood-station-fallback",
            "severity": severity,
            "location": location,
            "requirements": {"police": 1},
            "primary_target_id": primary_target_id,
            "fallback_reason": "no_verified_flood_response_site",
            "allocation_target": {
                "target_id": primary_target_id,
                "target_type": "hydrometric_station_fallback",
                "source_station_id": station.get("id"),
                "allocation_location": dict(location),
                "covered_response_site_ids": [],
                "requires_road_access_resolution": True,
            },
        }

    def _build_flood_response_plan(self, *, item, now, risk, target):
        """Use the Planner plan when valid, otherwise build a safe fallback."""
        planner_plan = item.get("response_plan")
        if (
            isinstance(planner_plan, dict)
            and self._planning_status(planner_plan) == "success"
        ):
            return self._adapt_planner_flood_plan(
                planner_plan=planner_plan,
                risk=risk,
                target=target,
            )

        # Targeting and risk evidence already establish the destination,
        # severity, and responsible unit when the Planner is unavailable.
        return self._flood_fallback_plan(
            item=item,
            now=now,
            event_id=target["event_id"],
            location=target["location"],
            risk=risk,
            severity=target["severity"],
            requirements=target["requirements"],
            primary_target_id=target["primary_target_id"],
            fallback_reason=target["fallback_reason"],
        )

    @staticmethod
    def _adapt_planner_flood_plan(*, planner_plan, risk, target):
        """Apply verified Flood evidence to a successful Planner response."""
        response_plan = deepcopy(planner_plan)
        planned_risk = response_plan.get("responding_to") or {}
        if (
            planned_risk.get("risk_score") != risk.risk_score
            or str(planned_risk.get("risk_level") or "").lower()
            != risk.risk_level
        ):
            raise ValueError("flood response plan does not match risk analyzer")

        # The Planner owns units and instructions. Flood targeting owns the
        # physical destination used for station routing.
        response_plan["event_id"] = target["event_id"]
        response_plan["location"] = {
            "latitude": float(target["location"]["latitude"]),
            "longitude": float(target["location"]["longitude"]),
        }
        response_plan["responding_to"] = {
            **planned_risk,
            "primary_target_id": target["primary_target_id"],
            "fallback_reason": target["fallback_reason"],
        }
        return response_plan

    @staticmethod
    def _missing_flood_location(incident_id):
        """Return the terminal result used when Flood has no routable target."""
        return {
            "terminal": {
                "incident_id": incident_id,
                "event_id": f"{incident_id}:flood-station-fallback",
                "hazard": "flood",
                "status": "skipped",
                "reason": "hydrometric_station_location_unavailable",
                "allocated_units": {},
                "requirements": {
                    "police": {
                        "requested": 1,
                        "assigned": 0,
                        "shortfall": 1,
                    }
                },
                "shortages": {"police_station": 1},
                "unsupported_units": [],
                "errors": [],
                "allocation_target": None,
            }
        }

    @staticmethod
    def _flood_fallback_plan(
        *,
        item,
        now,
        event_id,
        location,
        risk,
        severity,
        requirements,
        primary_target_id,
        fallback_reason,
    ):
        """Build a deterministic response plan from validated Flood evidence."""
        return {
            "metadata": {
                "planning_status": "success",
                "timestamp": normalize_utc(
                    item.get("queued_at") or now
                ).isoformat(),
                "agent": "deterministic_flood_station_fallback",
            },
            "event_id": event_id,
            "location": {
                "latitude": float(location["latitude"]),
                "longitude": float(location["longitude"]),
            },
            "responding_to": {
                "risk_semantics": OPERATIONAL_RISK_SEMANTICS,
                "risk_score": risk.risk_score,
                "risk_level": risk.risk_level,
                "severity_level": severity,
                "risk_confidence": risk.confidence,
                "primary_target_id": primary_target_id,
                "fallback_reason": fallback_reason,
            },
            "recommended_units": list(requirements),
            "response_actions": [
                {
                    "action": (
                        "Secure access to the identified flood response site."
                    ),
                    "timeframe": "immediate",
                    "responsible_unit": unit,
                }
                for unit in requirements
            ],
        }

    def _prepare_response_plan(self, item, now):
        """Validate the response-plan contract shared by every hazard."""
        # The Coordinator wrapper supplies the canonical incident identity and
        # queue time. Standalone callers may pass the Planner plan directly.
        response_plan = item.get("response_plan", item)
        if not isinstance(response_plan, dict):
            raise ValueError("response_plan must be an object")

        incident_id = str(
            item.get("incident_id") or response_plan.get("event_id") or ""
        ).strip()
        if not incident_id:
            raise ValueError("incident_id is required")

        # Failed and skipped plans are terminal outcomes, not malformed
        # allocation requests. Preserve their reason for the caller.
        planning_status = self._planning_status(response_plan)
        if planning_status not in {"success", "failed", "skipped"}:
            raise ValueError("response plan has an invalid planning_status")
        if planning_status != "success":
            return self._terminal_plan_result(
                incident_id,
                response_plan,
                planning_status,
            )

        allocation_policy = item.get("allocation_policy")
        if allocation_policy is not None:
            return self._prepare_earthquake(
                item,
                response_plan,
                incident_id,
                now,
            )

        responding_to = response_plan.get("responding_to") or {}
        if responding_to.get("risk_semantics") != OPERATIONAL_RISK_SEMANTICS:
            raise ValueError("response plan does not contain operational risk")

        risk_score, risk_level = self._validated_risk(responding_to)
        self._validate_response_actions(response_plan)
        metadata = response_plan.get("metadata") or {}
        queued_at = normalize_utc(
            item.get("queued_at") or metadata.get("timestamp") or now
        )
        waited_seconds = max(0, (now - queued_at).total_seconds())

        # All hazards enter one priority queue. Aging adds one point every five
        # minutes so an older valid request eventually advances.
        return {
            "incident_id": incident_id,
            "hazard": str(item.get("hazard") or "fire"),
            "response_plan": response_plan,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "queued_at": queued_at,
            "allocation_time": now,
            "urgency": self._urgency(response_plan),
            "effective_priority": risk_score + int(waited_seconds // 300),
            "allocation_policy": None,
            "allocation_basis": None,
            "quantity_source": None,
        }

    def _prepare_earthquake(self, item, response_plan, incident_id, now):
        """Apply the product's minimum Earthquake station policy."""
        if item.get("allocation_policy") != EARTHQUAKE_MINIMUM_RESPONSE_POLICY:
            raise ValueError("unsupported allocation policy")
        if response_plan.get("hazard_type") != "earthquake":
            raise ValueError(
                "earthquake allocation policy requires an earthquake plan"
            )

        metadata = response_plan.get("metadata") or {}
        queued_at = normalize_utc(
            item.get("queued_at") or metadata.get("timestamp") or now
        )
        responding_to = response_plan.get("responding_to") or {}
        risk_score, risk_level = self._validated_risk(responding_to)
        waited_seconds = max(0, (now - queued_at).total_seconds())

        # The policy fixes quantity at one station per requested unit type.
        # Queue position still uses the same 0-100 operational risk and aging
        # calculation as Fire and Flood.
        return {
            "incident_id": incident_id,
            "hazard": "earthquake",
            "response_plan": response_plan,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "queued_at": queued_at,
            "allocation_time": now,
            "urgency": self._urgency(response_plan),
            "effective_priority": risk_score + int(waited_seconds // 300),
            "allocation_policy": EARTHQUAKE_MINIMUM_RESPONSE_POLICY,
            "allocation_basis": EARTHQUAKE_ALLOCATION_BASIS,
            "quantity_source": EARTHQUAKE_QUANTITY_SOURCE,
        }

    @staticmethod
    def _validated_risk(responding_to):
        """Validate and normalize the shared operational-risk fields."""
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
        return float(risk_score), risk_level

    @staticmethod
    def _validate_response_actions(response_plan):
        """Ensure every requested unit has at least one valid instruction."""
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
                raise ValueError(
                    "each response action must contain an instruction"
                )
            if action.get("timeframe") not in TIMEFRAME_PRIORITY:
                raise ValueError(
                    "each response action must contain a valid timeframe"
                )
            action_units.add(responsible_unit)

        if set(recommended_units) - action_units:
            raise ValueError(
                "each recommended unit must have at least one response action"
            )

    @staticmethod
    def _terminal_plan_result(incident_id, response_plan, planning_status):
        """Preserve a Planner failure or skip as a terminal allocation result."""
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
