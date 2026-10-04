"""An unconfirmed fire's card carries the verification steps, not an empty plan."""

from ecoguard.coordinator.event_projection import fire_shared_event
from ecoguard.planners.uncorroborated.planner import UncorroboratedReportPlanner


def test_unconfirmed_fire_card_lists_who_to_call():
    advisory = UncorroboratedReportPlanner(parties_lookup=lambda **_: {
        "police_station": {"name": "תחנת מסובים", "phone": "03-5384425", "basis": "responsible"},
        "authority": {"name": "גבעת שמואל", "phone": "03-5319222"},
    }).plan(
        hazard="fire", latitude=32.0775, longitude=34.8522,
        location_text="גבעת שמואל", analysis_performed=True,
    ).as_dict()

    event = fire_shared_event(
        {"location": {"latitude": 32.0775, "longitude": 34.8522}},
        planner=advisory,
        incident_id="INC-TEST-1",
    )

    steps = event.details.response_actions
    assert [step.timeframe for step in steps] == ["immediate"] * 3
    assert "03-5384425" in steps[0].action and "תחנת מסובים" in steps[0].action
    assert "03-5319222" in steps[1].action
    assert "102" in steps[2].action
    assert event.description.startswith("Unverified fire report at גבעת שמואל")
