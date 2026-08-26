"""
Fire Coordinator

Responsible for orchestrating the complete, end-to-end fire event pipeline.
It replaces direct agent calls in the FastAPI backend and ensures data flows
sequentially through the five pipeline stages.

How it works:
    1. Validates the event type, explicitly rejecting non-fire events with an 
       "unsupported event type" message.
    2. Executes Data Collection & Event Detection to gather live satellite, 
       weather, and geospatial data.
    3. Executes Risk Analysis to determine risk levels based on protocols.
    4. Executes Resource Allocation to select the nearest response units using 
       real geospatial data.
    5. Executes Response Planning to produce a protocol-grounded action plan.
    6. Returns a single, structured, non-hardcoded result containing the full chain.

Consumed by:
    backend.main (FastAPI endpoints)
"""

from agents.fire_detection_agent import FireDetectionAgent
from agents.resource_allocation_agent import ResourceAllocationAgent
from agents.risk_analysis_agent import analyze_event

class FireCoordinator:
    def __init__(self):
        # initialize agents
        self.fire_detection_agent = FireDetectionAgent()
        self.resource_allocation_agent = ResourceAllocationAgent()

    def run_event_pipeline(self, latitude: float, longitude: float, event_type: str = "fire"):
        """
        Runs the full 5-stage pipeline for a fire event.
        """
        # Ensure event type. TODO: extend to other events
        if event_type.lower() != "fire":
            return {
                "status": "error", 
                "message": f"Unsupported event type: '{event_type}'. Only 'fire' is supported."
            }

        # ---------------------------------------------------------
        # Data Collection + Event Detection
        # ---------------------------------------------------------
        detection_result = self.fire_detection_agent.detect_fire(
            latitude=latitude, 
            longitude=longitude
        )

        # TODO: Hardcoded data for testing. remove
        # from agents.geospatial_context_agent import GeospatialContextAgent
        # temp_geo_agent = GeospatialContextAgent()
        # geo_data = temp_geo_agent.fetch_nearby_context(latitude, longitude, radius_km=5) # הרחבתי קצת את הרדיוס כדי שבטוח נתפוס תחנות
        
        # detection_result = {
        #     "detected": True,
        #     "location": {"latitude": latitude, "longitude": longitude},
        #     "geospatial_context": geo_data.get("geospatial_context", {})
        # }

        is_detected = detection_result.get("detected")

        # Handle null case - unable to detect fire
        if is_detected is None:
            return {
                "status": "error", 
                "message": "Detection service is currently unavailable. Could not verify event status."
            }
            
        # Handle false case - no fire was detected
        elif is_detected is False:
            return {
                "status": "no_event", 
                "message": "No fire event detected at this location."
            }
        
        # ---------------------------------------------------------
        # Risk Analysis
        # ---------------------------------------------------------

        # TODO: (Integration): Uncomment the following lines once Risk Analysis Agent
        # returns un-hardcoded response
        #
        # detected_event_type = detection_result.get("event_type", "fire")
        # risk_result = self.risk_analysis_agent.analyze_event(
        #     event_type=detected_event_type,
        #     detected_event=detection_result
        # )
        risk_result = analyze_event("wildfire")

        recommended_units = risk_result.get("recommended_units", [])
        required_resources = {}

        # TODO: remove hardcoded facilities
        if "fire_department" in recommended_units:
            required_resources["fire_station"] = 2
        if "police" in recommended_units:
            required_resources["police_station"] = 1
        if "hospital" in recommended_units:
                    required_resources["hospital"] = 1
                
        required_resources["road"] = 3
            
        risk_result["required_resources"] = required_resources

        # ---------------------------------------------------------
        # Resource Allocation
        # ---------------------------------------------------------
        allocation_result = self.resource_allocation_agent.allocate_resources(
            event_location=detection_result["location"],
            geospatial_context=detection_result["geospatial_context"],
            risk_analysis=risk_result
        )

        # ---------------------------------------------------------
        # Response Planning
        # ---------------------------------------------------------
        return {
            "status": "success",
            "event_type": "fire",
            "location": detection_result["location"],
            "risk_assessment": {
                "score": risk_result.get("risk_score"),
                "level": risk_result.get("risk_level"),
                "explanation": risk_result.get("explanation")
            },
            "allocated_resources": allocation_result,
            "response_plan": risk_result.get("response_plan", [])
        }