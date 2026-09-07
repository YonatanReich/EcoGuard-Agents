from agents.fire_detection_agent import FireDetectionAgent
from agents.risk_analysis_agent import RiskAnalysisAgent
from agents.response_planning_agent import ResponsePlanningAgent
from agents.resource_allocation_agent import ResourceAllocationAgent


class FireCoordinator:
    def __init__(self, *, detection_agent=None, risk_agent=None, planning_agent=None, allocation_agent=None):
        self.fire_detection_agent = detection_agent if detection_agent is not None else FireDetectionAgent()
        self.risk_agent = risk_agent if risk_agent is not None else RiskAnalysisAgent()
        self.planning_agent = planning_agent if planning_agent is not None else ResponsePlanningAgent()
        self.resource_allocation_agent = allocation_agent if allocation_agent is not None else ResourceAllocationAgent()

    def run_event_pipeline(
        self,
        latitude: float,
        longitude: float,
        event_type: str = "fire",
        *,
        day_range: int = 2,
        radius_km: float = 5.0,
        include_analysis: bool = True,
    ):
        """
        Runs the full end-to-end pipeline for a fire event.
        """
        if not isinstance(event_type, str) or event_type.lower() != "fire":
            return self._build_final_response(
                status="error",
                message=f"Unsupported event type: '{event_type}'. Only 'fire' is supported."
            )

        detection_result = self.fire_detection_agent.detect_fire(
            latitude=latitude,
            longitude=longitude,
            day_range=day_range,
            max_hotspot_distance_km=radius_km,
        )

        is_detected = detection_result.get("detected")

        if is_detected is None:
            return self._build_final_response(
                status="error",
                message="Detection service is currently unavailable. Could not verify event status.",
                detection=detection_result,
            )
        elif is_detected is False:
            return self._build_final_response(
                status="no_event",
                message="No fire event detected at this location.",
                detection=detection_result,
            )

        if not include_analysis:
            return self._build_final_response(
                status="success",
                message=None,
                detection=detection_result,
            )

        risk_result = self.risk_agent.analyze_event(detection_result)
        
        if risk_result.get("metadata", {}).get("analysis_status") != "success":
            return self._build_final_response(
                status="partial",
                message="Risk analysis failed or returned incomplete data.",
                detection=detection_result,
                risk_analysis=risk_result,
            )

        planning_result = self.planning_agent.plan_response(
            detection_result, risk_result
        )

        if planning_result.get("metadata", {}).get("planning_status") != "success":
            return self._build_final_response(
                status="partial",
                message="Response planning failed.",
                detection=detection_result,
                risk_analysis=risk_result,
                planning=planning_result,
            )

        allocation_result = self.resource_allocation_agent.allocate_resources(
            detection_result.get("location"),
            detection_result.get("geospatial_context"),
            planning_result,
        )

        final_status = "success" if allocation_result.get("status") == "success" else "partial"

        return self._build_final_response(
            status=final_status,
            message=None,
            detection=detection_result,
            risk_analysis=risk_result,
            planning=planning_result,
            allocation=self._clean_allocation(allocation_result)
        )

    @staticmethod
    def _clean_allocation(allocation):
        """Remove internal OpenStreetMap identifiers from coordinator output."""
        if not isinstance(allocation, dict):
            return allocation

        cleaned_units = {}
        for unit_type, facilities in (allocation.get("allocated_units") or {}).items():
            cleaned_units[unit_type] = [
                {
                    key: value
                    for key, value in facility.items()
                    if key not in {"osm_id", "osm_type"}
                }
                for facility in facilities
            ]

        return {**allocation, "allocated_units": cleaned_units}

    def _build_final_response(self, status: str, message: str | None, detection=None, risk_analysis=None, planning=None, allocation=None):
        """
        Helper method to ensure a consistent, single structured response shape 
        for all pipeline outcomes.
        """
        return {
            "status": status,
            "message": message,
            "event_type": "fire",
            "location": detection.get("location") if detection else None,
            "detection": detection,
            "risk_analysis": risk_analysis,
            "planning": planning,
            "allocated_resources": allocation,
        }