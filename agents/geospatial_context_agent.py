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

    def build_settlements_query(self, latitude, longitude, radius_km=2):
        """
        Build an Overpass query for nearby settlements or populated areas.

        Args:
            latitude (float): Location latitude.
            longitude (float): Location longitude.
            radius_km (int): Search radius in kilometers.

        Returns:
            str: Overpass QL query for nearby populated places.
        """
        radius_meters = radius_km * 1000

        return f"""
[out:json][timeout:25];

(
  node["place"~"city|town|village|suburb|neighbourhood"](around:{radius_meters},{latitude},{longitude});
  way["place"~"city|town|village|suburb|neighbourhood"](around:{radius_meters},{latitude},{longitude});
  relation["place"~"city|town|village|suburb|neighbourhood"](around:{radius_meters},{latitude},{longitude});
);

out center tags;
"""

    def normalize_settlements(self, elements):
        """
        Normalize raw Overpass settlement elements into a unique settlement list.

        OpenStreetMap may store the same populated area as several objects.
        For example, a town can appear both as a node and as a relation.
        In that case, this function keeps only one result and prefers:
        relation over way, and way over node.

        Args:
            elements (list): Raw Overpass elements list.

        Returns:
            list: Unique nearby settlements or populated areas.
        """
        unique_settlements = {}

        osm_type_priority = {
            "node": 1,
            "way": 2,
            "relation": 3,
        }

        for element in elements:
            tags = element.get("tags", {})

            place_type = tags.get("place")
            settlement_name = tags.get("name")

            if not place_type or not settlement_name:
                continue

            osm_type = element.get("type")
            osm_id = element.get("id")
            center = element.get("center", {})

            settlement = {
                "name": settlement_name,
                "type": place_type,
                "osm_type": osm_type,
                "osm_id": osm_id,
                "population": tags.get("population"),
                "latitude": element.get("lat") or center.get("lat"),
                "longitude": element.get("lon") or center.get("lon"),
            }

            unique_key = settlement_name

            if unique_key not in unique_settlements:
                unique_settlements[unique_key] = settlement
                continue

            existing_osm_type = unique_settlements[unique_key].get("osm_type")

            current_priority = osm_type_priority.get(osm_type, 0)
            existing_priority = osm_type_priority.get(existing_osm_type, 0)

            if current_priority > existing_priority:
                unique_settlements[unique_key] = settlement

        return list(unique_settlements.values())

    def build_hospitals_query(self, latitude, longitude, radius_km=2):
        """
        Build an Overpass query for nearby hospitals.

        Args:
            latitude (float): Location latitude.
            longitude (float): Location longitude.
            radius_km (int): Search radius in kilometers.

        Returns:
            str: Overpass QL query for nearby hospitals.
        """
        radius_meters = radius_km * 1000

        return f"""
[out:json][timeout:25];

(
  node["amenity"="hospital"](around:{radius_meters},{latitude},{longitude});
  way["amenity"="hospital"](around:{radius_meters},{latitude},{longitude});
  relation["amenity"="hospital"](around:{radius_meters},{latitude},{longitude});
);

out center tags;
"""

    def normalize_hospitals(self, elements):
        """
        Normalize raw Overpass hospital elements into a unique hospital list.

        OpenStreetMap may store hospitals as nodes, ways, or relations.
        This function keeps only named hospitals and removes duplicates
        by hospital name. If the same hospital appears more than once,
        relation is preferred over way, and way is preferred over node.

        Args:
            elements (list): Raw Overpass elements list.

        Returns:
            list: Unique nearby hospitals.
        """
        unique_hospitals = {}

        osm_type_priority = {
            "node": 1,
            "way": 2,
            "relation": 3,
        }

        for element in elements:
            tags = element.get("tags", {})

            amenity_type = tags.get("amenity")
            hospital_name = tags.get("name")

            if amenity_type != "hospital" or not hospital_name:
                continue

            osm_type = element.get("type")
            osm_id = element.get("id")
            center = element.get("center", {})

            hospital = {
                "name": hospital_name,
                "type": amenity_type,
                "osm_type": osm_type,
                "osm_id": osm_id,
                "latitude": element.get("lat") or center.get("lat"),
                "longitude": element.get("lon") or center.get("lon"),
            }

            unique_key = hospital_name

            if unique_key not in unique_hospitals:
                unique_hospitals[unique_key] = hospital
                continue

            existing_osm_type = unique_hospitals[unique_key].get("osm_type")

            current_priority = osm_type_priority.get(osm_type, 0)
            existing_priority = osm_type_priority.get(existing_osm_type, 0)

            if current_priority > existing_priority:
                unique_hospitals[unique_key] = hospital

        return list(unique_hospitals.values())