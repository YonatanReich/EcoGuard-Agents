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
        self.overpass_url = "https://overpass-api.de/api/interpreter"

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

    def build_roads_query(self, latitude, longitude, radius_km=2):
        """
        Build an Overpass query for nearby main roads.

        Args:
            latitude (float): Location latitude.
            longitude (float): Location longitude.
            radius_km (int): Search radius in kilometers.

        Returns:
            str: Overpass QL query for nearby main roads.
        """
        radius_meters = radius_km * 1000

        return f"""
[out:json][timeout:25];

(
  way["highway"~"motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link"](around:{radius_meters},{latitude},{longitude});
);

out center tags;
"""

    def normalize_roads(self, elements):
        """
        Normalize raw Overpass road elements into a unique road list.

        OpenStreetMap stores roads as multiple way segments, so the same
        road may appear several times. This function removes duplicates
        using ref when available, and name when ref is missing.

        Args:
            elements (list): Raw Overpass elements list.

        Returns:
            list: Unique nearby roads.
        """
        unique_roads = {}

        for element in elements:
            tags = element.get("tags", {})

            road_type = tags.get("highway")
            road_name = tags.get("name")
            road_ref = tags.get("ref")

            if not road_type:
                continue

            if road_ref:
                unique_key = f"ref:{road_ref}"
            elif road_name:
                unique_key = f"name:{road_name}"
            else:
                continue

            if unique_key not in unique_roads:
                center = element.get("center", {})

                unique_roads[unique_key] = {
                    "name": road_name,
                    "ref": road_ref,
                    "type": road_type,
                    "latitude": center.get("lat"),
                    "longitude": center.get("lon"),
                }

        return list(unique_roads.values())