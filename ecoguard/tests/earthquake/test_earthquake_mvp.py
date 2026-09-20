from datetime import datetime, timezone

import pytest

from ecoguard.analyzers.emergency.earthquake.impact import (
    LIMITATION,
    estimate_impact,
    estimated_impact_radius_km,
)
from ecoguard.api.events import shared_event_feed
from ecoguard.collection.earthquake.gsi import normalize_fdsn_text
from ecoguard.database.repositories.towns import (
    TownIntersection,
    TownIntersectionResult,
    TownLookupStatus,
    towns_intersecting,
)
from ecoguard.detectors.earthquake.observation_processing import (
    MIN_DASHBOARD_MAGNITUDE,
    signals_from_observations,
)
from ecoguard.shared.events import (
    EarthquakeDetails,
    EarthquakePopulationSummary,
    EarthquakeSharedEvent,
    EarthquakeTown,
    GeoJsonPolygon,
)

NOW = datetime(2026, 9, 20, 10, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("magnitude", "radius"),
    [
        (3.49, 5.0),
        (3.5, 10.0),
        (4.4, 10.0),
        (4.5, 25.0),
        (5.4, 25.0),
        (5.5, 50.0),
    ],
)
def test_magnitude_radius_boundaries(magnitude, radius):
    assert estimated_impact_radius_km(magnitude) == radius


def test_gsi_fdsn_event_normalization_preserves_provenance():
    payload = (
        "#EventID|Time|Latitude|Longitude|Depth/km|Author|Catalog|Contributor|"
        "ContributorID|MagType|Magnitude|MagAuthor|EventLocationName\n"
        "gsi2026abcd|2026-09-20T10:30:00.000Z|31.75|35.21|12.4|GSI|GSI|"
        "GSI|gsi2026abcd|ML|4.6|GSI|Dead Sea Region\n"
    )

    event = normalize_fdsn_text(payload)[0]

    assert event.provider_event_id == "gsi2026abcd"
    assert event.observed_at == NOW
    assert event.latitude == 31.75
    assert event.longitude == 35.21
    assert event.magnitude == 4.6
    assert event.depth_km == 12.4
    assert event.provider == "GSI"
    assert event.raw["event_location_name"] == "Dead Sea Region"


def _persisted_earthquake(magnitude: float) -> dict:
    return {
        "cell_id": "risk-05000m-r0055-c0013",
        "observed_at": NOW,
        "payload": {
            "provider_event_id": f"gsi-m{magnitude}",
            "observed_at": NOW.isoformat(),
            "latitude": 31.75,
            "longitude": 35.21,
            "magnitude": magnitude,
            "depth_km": 12.4,
            "provider": "GSI",
            "raw": {},
        },
    }


def test_magnitude_3_4_does_not_emit_dashboard_signal():
    assert MIN_DASHBOARD_MAGNITUDE == 3.5
    assert signals_from_observations([_persisted_earthquake(3.4)]) == []


def test_magnitude_3_5_emits_dashboard_signal():
    signals = signals_from_observations([_persisted_earthquake(3.5)])

    assert len(signals) == 1
    assert signals[0].value == 3.5


def test_magnitude_4_6_keeps_existing_signal_behavior():
    signal = signals_from_observations([_persisted_earthquake(4.6)])[0]

    assert signal.hazard == "earthquake"
    assert signal.value == 4.6
    assert signal.location.latitude == 31.75
    assert signal.evidence["earthquake"]["provider_event_id"] == "gsi-m4.6"


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value

    def mappings(self):
        return self

    def all(self):
        return self.value


class _TownSession:
    def __init__(self):
        self.calls = []
        self.results = iter([
            _Result(True),
            _Result(True),
            _Result([{
                "town_id": "town-1",
                "name_he": "ירושלים",
                "name_en": "Jerusalem",
                "cbs_code": "3000",
            }]),
        ])

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        return next(self.results)


def test_towns_polygon_lookup_reuses_stored_outline_geometry():
    session = _TownSession()
    geometry = {"type": "Polygon", "coordinates": [[[35, 31], [36, 31], [35, 31]]]}

    result = towns_intersecting(geometry, session_factory=lambda: session)

    assert result.status == TownLookupStatus.SUCCESS_WITH_RESULTS
    assert result.towns[0].name_en == "Jerusalem"
    sql, params = session.calls[-1]
    assert "ST_Intersects(outline::geometry, area.geom)" in sql
    assert '"type": "Polygon"' in params["geojson"]


def test_impact_reuses_same_polygon_for_towns_and_population():
    received = []

    def town_query(geometry):
        received.append(geometry)
        return TownIntersectionResult(
            status=TownLookupStatus.SUCCESS_WITH_RESULTS,
            towns=[TownIntersection(
                town_id="town-1",
                name_he="ירושלים",
                name_en="Jerusalem",
                cbs_code="3000",
            )],
        )

    def population_query(geometry):
        received.append(geometry)
        return {
            "grid_available": True,
            "intersected_cell_count": 7,
            "weighted_population": 1234.6,
        }

    impact = estimate_impact(
        {
            "provider_event_id": "gsi2026abcd",
            "observed_at": NOW.isoformat(),
            "latitude": 31.75,
            "longitude": 35.21,
            "magnitude": 4.6,
            "depth_km": 12.4,
            "provider": "GSI",
        },
        town_query=town_query,
        population_query=population_query,
    )

    assert received[0] is received[1]
    assert impact.radius_km == 25.0
    assert impact.population_summary == {
        "status": "available",
        "estimated_population": 1235,
        "intersected_cell_count": 7,
        "reason": None,
    }
    assert "actual damage" in LIMITATION


def test_shared_event_feed_accepts_earthquake_contract():
    area = GeoJsonPolygon(coordinates=[[[35.0, 31.0], [35.1, 31.0], [35.0, 31.0]]])
    event = EarthquakeSharedEvent(
        id="INC-20260920-0001",
        title="Earthquake M4.6",
        description="GSI earthquake with a deterministic Estimated Impact Area.",
        latitude=31.75,
        longitude=35.21,
        observed_at=NOW,
        classification="emergency",
        analysis_status="success",
        planning_status="skipped",
        details=EarthquakeDetails(
            provider_event_id="gsi2026abcd",
            magnitude=4.6,
            depth_km=12.4,
            estimated_impact_radius_km=25,
            estimated_impact_area=area,
            towns=[EarthquakeTown(
                town_id="town-1",
                name_he="ירושלים",
                name_en="Jerusalem",
                cbs_code="3000",
            )],
            towns_status="available",
            population_summary=EarthquakePopulationSummary(
                status="available",
                estimated_population=1235,
                intersected_cell_count=7,
            ),
            source="https://seis.gsi.gov.il/fdsnws/event/1/query",
            limitations=[LIMITATION],
        ),
    )
    row = {
        "incident_id": event.id,
        "event_payload": event.model_dump(mode="json"),
        "last_successful_event_payload": None,
        "route": "emergency",
        "processing_status": "success",
        "failure_stage": None,
        "failure_reason": None,
        "retryable": False,
        "attempt_count": 1,
        "last_attempt_at": NOW,
        "processed_at": NOW,
    }

    delivered = shared_event_feed([row]).events[0]

    assert delivered.type == "earthquake"
    assert delivered.details.population_summary.wording == (
        "Estimated population geographically located within the impact area"
    )
