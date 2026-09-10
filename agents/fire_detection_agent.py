"""
Fire Detection Agent

Responsible for detecting outdoor/environmental fire events by combining
multiple independent environmental data sources.

NASA FIRMS provides the primary satellite evidence used to identify thermal
hotspots. Once a hotspot is found, the agent enriches that hotspot with:

    - GWIS/EFFIS Fire Weather Index (FWI) danger information.
    - Current and forecast weather from Open-Meteo.
    - Nearby geographic context from OpenStreetMap / Overpass API.

How it works:
    1. Query NASA FIRMS for thermal hotspots around a requested coordinate.
    2. If no hotspots are found, return an explicit no-fire-event result.
    3. If hotspots are found, select the most recent hotspot.
    4. Use the selected hotspot coordinate as the detected event location.
    5. Query GWIS/EFFIS, Open-Meteo and OpenStreetMap around that location.
    6. Combine the collected evidence into one DetectedFireEvent.

Important:
    A NASA FIRMS hotspot represents a satellite-detected thermal anomaly.
    It is used as the primary detection signal, but should not be interpreted
    by itself as absolute proof of a wildfire.

    Fire detection, fire-weather danger and downstream risk analysis are
    intentionally kept as separate concepts:

        - NASA FIRMS provides the primary detection evidence.
        - NASA confidence describes the quality/category of that satellite
          detection.
        - GWIS/EFFIS FWI describes the surrounding fire-weather danger.
        - Weather and geospatial sources provide additional environmental
          and exposure context.
        - RiskAnalysisAgent later combines the detected-event evidence with
          protocol-grounded reasoning to determine overall operational risk.

    Therefore this agent does not invent a combined risk score.

Failure behaviour:
    NASA FIRMS is the primary detection source. If the FIRMS request fails,
    the detection operation cannot determine whether a hotspot exists and
    returns a failed detection result.

    GWIS/EFFIS, weather and geospatial context are enrichment sources.
    Failure of one enrichment source does not discard the satellite
    detection. Instead, that section is returned with unavailable/failed
    information so downstream agents can still process a partial event.

Consumed by:
    RiskAnalysisAgent
    Coordinator
"""

from datetime import datetime, timezone
import math

import requests

from agents.firms_data_agent import FirmsDataAgent
from agents.firms_data_agent import FirmsProviderError
from agents.fire_danger_agent import FireDangerAgent
from agents.weather_data_agent import WeatherDataAgent
from agents.geospatial_context_agent import GeospatialContextAgent


class FireDetectionAgent:
    """
    Coordinates satellite detection and environmental enrichment to produce
    a structured DetectedFireEvent.

    Attributes:
        firms_agent (FirmsDataAgent): NASA FIRMS satellite hotspot provider.
        fire_danger_agent (FireDangerAgent): GWIS/EFFIS FWI provider.
        weather_agent (WeatherDataAgent): Open-Meteo weather provider.
        geospatial_agent (GeospatialContextAgent): OSM/Overpass context
            provider.
    """

    def __init__(self):
        self.firms_agent = FirmsDataAgent()
        self.fire_danger_agent = FireDangerAgent()
        self.weather_agent = WeatherDataAgent()
        self.geospatial_agent = GeospatialContextAgent()

    def normalize_nasa_confidence(
        self,
        confidence: str | None
    ) -> str | None:
        """
        Convert NASA FIRMS short confidence codes into readable values.

        VIIRS observations commonly encode confidence as:
            l -> low
            n -> nominal
            h -> high

        Args:
            confidence (str | None): Raw NASA FIRMS confidence value.

        Returns:
            str | None: Human-readable confidence value. Unknown confidence
                values are preserved in lowercase rather than discarded.
        """
        if confidence is None:
            return None

        confidence_mapping = {
            "l": "low",
            "n": "nominal",
            "h": "high",
        }

        normalized_input = str(confidence).lower()

        return confidence_mapping.get(
            normalized_input,
            normalized_input
        )

    def select_most_recent_hotspot(
        self,
        hotspots: list[dict]
    ) -> dict | None:
        """
        Select the most recent NASA FIRMS hotspot from a hotspot list.

        FIRMS provides acquisition date and time separately. They are combined
        here so detections from several requested days can be ordered
        chronologically.

        Args:
            hotspots (list[dict]): Normalized FIRMS hotspot records.

        Returns:
            dict | None: Most recent hotspot, or None when the list is empty.
        """
        if not hotspots:
            return None

        def hotspot_datetime(hotspot: dict):
            acquisition_date = hotspot.get(
                "acquisition_date",
                "1970-01-01"
            )

            # FIRMS may return times such as "26" instead of "0026".
            # Padding to four digits gives a consistent HHMM representation.
            acquisition_time = str(
                hotspot.get("acquisition_time", "0000")
            ).zfill(4)

            try:
                return datetime.strptime(
                    f"{acquisition_date} {acquisition_time}",
                    "%Y-%m-%d %H%M"
                )
            except (ValueError, TypeError):
                # Invalid timestamps are pushed to the beginning so they
                # cannot accidentally be selected as the newest detection.
                return datetime.min

        return max(
            hotspots,
            key=hotspot_datetime
        )

    def calculate_distance_km(
        self,
        latitude_a: float,
        longitude_a: float,
        latitude_b: float,
        longitude_b: float,
    ) -> float:
        """Calculate great-circle distance between two coordinates."""
        earth_radius_km = 6371.0088
        latitude_a_radians = math.radians(latitude_a)
        latitude_b_radians = math.radians(latitude_b)
        latitude_delta = math.radians(latitude_b - latitude_a)
        longitude_delta = math.radians(longitude_b - longitude_a)

        haversine_value = (
            math.sin(latitude_delta / 2) ** 2
            + math.cos(latitude_a_radians)
            * math.cos(latitude_b_radians)
            * math.sin(longitude_delta / 2) ** 2
        )
        return 2 * earth_radius_km * math.asin(
            min(1.0, math.sqrt(haversine_value))
        )

    def filter_relevant_hotspots(
        self,
        hotspots: list[dict],
        latitude: float,
        longitude: float,
        max_distance_km: float,
    ) -> list[dict]:
        """Keep only hotspots within the point-detection relevance radius."""
        relevant_hotspots = []
        for hotspot in hotspots:
            try:
                hotspot_latitude = float(hotspot["latitude"])
                hotspot_longitude = float(hotspot["longitude"])
                distance_km = self.calculate_distance_km(
                    latitude,
                    longitude,
                    hotspot_latitude,
                    hotspot_longitude,
                )
            except (KeyError, TypeError, ValueError):
                continue

            if distance_km <= max_distance_km:
                relevant_hotspots.append(hotspot)

        return relevant_hotspots

    def collect_fire_danger(
        self,
        latitude: float,
        longitude: float
    ) -> dict:
        """
        Collect GWIS/EFFIS fire-weather danger for the detected hotspot.

        Failure of this enrichment source does not invalidate the NASA
        satellite detection.

        Args:
            latitude (float): Detected hotspot latitude.
            longitude (float): Detected hotspot longitude.

        Returns:
            dict: Fire-danger information or an unavailable record.
        """
        try:
            return self.fire_danger_agent.get_fire_danger(
                latitude=latitude,
                longitude=longitude
            )

        except Exception as error:
            return {
                "source": "GWIS/EFFIS",
                "index": "FWI",
                "danger_level": "unknown",
                "fwi_min": None,
                "fwi_max": None,
                "collection_status": "failed",
                "error": str(error),
            }

    def collect_weather(
        self,
        latitude: float,
        longitude: float
    ) -> dict:
        """
        Collect weather information around the detected hotspot.

        WeatherDataAgent reads the collection layer's stored observations —
        the hotspot is answered by the 5 km cell containing it — and already
        implements graceful failure behaviour, returning
        collection_status="failed" when the store has nothing recent nearby.

        Args:
            latitude (float): Detected hotspot latitude.
            longitude (float): Detected hotspot longitude.

        Returns:
            dict: Unified weather response.
        """
        try:
            return self.weather_agent.fetch_weather_data(
                latitude=latitude,
                longitude=longitude
            )
        except Exception:
            current_timestamp = datetime.now(
                timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            return {
                "metadata": {
                    "timestamp": current_timestamp,
                    "data_source": "open-meteo",
                    "collection_status": "failed",
                },
                "location": {
                    "latitude": latitude,
                    "longitude": longitude,
                },
                "weather": {"current": {}, "forecast": {"daily": {}}},
                "error": "unexpected provider error",
            }

    def sanitize_firms_error(self, error: Exception) -> str:
        """Return a useful FIRMS error category without request details."""
        if isinstance(error, FirmsProviderError):
            error_kind = str(error)
            if error_kind in {
                "authentication error",
                "HTTP error",
                "timeout",
                "network error",
                "malformed response",
            }:
                return error_kind
            return "provider error"
        if isinstance(error, requests.exceptions.Timeout):
            return "timeout"
        if isinstance(error, requests.exceptions.HTTPError):
            status_code = getattr(error.response, "status_code", None)
            return (
                "authentication error"
                if status_code in (401, 403)
                else "HTTP error"
            )
        if isinstance(error, requests.exceptions.RequestException):
            return "network error"
        if isinstance(error, (KeyError, TypeError, ValueError)):
            return "malformed response"
        return "provider error"

    def collect_geospatial_context(
        self,
        latitude: float,
        longitude: float,
        radius_km: int = 2
    ) -> dict:
        """
        Collect nearby geographic objects around the detected hotspot.

        GeospatialContextAgent already handles Overpass failures gracefully,
        allowing the fire event to survive even if geographic enrichment is
        temporarily unavailable.

        Args:
            latitude (float): Detected hotspot latitude.
            longitude (float): Detected hotspot longitude.
            radius_km (int): OSM search radius around the hotspot.

        Returns:
            dict: Unified geospatial context response.
        """
        return self.geospatial_agent.fetch_nearby_context(
            latitude=latitude,
            longitude=longitude,
            radius_km=radius_km
        )

    def build_no_event_response(
        self,
        latitude: float,
        longitude: float
    ) -> dict:
        """
        Build the response returned when FIRMS finds no relevant hotspots.

        Args:
            latitude (float): Original search latitude.
            longitude (float): Original search longitude.

        Returns:
            dict: Structured result indicating that no geographically relevant
                fire event was detected for the requested point.
        """
        current_timestamp = datetime.now(
            timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        return {
            "metadata": {
                "timestamp": current_timestamp,
                "collection_status": "success",
            },
            "event_type": "fire",
            "detected": False,
            "location": {
                "latitude": latitude,
                "longitude": longitude,
            },
            "detection_confidence": None,
            "fire_weather_severity": None,
            "satellite_evidence": {
                "source": "NASA FIRMS",
                "hotspots_count": 0,
                "selected_hotspot": None,
            },
            "fire_danger": None,
            "weather_context": None,
            "geospatial_context": None,
        }

    def build_failed_detection_response(
        self,
        latitude: float,
        longitude: float,
        error: Exception
    ) -> dict:
        """
        Build a response for a failure of the primary NASA FIRMS source.

        A FIRMS communication failure is different from receiving a valid
        response containing zero hotspots. In this situation the system
        reports that detection could not be completed instead of incorrectly
        claiming that no fire was detected.

        Args:
            latitude (float): Original search latitude.
            longitude (float): Original search longitude.
            error (Exception): Failure raised while querying FIRMS.

        Returns:
            dict: Structured failed-detection response.
        """
        current_timestamp = datetime.now(
            timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        return {
            "metadata": {
                "timestamp": current_timestamp,
                "collection_status": "failed",
            },
            "event_type": "fire",
            "detected": None,
            "location": {
                "latitude": latitude,
                "longitude": longitude,
            },
            "detection_confidence": None,
            "fire_weather_severity": None,
            "satellite_evidence": {
                "source": "NASA FIRMS",
                "collection_status": "failed",
                "error": self.sanitize_firms_error(error),
            },
            "fire_danger": None,
            "weather_context": None,
            "geospatial_context": None,
        }

    def build_detected_event(
        self,
        hotspot: dict,
        hotspots: list[dict],
        fire_danger: dict,
        weather_response: dict,
        geospatial_response: dict
    ) -> dict:
        """
        Build the final DetectedFireEvent from all available evidence.

        NASA confidence is preserved as the detection-confidence signal.
        The GWIS/EFFIS danger category is preserved separately as the
        fire-weather severity.

        Keeping these concepts separate is important:

            detection_confidence
                -> how NASA classifies the quality/category of the satellite
                   thermal detection.

            fire_weather_severity
                -> the GWIS/EFFIS FWI category describing how severe the
                   surrounding fire-weather conditions are.

            overall risk
                -> intentionally NOT calculated here. It belongs to the
                   downstream RiskAnalysisAgent.

        Args:
            hotspot (dict): Selected FIRMS hotspot representing the event.
            hotspots (list[dict]): All FIRMS hotspots found in the search.
            fire_danger (dict): GWIS/EFFIS FWI result.
            weather_response (dict): Open-Meteo unified response.
            geospatial_response (dict): OSM unified response.

        Returns:
            dict: Combined DetectedFireEvent.
        """
        current_timestamp = datetime.now(
            timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        raw_confidence = hotspot.get("confidence")

        normalized_confidence = self.normalize_nasa_confidence(
            raw_confidence
        )

        selected_hotspot = {
            **hotspot,
            "raw_confidence": raw_confidence,
            "normalized_confidence": normalized_confidence,
        }

        return {
            "metadata": {
                "timestamp": current_timestamp,
                "collection_status": "success",
            },
            "event_type": "fire",
            "detected": True,
            "location": {
                "latitude": hotspot.get("latitude"),
                "longitude": hotspot.get("longitude"),
            },

            # Human-readable NASA detection confidence.
            "detection_confidence": normalized_confidence,

            # This is specifically fire-weather severity from GWIS/EFFIS,
            # not the final operational risk level.
            "fire_weather_severity": fire_danger.get(
                "danger_level",
                "unknown"
            ),

            "satellite_evidence": {
                "source": "NASA FIRMS",
                "hotspots_count": len(hotspots),
                "selected_hotspot": selected_hotspot,
                "hotspots": hotspots,
            },

            "fire_danger": fire_danger,

            # Weather is retained as environmental evidence/context.
            # RiskAnalysisAgent may later use these values together with
            # satellite, FWI and protocol information.
            "weather_context": weather_response.get(
                "weather",
                {}
            ),

            # Geospatial information is retained as environmental/exposure
            # context rather than being converted into a risk score here.
            "geospatial_context": geospatial_response.get(
                "geospatial_context",
                {}
            ),

            # Preserve provider collection states so downstream components
            # can distinguish complete events from partially enriched ones.
            "source_status": {
                "nasa_firms": "success",
                "gwis_effis": fire_danger.get(
                    "collection_status",
                    "success"
                ),
                "weather": weather_response.get(
                    "metadata",
                    {}
                ).get(
                    "collection_status",
                    "unknown"
                ),
                "geospatial": geospatial_response.get(
                    "metadata",
                    {}
                ).get(
                    "collection_status",
                    "unknown"
                ),
            },
        }

    def detect_fire(
        self,
        latitude: float,
        longitude: float,
        firms_delta: float = 0.5,
        day_range: int = 5,
        geospatial_radius_km: int = 2,
        max_hotspot_distance_km: float = 5.0,
    ) -> dict:
        """
        Detect and enrich a possible fire event around a requested location.

        This is the main public method of FireDetectionAgent.

        Detection flow:
            1. Search NASA FIRMS around the requested location.
            2. Keep only hotspots within the configured Haversine distance.
            3. Stop with detected=False when no relevant hotspots remain.
            4. Select the most recent geographically relevant hotspot.
            5. Use that hotspot's coordinates as the event location.
            6. Collect FWI, weather and geospatial context there.
            7. Return one combined DetectedFireEvent.

        Args:
            latitude (float): Center latitude of the initial search.
            longitude (float): Center longitude of the initial search.
            firms_delta (float): FIRMS bounding-box expansion in degrees.
            day_range (int): Number of recent FIRMS days to inspect.
            geospatial_radius_km (int): OSM enrichment radius around the
                selected hotspot.
            max_hotspot_distance_km (float): Maximum Haversine distance from
                the requested point for a FIRMS hotspot to be relevant.

        Returns:
            dict: DetectedFireEvent, explicit no-event result, or failed
                detection result when the primary FIRMS source is unavailable.
        """
        try:
            firms_response = self.firms_agent.fetch_hotspots(
                latitude=latitude,
                longitude=longitude,
                delta=firms_delta,
                day_range=day_range
            )

        except Exception as error:
            return self.build_failed_detection_response(
                latitude=latitude,
                longitude=longitude,
                error=error
            )

        fire_satellite_data = firms_response.get(
            "fire_satellite_data",
            {}
        )

        hotspots = fire_satellite_data.get(
            "hotspots",
            []
        )

        relevant_hotspots = self.filter_relevant_hotspots(
            hotspots=hotspots,
            latitude=latitude,
            longitude=longitude,
            max_distance_km=max_hotspot_distance_km,
        )

        if not relevant_hotspots:
            return self.build_no_event_response(
                latitude=latitude,
                longitude=longitude
            )

        # Environmental enrichment is performed around the actual satellite
        # hotspot rather than around the center of the original search area.
        selected_hotspot = self.select_most_recent_hotspot(
            relevant_hotspots
        )

        hotspot_latitude = selected_hotspot["latitude"]
        hotspot_longitude = selected_hotspot["longitude"]

        fire_danger = self.collect_fire_danger(
            latitude=hotspot_latitude,
            longitude=hotspot_longitude
        )

        weather_response = self.collect_weather(
            latitude=hotspot_latitude,
            longitude=hotspot_longitude
        )

        geospatial_response = self.collect_geospatial_context(
            latitude=hotspot_latitude,
            longitude=hotspot_longitude,
            radius_km=geospatial_radius_km
        )

        return self.build_detected_event(
            hotspot=selected_hotspot,
            hotspots=relevant_hotspots,
            fire_danger=fire_danger,
            weather_response=weather_response,
            geospatial_response=geospatial_response
        )
