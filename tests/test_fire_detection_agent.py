from unittest.mock import MagicMock

from agents.fire_detection_agent import FireDetectionAgent


def build_agent():
    """
    Create a FireDetectionAgent whose external providers are replaced
    with mocks so the tests do not depend on live APIs.
    """
    agent = FireDetectionAgent()

    agent.firms_agent = MagicMock()
    agent.fire_danger_agent = MagicMock()
    agent.weather_agent = MagicMock()
    agent.geospatial_agent = MagicMock()

    return agent


def test_detect_fire_when_hotspot_exists():
    """
    When NASA FIRMS returns a hotspot, FireDetectionAgent should enrich
    that hotspot and return a detected fire event.
    """
    agent = build_agent()

    agent.firms_agent.fetch_hotspots.return_value = {
        "fire_satellite_data": {
            "hotspots_count": 1,
            "hotspots": [
                {
                    "latitude": 31.91995,
                    "longitude": 34.89613,
                    "acquisition_date": "2026-08-21",
                    "acquisition_time": "26",
                    "satellite": "N20",
                    "instrument": "VIIRS",
                    "confidence": "n",
                    "frp": 1.21,
                    "daynight": "N",
                }
            ],
        }
    }

    agent.fire_danger_agent.get_fire_danger.return_value = {
        "source": "GWIS/EFFIS",
        "index": "FWI",
        "danger_level": "very_high",
        "fwi_min": 38.0,
        "fwi_max": 50.0,
    }

    agent.weather_agent.fetch_weather_data.return_value = {
        "metadata": {
            "collection_status": "success"
        },
        "weather": {
            "current": {
                "temperature_c": 31.3,
                "humidity_percent": 57,
                "wind_speed_kmh": 5.4,
                "precipitation_mm": 0.0,
            }
        }
    }

    agent.geospatial_agent.fetch_nearby_context.return_value = {
        "metadata": {
            "collection_status": "success"
        },
        "geospatial_context": {
            "nearby_roads": [],
            "nearby_settlements": [],
            "nearby_hospitals": [],
            "nearby_police_stations": [],
            "nearby_fire_stations": [],
        }
    }

    result = agent.detect_fire(
        latitude=32.0853,
        longitude=34.7818
    )

    assert result["detected"] is True
    assert result["event_type"] == "fire"
    assert result["detection_confidence"] == "nominal"
    assert result["fire_weather_severity"] == "very_high"

    assert result["location"]["latitude"] == 31.91995
    assert result["location"]["longitude"] == 34.89613

    assert result["source_status"]["nasa_firms"] == "success"
    assert result["source_status"]["gwis_effis"] == "success"


def test_detect_fire_when_no_hotspots_exist():
    """
    When NASA FIRMS successfully returns zero hotspots, the agent should
    explicitly return detected=False and should not run enrichment sources.
    """
    agent = build_agent()

    agent.firms_agent.fetch_hotspots.return_value = {
        "fire_satellite_data": {
            "hotspots_count": 0,
            "hotspots": [],
        }
    }

    result = agent.detect_fire(
        latitude=29.55,
        longitude=34.95
    )

    assert result["detected"] is False
    assert result["detection_confidence"] is None
    assert result["fire_weather_severity"] is None

    agent.fire_danger_agent.get_fire_danger.assert_not_called()
    agent.weather_agent.fetch_weather_data.assert_not_called()
    agent.geospatial_agent.fetch_nearby_context.assert_not_called()


def test_detect_fire_when_nasa_firms_fails():
    """
    Failure of the primary NASA FIRMS source must not be interpreted
    as 'no fire detected'.
    """
    agent = build_agent()

    agent.firms_agent.fetch_hotspots.side_effect = RuntimeError(
        "NASA FIRMS unavailable"
    )

    result = agent.detect_fire(
        latitude=32.0853,
        longitude=34.7818
    )

    assert result["detected"] is None
    assert result["metadata"]["collection_status"] == "failed"
    assert result["satellite_evidence"]["collection_status"] == "failed"


def test_detect_fire_survives_gwis_failure():
    """
    If NASA detects a hotspot but GWIS fails, the fire event should still
    remain detected and the GWIS source should be marked as failed.
    """
    agent = build_agent()

    agent.firms_agent.fetch_hotspots.return_value = {
        "fire_satellite_data": {
            "hotspots_count": 1,
            "hotspots": [
                {
                    "latitude": 31.91995,
                    "longitude": 34.89613,
                    "acquisition_date": "2026-08-21",
                    "acquisition_time": "26",
                    "satellite": "N20",
                    "instrument": "VIIRS",
                    "confidence": "n",
                    "frp": 1.21,
                    "daynight": "N",
                }
            ],
        }
    }

    agent.fire_danger_agent.get_fire_danger.side_effect = RuntimeError(
        "GWIS unavailable"
    )

    agent.weather_agent.fetch_weather_data.return_value = {
        "metadata": {
            "collection_status": "success"
        },
        "weather": {
            "current": {}
        }
    }

    agent.geospatial_agent.fetch_nearby_context.return_value = {
        "metadata": {
            "collection_status": "success"
        },
        "geospatial_context": {}
    }

    result = agent.detect_fire(
        latitude=32.0853,
        longitude=34.7818
    )

    assert result["detected"] is True
    assert result["fire_weather_severity"] == "unknown"
    assert result["source_status"]["gwis_effis"] == "failed"