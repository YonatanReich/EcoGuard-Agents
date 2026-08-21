"""
NASA FIRMS Data Agent

Responsible for collecting near-real-time satellite thermal hotspot data
around a requested coordinate using the NASA FIRMS Area API.

The agent currently uses the VIIRS NOAA-20 Near Real-Time data source.
NASA FIRMS returns the observations as CSV, so this agent also handles
normalization into Python dictionaries and wraps the result in the
project's unified response structure.

How it works:
    1. build_bounding_box creates a geographic search area around the
       requested coordinate.
    2. fetch_hotspots calls the NASA FIRMS Area API using the configured
       MAP_KEY, satellite source, bounding box and day range.
    3. parse_hotspots_csv converts the CSV response into a list of
       structured hotspot records.
    4. build_unified_response wraps the normalized hotspot data in a
       consistent EcoGuard response object.

Important:
    A FIRMS hotspot represents a satellite-detected thermal anomaly.
    It is strong evidence of active fire or another significant heat
    source, but it is not treated as absolute proof of a wildfire by
    this agent alone.

Environment:
    Requires NASA_FIRMS_API_KEY in the project .env file.

Consumed by:
    FireDetectionAgent
"""

import csv
import io
import os

import requests
from dotenv import load_dotenv

load_dotenv()


class FirmsDataAgent:
    """
    Fetches and normalizes NASA FIRMS active-fire hotspot observations.

    Attributes:
        api_key (str | None): NASA FIRMS MAP_KEY loaded from the project
            environment variables.
        base_url (str): NASA FIRMS service base URL.
    """

    def __init__(self):
        self.api_key = os.getenv("NASA_FIRMS_API_KEY")

        self.base_url = (
            "https://firms.modaps.eosdis.nasa.gov"
        )

    def parse_hotspots_csv(self, csv_text: str) -> list[dict]:
        """
        Convert the NASA FIRMS CSV response into structured hotspot records.

        Args:
            csv_text (str): Raw CSV text returned by the FIRMS Area API.

        Returns:
            list[dict]: Normalized satellite hotspot observations.

            Each hotspot contains:
                - latitude
                - longitude
                - acquisition_date
                - acquisition_time
                - satellite
                - instrument
                - confidence
                - frp
                - daynight

        Notes:
            NASA FIRMS VIIRS confidence values may be encoded using short
            categorical values such as "l", "n" and "h".

            FRP stands for Fire Radiative Power and represents the amount
            of radiant energy measured for the detected thermal anomaly.
        """
        reader = csv.DictReader(
            io.StringIO(csv_text)
        )

        hotspots = []

        for row in reader:
            hotspots.append({
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "acquisition_date": row["acq_date"],
                "acquisition_time": row["acq_time"],
                "satellite": row["satellite"],
                "instrument": row["instrument"],
                "confidence": row["confidence"],
                "frp": float(row["frp"]),
                "daynight": row["daynight"],
            })

        return hotspots

    def build_unified_response(
        self,
        latitude: float,
        longitude: float,
        hotspots: list[dict]
    ) -> dict:
        """
        Wrap normalized FIRMS data in the EcoGuard unified structure.

        Args:
            latitude (float): Latitude of the original requested location.
            longitude (float): Longitude of the original requested location.
            hotspots (list[dict]): Parsed FIRMS hotspot observations.

        Returns:
            dict: Unified satellite fire-data response containing:
                - metadata
                - requested location
                - hotspot count
                - hotspot observations
        """
        return {
            "metadata": {
                "data_source": "NASA FIRMS",
                "collection_status": "success"
            },
            "location": {
                "latitude": latitude,
                "longitude": longitude
            },
            "fire_satellite_data": {
                "hotspots_count": len(hotspots),
                "hotspots": hotspots
            }
        }

    def build_bounding_box(
        self,
        latitude: float,
        longitude: float,
        delta: float = 0.05
    ) -> str:
        """
        Build a rectangular FIRMS Area API search region around a coordinate.

        NASA FIRMS expects area coordinates in the order:

            west,south,east,north

        A symmetric delta is applied around the requested coordinate.

        Args:
            latitude (float): Center latitude in decimal degrees.
            longitude (float): Center longitude in decimal degrees.
            delta (float): Number of degrees to extend the search area
                in every direction.

        Returns:
            str: FIRMS-compatible bounding box string.
        """
        west = longitude - delta
        south = latitude - delta
        east = longitude + delta
        north = latitude + delta

        return f"{west},{south},{east},{north}"

    def fetch_hotspots(
        self,
        latitude: float,
        longitude: float,
        delta: float = 0.05,
        source: str = "VIIRS_NOAA20_NRT",
        day_range: int = 1
    ) -> dict:
        """
        Fetch near-real-time satellite hotspot data from NASA FIRMS.

        The method builds a bounding box around the requested coordinate,
        calls the FIRMS Area API, parses the CSV response and returns the
        result in the EcoGuard unified structure.

        Args:
            latitude (float): Center latitude for the search.
            longitude (float): Center longitude for the search.
            delta (float): Bounding-box expansion in decimal degrees.
            source (str): NASA FIRMS satellite dataset identifier.
                The default is VIIRS NOAA-20 Near Real-Time.
            day_range (int): Number of recent days to request from FIRMS.

        Returns:
            dict: Unified FIRMS fire-satellite response.

        Raises:
            requests.HTTPError: If NASA FIRMS returns a non-success HTTP
                response.
            requests.RequestException: If communication with FIRMS fails.

        Notes:
            This agent currently allows request exceptions to propagate.
            FireDetectionAgent or a future orchestration layer should decide
            whether FIRMS failure should abort detection or produce a partial
            result.
        """
        if not self.api_key:
            raise ValueError(
                "NASA_FIRMS_API_KEY is missing from the environment."
            )

        bounding_box = self.build_bounding_box(
            latitude=latitude,
            longitude=longitude,
            delta=delta
        )

        url = (
            f"{self.base_url}/api/area/csv/"
            f"{self.api_key}/"
            f"{source}/"
            f"{bounding_box}/"
            f"{day_range}"
        )

        response = requests.get(
            url,
            timeout=30
        )

        response.raise_for_status()

        hotspots = self.parse_hotspots_csv(
            response.text
        )

        return self.build_unified_response(
            latitude=latitude,
            longitude=longitude,
            hotspots=hotspots
        )

