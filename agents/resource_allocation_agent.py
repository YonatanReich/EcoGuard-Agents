import math

"""
Resource Allocation Agent

Responsible for selecting the nearest available emergency response units 
(such as fire stations, hospitals, and police stations) based on protocol 
requirements and real-world geographic proximity.

This agent connects the protocol-grounded output of the Risk Analysis Agent 
with the real-world geospatial data collected early in the pipeline.

How it works:
    1. allocate_resources parses the required unit types and counts from the 
       Risk Analysis assessment.
    2. _haversine_distance calculates the great-circle distance in kilometers 
       between the detected event location and each nearby facility.
    3. _find_closest_facilities sorts the available facilities of the required 
       type by distance and selects the exact number mandated by the protocol.
    4. The agent returns a structured JSON response mapping each required 
       unit type to the closest physical facilities.

Consumed by:
    Coordinator
"""

class ResourceAllocationAgent:
    def __init__(self):
        self.agent_name = "Resource Allocation Agent"

    def _haversine_distance(self, lat1, lon1, lat2, lon2):
        """
        Calculate the great circle distance in kilometers between two points 
        on the earth (specified in decimal degrees).
        """
        # Convert decimal degrees to radians 
        lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])

        # Haversine formula 
        dlon = lon2 - lon1 
        dlat = lat2 - lat1 
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a)) 
        r = 6371 # Radius of earth in kilometers
        return c * r

    def _find_closest_facilities(self, event_lat, event_lon, facilities_list, required_count):
        """
        Sorts the facilities by distance and returns the requested number of closest ones.
        """
        if not facilities_list or required_count <= 0:
            return []

        # Calculate distance for each facility and append it to the dictionary
        for facility in facilities_list:
            fac_lat = facility.get("latitude")
            fac_lon = facility.get("longitude")
            
            if fac_lat is not None and fac_lon is not None:
                facility["distance_km"] = self._haversine_distance(event_lat, event_lon, fac_lat, fac_lon)
            else:
                facility["distance_km"] = float('inf') # Fallback if coordinates are missing

        # Sort by distance and slice the list to get the required count
        sorted_facilities = sorted(facilities_list, key=lambda x: x["distance_km"])
        return sorted_facilities[:required_count]

    def allocate_resources(self, event_location, geospatial_context, risk_analysis):
        """
        Allocates resources based on risk analysis requirements and geospatial proximity.
        """
        event_lat = event_location.get("latitude")
        event_lon = event_location.get("longitude")
        
        required_resources = risk_analysis.get("required_resources", {})
        
        allocated_units = {
            "fire_stations": [],
            "hospitals": [],
            "police_stations": [],
            "roads": []
        }

        # Allocate Fire Stations
        if "fire_station" in required_resources:
            allocated_units["fire_stations"] = self._find_closest_facilities(
                event_lat, 
                event_lon, 
                geospatial_context.get("nearby_fire_stations", []), 
                required_resources["fire_station"]
            )

        # Allocate Hospitals
        if "hospital" in required_resources:
            allocated_units["hospitals"] = self._find_closest_facilities(
                event_lat, 
                event_lon, 
                geospatial_context.get("nearby_hospitals", []), 
                required_resources["hospital"]
            )

        # Allocate Police Stations
        if "police_station" in required_resources:
            allocated_units["police_stations"] = self._find_closest_facilities(
                event_lat, 
                event_lon, 
                geospatial_context.get("nearby_police_stations", []), 
                required_resources["police_station"]
            )

        # Allocate Roads
        if "road" in required_resources:
            allocated_units["roads"] = self._find_closest_facilities(
                event_lat, 
                event_lon, 
                geospatial_context.get("nearby_roads", []), 
                required_resources["road"]
            )

        return {
            "status": "success",
            "allocated_units": allocated_units,
            "rationale": f"Allocated units based on proximity to event at ({event_lat}, {event_lon})."
        }