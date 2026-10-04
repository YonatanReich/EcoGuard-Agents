"""The demo page must be able to say what a run will look for, before it runs.

A score means nothing to someone who was not told what was asked. The authored
events used to exist only inside the scenario modules and the command-line
grader, so the dashboard button could start a run nobody had seen the shape of.
"""

from ecoguard.api.scenario import SCENARIOS, scenario_catalog


def test_every_startable_scenario_is_in_the_catalog():
    """A scenario that can be started but not explained is the gap this closes."""
    catalog = {item["id"] for item in scenario_catalog()["scenarios"]}

    assert catalog == set(SCENARIOS)


def test_each_scenario_lists_the_events_it_was_built_to_contain():
    """The modal shows these before offering to run anything."""
    for scenario in scenario_catalog()["scenarios"]:
        assert scenario["event_count"] > 0, scenario["id"]
        assert len(scenario["events"]) == scenario["event_count"]
        assert scenario["blurb"], "a scenario has to say what it is for"

        for event in scenario["events"]:
            assert event["id"]
            assert event["event"], "every authored event describes itself"
            assert event["hazard"]


def test_the_catalog_carries_no_answers_the_run_should_produce():
    """It says what was planted, not what the system found.

    Leaking an incident id or a verdict here would let the page show a result
    the run has not produced yet.
    """
    for scenario in scenario_catalog()["scenarios"]:
        for event in scenario["events"]:
            assert "verdict" not in event
            assert "incident_id" not in event


def test_flood_explanations_distinguish_detection_from_severity():
    """Both demos explain the regime-specific rule, not the severity band."""
    catalog = scenario_catalog()["scenarios"]

    for scenario in catalog:
        flood = next(
            event for event in scenario["events"] if event["hazard"] == "flood"
        )
        notes = flood["notes"]

        assert "ephemeral" in notes
        assert "1 m3/s" in notes
        assert "perennial" in notes
        assert "flowing-baseline" in notes
        assert "Q2" in notes
        assert "severity" in notes
