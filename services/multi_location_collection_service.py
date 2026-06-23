"""
Multi-Location Collection Service

This service is responsible for running data collection agents
on multiple predefined locations in Israel.
"""

import json

from agents.weather_data_agent import WeatherDataAgent
from agents.geospatial_context_agent import GeospatialContextAgent


class MultiLocationCollectionService:
    """
    Runs environmental data collection for multiple locations.
    """

    def __init__(self):
        self.service_name = "multi-location-collection-service"
        self.weather_agent = WeatherDataAgent()
        self.geospatial_agent = GeospatialContextAgent()

    def load_locations(self, file_path="data/israel_locations.json"):
        """
        Load predefined enabled locations from a JSON file.

        Args:
            file_path (str): Path to the locations JSON file.

        Returns:
            list: List of enabled location dictionaries.
        """
        with open(file_path, "r", encoding="utf-8") as file:
            data = json.load(file)

        locations = data.get("locations", [])

        enabled_locations = [
            location for location in locations
            if location.get("enabled", True)
        ]

        return enabled_locations

    def determine_location_status(self, weather_data, geospatial_data):
        """
        Determine the collection status for a single location.

        Args:
            weather_data (dict): Weather agent result.
            geospatial_data (dict): Geospatial agent result.

        Returns:
            str: Location collection status.
        """
        weather_status = weather_data.get("metadata", {}).get("collection_status")
        geospatial_status = geospatial_data.get("metadata", {}).get(
            "collection_status"
        )

        if weather_status == "failed" and geospatial_status == "failed":
            return "failed"

        if weather_status == "failed":
            return "partial"

        if geospatial_status in ["partial", "failed"]:
            return "partial"

        return "success"

    def normalize_location_result(
        self,
        location,
        weather_data,
        geospatial_data,
        collection_status="success",
    ):
        """
        Normalize a single location collection result.

        Args:
            location (dict): Original location dictionary.
            weather_data (dict): Weather agent result.
            geospatial_data (dict): Geospatial agent result.
            collection_status (str): Collection status for this location.

        Returns:
            dict: Normalized location result.
        """
        return {
            "location": {
                "name": location.get("name"),
                "region_type": location.get("region_type"),
                "latitude": location.get("latitude"),
                "longitude": location.get("longitude"),
                "scan_radius_km": location.get("scan_radius_km", 2),
            },
            "data": {
                "weather": weather_data,
                "geospatial": geospatial_data,
            },
            "collection_status": collection_status,
        }

    def build_collection_summary(self, results):
        """
        Build a summary for the multi-location collection result.

        Args:
            results (list): List of normalized location results.

        Returns:
            dict: Collection summary.
        """
        total_locations = len(results)

        successful_locations = 0
        partial_locations = 0
        failed_locations = 0

        for result in results:
            status = result.get("collection_status")

            if status == "failed":
                failed_locations += 1
            elif status == "partial":
                partial_locations += 1
            else:
                successful_locations += 1

        return {
            "total_locations": total_locations,
            "successful_locations": successful_locations,
            "partial_locations": partial_locations,
            "failed_locations": failed_locations,
        }

    def collect_for_locations(self, locations):
        """
        Collect weather and geospatial data for multiple locations.

        The service loops over all selected locations and calls both
        WeatherDataAgent and GeospatialContextAgent for each one.
        If collection fails for one location, the service stores the error
        and continues with the next location.

        Args:
            locations (list): List of location dictionaries.

        Returns:
            dict: Multi-location collection result with summary.
        """
        results = []

        for location in locations:
            latitude = location.get("latitude")
            longitude = location.get("longitude")
            scan_radius_km = location.get("scan_radius_km", 2)

            try:
                weather_data = self.weather_agent.fetch_weather_data(
                    latitude=latitude,
                    longitude=longitude,
                )

                geospatial_data = self.geospatial_agent.fetch_nearby_context(
                    latitude=latitude,
                    longitude=longitude,
                    radius_km=scan_radius_km,
                )

                location_result = self.normalize_location_result(
                    location=location,
                    weather_data=weather_data,
                    geospatial_data=geospatial_data,
                    collection_status=self.determine_location_status(
                        weather_data=weather_data,
                        geospatial_data=geospatial_data,
                    ),
                )

            except Exception as error:
                location_result = self.normalize_location_result(
                    location=location,
                    weather_data={},
                    geospatial_data={},
                    collection_status="failed",
                )

                location_result["error"] = str(error)

            results.append(location_result)

        summary = self.build_collection_summary(results)

        if summary["failed_locations"] > 0:
            collection_status = "completed_with_failures"
        elif summary["partial_locations"] > 0:
            collection_status = "partial"
        else:
            collection_status = "completed"

        return {
            "service": self.service_name,
            "locations_count": len(locations),
            "results_count": len(results),
            "summary": summary,
            "results": results,
            "collection_status": collection_status,
        }