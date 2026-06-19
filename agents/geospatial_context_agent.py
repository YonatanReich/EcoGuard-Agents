"""
Geospatial Context Agent

This agent is responsible for collecting basic geospatial context
around a given coordinate using OpenStreetMap through the Overpass API.
"""


class GeospatialContextAgent:
    """
    Collects nearby geographic objects around a given latitude and longitude.
    """

    def __init__(self):
        self.source_name = "OpenStreetMap / Overpass API"

    def fetch_nearby_context(self, latitude, longitude, radius_km=2):
        """
        Fetch basic geospatial context around a given coordinate.

        Args:
            latitude (float): Location latitude.
            longitude (float): Location longitude.
            radius_km (int): Search radius in kilometers.

        Returns:
            dict: Structured geospatial context.
        """
        return {
            "source": self.source_name,
            "latitude": latitude,
            "longitude": longitude,
            "radius_km": radius_km,
            "nearby_roads": [],
            "nearby_settlements": [],
            "nearby_hospitals": [],
            "nearby_police_stations": [],
            "nearby_fire_stations": [],
            "nearby_green_areas": [],
            "nearby_water_sources": [],
            "collection_status": "not_implemented"
        }