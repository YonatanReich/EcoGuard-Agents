"""EA-371 additional verification tests using existing evidence only."""

from types import SimpleNamespace

from ecoguard.analyzers.air_pollution.additional_verification import (
    AirPollutionAdditionalVerificationService,
)
from ecoguard.analyzers.air_pollution.event_analysis_schemas import (
    AirPollutionEventQualification,
)
from ecoguard.analyzers.air_pollution.official_classification import (
    classify_official_pollutant_sub_index,
)
from ecoguard.tests.analyzers.air_pollution.test_event_analyzer import (
    GENERATED_AT,
)


def _qualification():
    return AirPollutionEventQualification(
        qualified=True,
        path="PATH_A",
        reason="same_pollutant_different_station_spatial_corroboration",
    )


def _analysis(*, wind=True):
    result = (
        SimpleNamespace(wind_evidence=SimpleNamespace(provider="IMS"))
        if wind else None
    )
    return SimpleNamespace(transport_analysis=SimpleNamespace(result=result))


def _classification(value):
    return classify_official_pollutant_sub_index(
        pollutant="NO2", pollutant_sub_index=value
    )


def test_moderate_is_context_only_and_does_not_check_firms():
    calls = []
    service = AirPollutionAdditionalVerificationService(
        firms_run_reader=lambda: calls.append(True)
    )

    result = service.verify(
        incident={"links": []},
        analysis=_analysis(),
        qualification=_qualification(),
        classification=_classification(25),
        checked_at=GENERATED_AT,
    )

    assert result.status == "CONTEXT_ONLY"
    assert calls == []


def test_existing_fire_link_is_possible_source_correlation_not_causation():
    service = AirPollutionAdditionalVerificationService(
        firms_run_reader=lambda: None
    )
    incident = {"links": [{
        "cause_hazard": "fire",
        "effect_hazard": "air_pollution",
        "cause_incident": "INC-FIRE-1",
        "distance_km": 4.2,
        "bearing_deg": 145.0,
        "lag_hours": 1.5,
        "rationale": "legacy coordinator audit rationale",
    }]}

    result = service.verify(
        incident=incident,
        analysis=_analysis(),
        qualification=_qualification(),
        classification=_classification(-25),
        checked_at=GENERATED_AT,
    )

    assert result.status == "CORROBORATED"
    correlation = result.possible_source_correlations[0]
    assert correlation.source_incident_id == "INC-FIRE-1"
    assert "Possible source correlation only" in correlation.statement
    assert "confirm causation" in correlation.statement


def test_successful_shared_evidence_check_without_match_is_not_disqualifying():
    service = AirPollutionAdditionalVerificationService(
        firms_run_reader=lambda: {"status": "ok", "rows_written": 0}
    )

    result = service.verify(
        incident={"links": []},
        analysis=_analysis(),
        qualification=_qualification(),
        classification=_classification(-250),
        checked_at=GENERATED_AT,
    )

    assert result.status == "NO_EXTERNAL_EVIDENCE"
    assert result.possible_source_correlations == []
    assert "does not mean" in result.limitations[1]


def test_missing_provider_state_or_wind_is_verification_unavailable():
    service = AirPollutionAdditionalVerificationService(
        firms_run_reader=lambda: {"status": "failed"}
    )

    no_wind = service.verify(
        incident={"links": []},
        analysis=_analysis(wind=False),
        qualification=_qualification(),
        classification=_classification(-25),
        checked_at=GENERATED_AT,
    )
    failed_firms = service.verify(
        incident={"links": []},
        analysis=_analysis(),
        qualification=_qualification(),
        classification=_classification(-25),
        checked_at=GENERATED_AT,
    )

    assert no_wind.status == "VERIFICATION_UNAVAILABLE"
    assert no_wind.reason == "compatible_wind_evidence_unavailable"
    assert failed_firms.status == "VERIFICATION_UNAVAILABLE"
    assert failed_firms.reason == "firms_evidence_unavailable"
