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
            "missing_layers": [
                "nearby_roads",
                "nearby_settlements",
                "nearby_hospitals",
                "nearby_police_stations",
                "nearby_fire_stations",
                "nearby_green_areas",
                "nearby_water_sources",
            ],
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

    def build_police_stations_query(self, latitude, longitude, radius_km=2):
        """
        Build an Overpass query for nearby police stations.

        Args:
            latitude (float): Location latitude.
            longitude (float): Location longitude.
            radius_km (int): Search radius in kilometers.

        Returns:
            str: Overpass QL query for nearby police stations.
        """
        radius_meters = radius_km * 1000

        return f"""
[out:json][timeout:25];

(
  node["amenity"="police"](around:{radius_meters},{latitude},{longitude});
  way["amenity"="police"](around:{radius_meters},{latitude},{longitude});
  relation["amenity"="police"](around:{radius_meters},{latitude},{longitude});
);

out center tags;
"""

    def normalize_police_stations(self, elements):
        """
        Normalize raw Overpass police station elements into a unique list.

        OpenStreetMap may store police stations as nodes, ways, or relations.
        This function keeps only named police stations and removes duplicates
        by police station name. If the same police station appears more than
        once, relation is preferred over way, and way is preferred over node.

        Args:
            elements (list): Raw Overpass elements list.

        Returns:
            list: Unique nearby police stations.
        """
        unique_police_stations = {}

        osm_type_priority = {
            "node": 1,
            "way": 2,
            "relation": 3,
        }

        for element in elements:
            tags = element.get("tags", {})

            amenity_type = tags.get("amenity")
            police_station_name = tags.get("name")

            if amenity_type != "police" or not police_station_name:
                continue

            osm_type = element.get("type")
            osm_id = element.get("id")
            center = element.get("center", {})

            police_station = {
                "name": police_station_name,
                "type": amenity_type,
                "osm_type": osm_type,
                "osm_id": osm_id,
                "latitude": element.get("lat") or center.get("lat"),
                "longitude": element.get("lon") or center.get("lon"),
            }

            unique_key = police_station_name

            if unique_key not in unique_police_stations:
                unique_police_stations[unique_key] = police_station
                continue

            existing_osm_type = unique_police_stations[unique_key].get("osm_type")

            current_priority = osm_type_priority.get(osm_type, 0)
            existing_priority = osm_type_priority.get(existing_osm_type, 0)

            if current_priority > existing_priority:
                unique_police_stations[unique_key] = police_station

        return list(unique_police_stations.values())

    def build_fire_stations_query(self, latitude, longitude, radius_km=2):
        """
        Build an Overpass query for nearby fire stations.

        Args:
            latitude (float): Location latitude.
            longitude (float): Location longitude.
            radius_km (int): Search radius in kilometers.

        Returns:
            str: Overpass QL query for nearby fire stations.
        """
        radius_meters = radius_km * 1000

        return f"""
[out:json][timeout:25];

(
  node["amenity"="fire_station"](around:{radius_meters},{latitude},{longitude});
  way["amenity"="fire_station"](around:{radius_meters},{latitude},{longitude});
  relation["amenity"="fire_station"](around:{radius_meters},{latitude},{longitude});
);

out center tags;
"""

    def normalize_fire_stations(self, elements):
        """
        Normalize raw Overpass fire station elements into a unique list.

        OpenStreetMap may store fire stations as nodes, ways, or relations.
        This function keeps only named fire stations and removes duplicates
        by fire station name. If the same fire station appears more than once,
        relation is preferred over way, and way is preferred over node.

        Args:
            elements (list): Raw Overpass elements list.

        Returns:
            list: Unique nearby fire stations.
        """
        unique_fire_stations = {}

        osm_type_priority = {
            "node": 1,
            "way": 2,
            "relation": 3,
        }

        for element in elements:
            tags = element.get("tags", {})

            amenity_type = tags.get("amenity")
            fire_station_name = tags.get("name")

            if amenity_type != "fire_station" or not fire_station_name:
                continue

            osm_type = element.get("type")
            osm_id = element.get("id")
            center = element.get("center", {})

            fire_station = {
                "name": fire_station_name,
                "type": amenity_type,
                "osm_type": osm_type,
                "osm_id": osm_id,
                "latitude": element.get("lat") or center.get("lat"),
                "longitude": element.get("lon") or center.get("lon"),
            }

            unique_key = fire_station_name

            if unique_key not in unique_fire_stations:
                unique_fire_stations[unique_key] = fire_station
                continue

            existing_osm_type = unique_fire_stations[unique_key].get("osm_type")

            current_priority = osm_type_priority.get(osm_type, 0)
            existing_priority = osm_type_priority.get(existing_osm_type, 0)

            if current_priority > existing_priority:
                unique_fire_stations[unique_key] = fire_station

        return list(unique_fire_stations.values())

    def get_missing_layers(self, context):
        """
        Identify geospatial layers that are missing or empty.

        Args:
            context (dict): Structured geospatial context.

        Returns:
            list: Names of layers that are missing or contain no data.
        """
        layer_keys = [
            "nearby_roads",
            "nearby_settlements",
            "nearby_hospitals",
            "nearby_police_stations",
            "nearby_fire_stations",
            "nearby_green_areas",
            "nearby_water_sources",
        ]

        missing_layers = []

        for layer_key in layer_keys:
            layer_value = context.get(layer_key)

            if not layer_value:
                missing_layers.append(layer_key)

        return missing_layers

    def build_structured_context(
        self,
        latitude,
        longitude,
        radius_km=2,
        roads_elements=None,
        settlements_elements=None,
        hospitals_elements=None,
        police_stations_elements=None,
        fire_stations_elements=None,
    ):
        """
        Build a structured geospatial context from raw Overpass elements.

        This method receives raw Overpass element lists for each supported
        geospatial layer, normalizes them, handles missing layers, and returns
        one unified context object.

        Args:
            latitude (float): Location latitude.
            longitude (float): Location longitude.
            radius_km (int): Search radius in kilometers.
            roads_elements (list): Raw Overpass road elements.
            settlements_elements (list): Raw Overpass settlement elements.
            hospitals_elements (list): Raw Overpass hospital elements.
            police_stations_elements (list): Raw Overpass police station elements.
            fire_stations_elements (list): Raw Overpass fire station elements.

        Returns:
            dict: Structured geospatial context.
        """
        roads_elements = roads_elements or []
        settlements_elements = settlements_elements or []
        hospitals_elements = hospitals_elements or []
        police_stations_elements = police_stations_elements or []
        fire_stations_elements = fire_stations_elements or []

        nearby_roads = self.normalize_roads(roads_elements)
        nearby_settlements = self.normalize_settlements(settlements_elements)
        nearby_hospitals = self.normalize_hospitals(hospitals_elements)
        nearby_police_stations = self.normalize_police_stations(police_stations_elements)
        nearby_fire_stations = self.normalize_fire_stations(fire_stations_elements)

        context = {
            "source": self.source_name,
            "latitude": latitude,
            "longitude": longitude,
            "radius_km": radius_km,
            "nearby_roads": nearby_roads,
            "nearby_settlements": nearby_settlements,
            "nearby_hospitals": nearby_hospitals,
            "nearby_police_stations": nearby_police_stations,
            "nearby_fire_stations": nearby_fire_stations,
            "nearby_green_areas": [],
            "nearby_water_sources": [],
            "summary": {
                "nearby_roads_count": len(nearby_roads),
                "nearby_settlements_count": len(nearby_settlements),
                "nearby_hospitals_count": len(nearby_hospitals),
                "nearby_police_stations_count": len(nearby_police_stations),
                "nearby_fire_stations_count": len(nearby_fire_stations),
                "nearby_green_areas_count": 0,
                "nearby_water_sources_count": 0,
            },
        }

        missing_layers = self.get_missing_layers(context)

        context["missing_layers"] = missing_layers

        if missing_layers:
            context["collection_status"] = "completed_with_missing_data"
        else:
            context["collection_status"] = "completed"

        return context