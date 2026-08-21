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

from agents.firms_data_agent import FirmsDataAgent
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

        WeatherDataAgent already implements graceful failure behaviour and
        returns collection_status="failed" when Open-Meteo is unavailable.

        Args:
            latitude (float): Detected hotspot latitude.
            longitude (float): Detected hotspot longitude.

        Returns:
            dict: Unified weather response.
        """
        return self.weather_agent.fetch_weather_data(
            latitude=latitude,
            longitude=longitude
        )

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
        Build the response returned when NASA FIRMS finds no hotspots.

        Args:
            latitude (float): Original search latitude.
            longitude (float): Original search longitude.

        Returns:
            dict: Structured result indicating that no fire event was
                detected.
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
                "error": str(error),
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
        geospatial_radius_km: int = 2
    ) -> dict:
        """
        Detect and enrich a possible fire event around a requested location.

        This is the main public method of FireDetectionAgent.

        Detection flow:
            1. Search NASA FIRMS around the requested location.
            2. Stop with detected=False when FIRMS successfully returns
               zero hotspots.
            3. Select the most recent hotspot when detections exist.
            4. Use that hotspot's coordinates as the event location.
            5. Collect FWI, weather and geospatial context there.
            6. Return one combined DetectedFireEvent.

        Args:
            latitude (float): Center latitude of the initial search.
            longitude (float): Center longitude of the initial search.
            firms_delta (float): FIRMS bounding-box expansion in degrees.
            day_range (int): Number of recent FIRMS days to inspect.
            geospatial_radius_km (int): OSM enrichment radius around the
                selected hotspot.

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

        if not hotspots:
            return self.build_no_event_response(
                latitude=latitude,
                longitude=longitude
            )

        # Environmental enrichment is performed around the actual satellite
        # hotspot rather than around the center of the original search area.
        selected_hotspot = self.select_most_recent_hotspot(
            hotspots
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
            hotspots=hotspots,
            fire_danger=fire_danger,
            weather_response=weather_response,
            geospatial_response=geospatial_response
        )