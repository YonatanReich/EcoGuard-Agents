from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ecoguard.analyzers.emergency.earthquake.impact import (
    LIMITATION,
    estimate_impact,
    estimated_impact_radius_km,
)
from ecoguard.response_planner.emergency.adapters import build_earthquake_plan_input
from ecoguard.api import events as event_api
from ecoguard.api.events import shared_event_feed
from ecoguard.analyzers.emergency.earthquake import incident_handler as earthquake_handler
from ecoguard.coordinator.dispatcher import IncidentDispatchContext
from ecoguard.coordinator.dispatcher import IncidentProcessingResult
from ecoguard.coordinator.event_projection import earthquake_shared_event
from ecoguard.analyzers.emergency.earthquake.risk_scale import earthquake_operational_risk
from ecoguard.collection.earthquake.gsi import normalize_fdsn_text
from ecoguard.resource_allocator.allocation_agent import ResourceAllocationAgent
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

    # The towns lookup and the summary population must describe the same area,
    # or the two numbers on the event card are about different places. They are
    # the first and last queries: the ones between them are the per-band
    # population counts, each over its own nested intensity ring.
    assert received[0] is received[-1]
    assert len(received) > 2, "the intensity bands should each be counted"
    # Was 25.0 from the magnitude-only table. The intensity equation puts
    # the MMI IV ring for this event at 24.68 km -- close enough to be a
    # quiet check that the invented band was not wildly off for a moderate
    # shallow earthquake, which is where it was least wrong.
    assert impact.radius_km == pytest.approx(24.68, abs=0.01)
    assert impact.max_mmi == 5.1
    # Nothing here reaches MMI VI, so nobody is at damaging intensity. A
    # counted zero, not an unreadable one.
    assert impact.population_at_damaging_intensity == 0
    assert impact.population_summary == {
        "status": "available",
        "estimated_population": 1235,
        "intersected_cell_count": 7,
        "reason": None,
    }
    assert "actual damage" in LIMITATION

    planner_input = build_earthquake_plan_input(
        impact,
        incident_id="INC-EQ-1",
    )
    assert planner_input.hazard_type == "earthquake"
    assert planner_input.incident_id == "INC-EQ-1"
    assert planner_input.location.model_dump() == {
        "latitude": 31.75,
        "longitude": 35.21,
    }
    # This asserted None until earthquake gained a score on the shared scale.
    # It is derived, not invented: M4.6 sets the band, the counted population
    # inside the impact area moves it, and the basis records which of the two
    # were available.
    # Severity now reads the people at damaging intensity, not everyone who
    # felt it. This event shakes 1,235 people at MMI IV-V and nobody at VI or
    # above, so the magnitude band is adjusted down rather than up.
    assert planner_input.risk_context == {
        "risk_semantics": "detected_event_operational_risk",
        "risk_score": 40,
        "risk_level": "medium",
        "population_at_risk": 0,
        "basis": "magnitude_and_population",
    }
    assert planner_input.additional_context["magnitude"] == 4.6
    assert planner_input.additional_context["depth_km"] == 12.4
    assert planner_input.additional_context["town_intersection"]["towns"][0][
        "name_en"
    ] == "Jerusalem"
    assert planner_input.additional_context["population_summary"][
        "estimated_population"
    ] == 1235
    assert planner_input.limitations == [LIMITATION]
    serialized = planner_input.model_dump_json().lower()
    # risk_score and risk_level used to be asserted absent here, back when
    # earthquake carried no operational risk at all. They are present now and
    # checked above, derived from the magnitude and a counted population.
    #
    # What must still never appear is a damage claim. This analyser models no
    # casualties and no structural collapse -- the impact area is a screening
    # radius -- so a number for either would be invented, and invented numbers
    # in a plan input are the ones an operator acts on.
    assert "casualt" not in serialized
    assert "collapsed building" not in serialized


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


def test_earthquake_handler_invokes_and_preserves_successful_planner(monkeypatch):
    impact = SimpleNamespace(
        provider_event_id="gsi2026abcd",
        observed_at=NOW,
        latitude=31.75,
        longitude=35.21,
        magnitude=4.6,
        depth_km=12.4,
        radius_km=25.0,
        area={"type": "Polygon", "coordinates": []},
        towns=TownIntersectionResult(
            status=TownLookupStatus.SUCCESS_EMPTY,
            towns=[],
        ),
        population_at_damaging_intensity=1235,
        population_summary={
            "status": "unavailable",
            "estimated_population": None,
            "intersected_cell_count": None,
            "reason": "population_grid_not_loaded",
        },
        provider="GSI",
        source="https://seis.gsi.gov.il/fdsnws/event/1/query",
    )
    monkeypatch.setattr(earthquake_handler, "estimate_impact", lambda _: impact)

    class Planner:
        def __init__(self):
            self.inputs = []

        def plan_response(self, planner_input):
            self.inputs.append(planner_input)
            return {
                "metadata": {"planning_status": "success"},
                "hazard_type": "earthquake",
                "recommended_units": ["fire_department"],
                "response_actions": [],
            }

    planner = Planner()
    handler = earthquake_handler.EarthquakeIncidentHandler(planner=planner)
    context = IncidentDispatchContext(
        incident_id="INC-EQ-1",
        hazard="earthquake",
        route="emergency",
        analysis_id="analysis-1",
        coordinator_routing_id="routing-1",
        routed_by="test",
        routed_at=NOW,
        requested_at=NOW,
    )
    result = handler.process({
        "signals": [{"evidence": {"earthquake": {
            "provider_event_id": "gsi2026abcd",
            "observed_at": NOW.isoformat(),
        }}}],
    }, context)

    assert planner.inputs[0].hazard_type == "earthquake"
    assert result.planner_status == "success"
    assert result.planner_result["recommended_units"] == ["fire_department"]
    assert result.analysis_result is impact


def test_earthquake_projection_exposes_plan_allocation_route_and_policy(monkeypatch):
    impact = SimpleNamespace(
        provider_event_id="gsi2026abcd",
        observed_at=NOW,
        latitude=31.75,
        longitude=35.21,
        magnitude=4.6,
        depth_km=12.4,
        radius_km=25.0,
        area={
            "type": "Polygon",
            "coordinates": [[[35.0, 31.0], [35.1, 31.0], [35.0, 31.0]]],
        },
        towns=TownIntersectionResult(
            status=TownLookupStatus.SUCCESS_EMPTY,
            towns=[],
        ),
        population_at_damaging_intensity=1235,
        population_summary={
            "status": "unavailable",
            "estimated_population": None,
            "intersected_cell_count": None,
            "reason": "population_grid_not_loaded",
        },
        provider="GSI",
        source="https://seis.gsi.gov.il/fdsnws/event/1/query",
    )
    result = IncidentProcessingResult(
        incident_id="INC-EQ-1",
        hazard="earthquake",
        route="emergency",
        status="success",
        requested_at=NOW,
        completed_at=NOW,
        analysis_status="success",
        planner_status="success",
        analysis_result=impact,
        planner_result={
            "plan_summary": "Coordinate an initial multi-agency response.",
            "recommended_units": ["fire_department", "home_front_command"],
            "response_actions": [{
                "action": "Coordinate initial response at the reported epicenter.",
                "responsible_unit": "fire_department",
                "timeframe": "immediate",
                "supporting_protocol_chunk_ids": ["official#response#0"],
            }],
            "evidence_gaps": ["Actual damage is unknown."],
            "limitations": [LIMITATION],
            "grounding": {"citations": []},
        },
        resource_allocation_result={
            "status": "partial",
            "routing_status": "complete",
            "requirements": {
                "fire_department": {"requested": 1, "assigned": 1, "shortfall": 0},
                "home_front_command": {"requested": 1, "assigned": 0, "shortfall": 1},
            },
            "shortages": {},
            "unsupported_units": ["home_front_command"],
            "allocation_policy": "earthquake_minimum_response_v1",
            "allocation_basis": "protocol_recommended_units",
            "quantity_source": "ecoguard_minimum_response_policy",
            "errors": [],
            "allocated_units": {"fire_stations": [{
                "database_id": 7,
                "name": "Existing Fire Station",
                "address": "Station address",
                "unit_type": "fire_station",
                "recommended_unit": "fire_department",
                "latitude": 31.8,
                "longitude": 35.2,
                "distance_km": 8.2,
                "allocation_status": "assigned",
                "selection_reason": "shortest_road_travel_time",
                "route": {
                    "status": "complete",
                    "provider": "mapbox",
                    "profile": "mapbox/driving-traffic",
                    "distance_m": 8200,
                    "duration_s": 600,
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[35.2, 31.8], [35.21, 31.75]],
                    },
                    "estimated_arrival_at": "2026-09-20T10:40:00Z",
                    "road_access_verified": True,
                    "requires_field_access_confirmation": False,
                    "steps_he": [],
                },
            }]},
        },
    )
    event = earthquake_shared_event(result, {"id": "INC-EQ-1"})
    payload = event.model_dump(mode="json")

    assert payload["details"]["recommended_units"] == [
        "fire_department", "home_front_command"
    ]
    allocation = payload["details"]["resource_allocation"]
    assert allocation["allocation_policy"] == "earthquake_minimum_response_v1"
    assert allocation["unsupported_units"] == ["home_front_command"]
    assert allocation["stations"][0]["route"]["estimated_arrival_at"] == (
        "2026-09-20T10:40:00Z"
    )
    row = {
        "incident_id": "INC-EQ-1",
        "event_payload": payload,
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
    delivered = shared_event_feed([row]).model_dump(mode="json")
    delivered_allocation = delivered["events"][0]["details"]["resource_allocation"]
    assert delivered_allocation["stations"][0]["name"] == "Existing Fire Station"
    assert delivered_allocation["allocation_policy"] == (
        "earthquake_minimum_response_v1"
    )

    monkeypatch.setattr(event_api, "read_projected_events", lambda *, limit: [row])
    application = FastAPI()
    application.include_router(event_api.router)
    response = TestClient(application).get("/api/events")

    assert response.status_code == 200
    api_allocation = response.json()["events"][0]["details"]["resource_allocation"]
    assert api_allocation["stations"][0]["route"]["duration_s"] == 600
    assert api_allocation["quantity_source"] == "ecoguard_minimum_response_policy"


# The rows below are copied from a real GSI FDSN response, not composed. The
# fixture above was composed, and it is why this collector passed its tests
# for weeks while being unable to complete a single live fetch: it invented a
# Z suffix GSI does not send and stopped at 13 columns where GSI sends 14.
REAL_GSI_HEADER = (
    "#EventID|Time|Latitude|Longitude|Depth/km|Author|Catalog|Contributor|"
    "ContributorID|MagType|Magnitude|MagAuthor|EventLocationName|EventType"
)
REAL_GSI_EARTHQUAKE = (
    "gsi_loc_2026skyt|2026-09-17T06:41:12.884184|32.6875|35.48468"
    "|8.244140625|dagmara@janalyse||GSI|gsi_loc_2026skyt|MLv"
    "|2.8368797|gsi28jauto.sysop|Galilee|earthquake"
)
REAL_GSI_EXPLOSION = (
    "gsi_loc_2026slcj|2026-09-17T09:20:46.673487|31.10417175292969"
    "|35.161778891958846|0.7405598958333333|dagmara@janalyse||GSI"
    "|gsi_loc_2026slcj|MLv|2.3723277713615034|gsi28jauto.sysop|Negev|explosion"
)


def test_a_real_gsi_row_parses_and_its_naive_time_is_read_as_utc():
    """GSI sends no zone suffix; FDSN text times are UTC by specification."""
    events = normalize_fdsn_text(f"{REAL_GSI_HEADER}\n{REAL_GSI_EARTHQUAKE}\n")

    assert len(events) == 1
    observed = events[0].observed_at
    assert observed.tzinfo is not None, "a naive time fails AwareDatetime"
    assert observed.utcoffset() == timedelta(0)
    assert events[0].raw["event_type"] == "earthquake"


def test_a_quarry_blast_is_not_an_earthquake():
    """Most of what GSI returns is explosions - 37 of 45 in a sample week."""
    payload = f"{REAL_GSI_HEADER}\n{REAL_GSI_EXPLOSION}\n{REAL_GSI_EARTHQUAKE}\n"

    events = normalize_fdsn_text(payload)

    assert [event.provider_event_id for event in events] == ["gsi_loc_2026skyt"]


def test_an_unlabelled_row_is_kept():
    """Absence of a label is not evidence of a blast, and missing a real
    earthquake is the worse of the two errors."""
    unlabelled = REAL_GSI_EARTHQUAKE.rsplit("|", 1)[0] + "|"

    events = normalize_fdsn_text(f"{REAL_GSI_HEADER}\n{unlabelled}\n")

    assert len(events) == 1
    assert events[0].raw["event_type"] is None


# --- operational risk on the shared scale --------------------------------

@pytest.mark.parametrize(
    ("magnitude", "expected"),
    [(3.5, 40), (4.4, 40), (4.5, 60), (5.4, 60), (5.5, 80), (6.4, 80), (6.5, 100)],
)
def test_magnitude_bands_land_on_the_shared_scale(magnitude, expected):
    """Same 40/60/80/100 steps Flood uses, so the two are comparable."""
    score, _ = earthquake_operational_risk(magnitude)
    assert score == expected


def test_population_moves_the_score_in_both_directions():
    """The whole reason the score exists: the same magnitude under a city and
    under open desert are not the same emergency."""
    desert, _ = earthquake_operational_risk(5.0, population_at_risk=0)
    town, _ = earthquake_operational_risk(5.0, population_at_risk=50_000)
    city, _ = earthquake_operational_risk(5.0, population_at_risk=900_000)

    assert desert < town < city
    assert (desert, town, city) == (40, 60, 80)


def test_a_counted_zero_is_not_an_unavailable_count():
    """Nobody there, and nobody could look, must not produce the same score."""
    counted_zero, _ = earthquake_operational_risk(5.0, population_at_risk=0)
    could_not_read, _ = earthquake_operational_risk(5.0, population_at_risk=None)

    assert counted_zero == 40
    assert could_not_read == 60  # magnitude band alone, no adjustment


def test_below_the_dashboard_threshold_has_no_operational_risk():
    with pytest.raises(ValueError):
        earthquake_operational_risk(3.4)


def test_a_large_earthquake_under_a_city_outranks_a_moderate_fire():
    """The defect this closes: an M6.0 used to queue behind a brush fire.

    _priority_key had returned a leading 1 for earthquake against 0 for
    everything else, and tuple comparison decides at index 0.
    """
    earthquake_score, _ = earthquake_operational_risk(6.0, population_at_risk=600_000)
    moderate_fire_score = 55

    ranked = sorted(
        [
            {"incident_id": "INC-EQ", "effective_priority": float(earthquake_score),
             "risk_score": float(earthquake_score), "urgency": 0,
             "queued_at": NOW},
            {"incident_id": "INC-FIRE", "effective_priority": float(moderate_fire_score),
             "risk_score": float(moderate_fire_score), "urgency": 0,
             "queued_at": NOW},
        ],
        key=ResourceAllocationAgent._priority_key,
    )

    assert [item["incident_id"] for item in ranked] == ["INC-EQ", "INC-FIRE"]
