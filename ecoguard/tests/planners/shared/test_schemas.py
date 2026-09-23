import pytest
from pydantic import ValidationError

from ecoguard.planners.shared.schemas import EmergencyResponsePlanInput


def valid_input(**overrides):
    payload = {
        "hazard_type": "fire",
        "event_description": "Active fire near homes with strong winds.",
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("hazard", ["fire", "flood", "earthquake"])
def test_input_supports_only_current_emergency_hazards(hazard):
    contract = EmergencyResponsePlanInput(**valid_input(hazard_type=hazard))
    assert contract.hazard_type == hazard


@pytest.mark.parametrize("field", ["hazard_type", "event_description"])
def test_only_hazard_and_description_are_required(field):
    payload = valid_input()
    payload.pop(field)
    with pytest.raises(ValidationError):
        EmergencyResponsePlanInput(**payload)


def test_optional_analyzer_context_is_opaque_and_preserved():
    contract = EmergencyResponsePlanInput(
        **valid_input(
            incident_id="INC-1",
            location={"latitude": 31.9, "longitude": 34.8},
            risk_context={"upstream_label": "urgent", "score": 0.82},
            evidence_gaps=["Population not supplied"],
            limitations=["Remote observation"],
            additional_context={"analyzer": "future-analyzer", "custom": [1, 2]},
        )
    )
    assert contract.risk_context == {"upstream_label": "urgent", "score": 0.82}
    assert contract.additional_context["analyzer"] == "future-analyzer"


def test_unsupported_hazard_and_empty_description_are_rejected():
    with pytest.raises(ValidationError):
        EmergencyResponsePlanInput(**valid_input(hazard_type="tsunami"))
    with pytest.raises(ValidationError):
        EmergencyResponsePlanInput(**valid_input(event_description="   "))


def test_incompatible_exposure_fields_are_not_part_of_the_shared_root():
    with pytest.raises(ValidationError):
        EmergencyResponsePlanInput(
            **valid_input(affected_population=500, roads_at_risk=[])
        )
