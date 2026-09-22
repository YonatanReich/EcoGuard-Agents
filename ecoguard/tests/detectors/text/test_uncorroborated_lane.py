"""The uncorroborated lane, end to end and offline.

Replaces the old tier model: there is no authority/unofficial split, nothing
waits in a weak-event holding pen, and a report nobody can confirm reaches the
operator as an advisory naming who to phone instead of expiring unseen.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ecoguard.coordinator.dispatcher import (
    IncidentDispatchContext,
    is_uncorroborated_report,
)
from ecoguard.detectors.text.triage import Report, triage
from ecoguard.response_planner.uncorroborated.incident_handler import (
    UncorroboratedReportHandler,
)
from ecoguard.response_planner.uncorroborated.planner import (
    UncorroboratedReportPlanner,
)

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)

PARTIES = {
    "authority": {
        "name": "רמת גן", "type": "municipality", "phone": "03-6753333",
        "address": "המעגל 26", "website": None,
    },
    "police_station": {
        "name": "תחנת בני ברק", "phone": "03-6796444",
        "address": "ז'בוטינסקי 45", "basis": "responsible",
    },
    "nearest_fire_station": {"name": "תחנת כיבוי רמת גן", "distance_m": 1200},
}


def report(candidate_id=1, origin="message:-100:1", tier="unofficial", **over):
    fields = dict(
        candidate_id=candidate_id,
        observation_id=1000 + candidate_id,
        source_id="telegram:-1001411503185",
        tier=tier,
        hazard="fire",
        observed_at=NOW - timedelta(minutes=5),
        text="Fire in an apartment block.",
        origin_key=origin,
        latitude=32.07056,
        longitude=34.827687,
        precision_m=2290.67,
        location_text="רמת גן",
        update_type="new",
        claim="Fire in an apartment block.",
    )
    fields.update(over)
    return Report(**fields)


def planner():
    return UncorroboratedReportPlanner(parties_lookup=lambda **_: PARTIES)


# --------------------------------------------------------------------------
# Triage: tiers are gone, nothing waits
# --------------------------------------------------------------------------


def test_a_lone_report_is_uncorroborated_not_parked():
    outcome = triage([report()], at=NOW)

    assert outcome.events == []
    assert len(outcome.uncorroborated) == 1
    assert outcome.uncorroborated[0]["basis"]["kind"] == "uncorroborated_report"


def test_source_tier_no_longer_decides_anything():
    """An 'authority' report gets the same treatment as any other claim."""
    authority = triage([report(tier="authority")], at=NOW)
    unofficial = triage([report(tier="unofficial")], at=NOW)

    assert len(authority.uncorroborated) == len(unofficial.uncorroborated) == 1
    assert authority.events == unofficial.events == []


def test_two_independent_origins_corroborate():
    """Distinct origins AND distinct wording: two witnesses, not one repost."""
    outcome = triage(
        [
            report(1, "message:-100:1", text="Fire in an apartment block.",
                   claim="Fire in an apartment block."),
            report(2, "message:-200:7",
                   text="Smoke pouring from a residential building on Bialik.",
                   claim="Smoke pouring from a residential building on Bialik."),
        ],
        at=NOW,
    )

    assert len(outcome.events) == 2
    assert outcome.uncorroborated == []


def test_the_same_claim_retyped_does_not_corroborate_itself():
    """Different channels, different post ids, same sentence: still one claim.

    It neither corroborates nor produces a second advisory — an operator
    ringing the same police station twice about one rumour is the failure this
    prevents.
    """
    outcome = triage(
        [report(1, "message:-100:1"), report(2, "message:-200:7")], at=NOW
    )

    assert outcome.events == []
    assert len(outcome.uncorroborated) == 1
    assert outcome.skipped[0]["reason"] == "same_claim_already_reported"


def test_forwards_of_one_message_do_not_corroborate_each_other():
    """Ten channels forwarding one claim is one claim."""
    same = "message:-100:1"
    outcome = triage([report(i, same, observation_id=9000 + i) for i in range(1, 6)], at=NOW)

    assert outcome.events == []
    assert len(outcome.uncorroborated) == 1          # one advisory, not five


def test_instrument_evidence_corroborates_but_a_rumour_incident_does_not():
    """An incident built only from text must not confirm the next rumour."""
    rumour_incident = {
        "id": "INC-RUMOUR", "hazards": ["fire"],
        "latitude": 32.07056, "longitude": 34.827687,
        "precision_m": 2290.0, "last_signal_at": NOW,
        "signals": [{"variable": "report", "evidence": {"text_report": {"corroborated": False}}}],
    }
    firms_incident = {**rumour_incident, "id": "INC-FIRMS",
                      "signals": [{"variable": "frp", "evidence": {}}]}

    assert triage([report()], open_incidents=[rumour_incident], at=NOW).events == []
    assert len(triage([report()], open_incidents=[firms_incident], at=NOW).events) == 1


def test_a_retraction_never_auto_closes_without_tiers():
    outcome = triage([report(update_type="false_alarm")], at=NOW)

    assert outcome.closed == []
    assert outcome.skipped[0]["reason"] == "retraction_recorded_not_acted_on"


# --------------------------------------------------------------------------
# Dispatcher routing
# --------------------------------------------------------------------------


def _incident(signals):
    return {
        "id": "INC-1", "status": "open", "primary_hazard": "fire",
        "hazards": ["fire"], "queues": ["emergency"],
        "latitude": 32.07056, "longitude": 34.827687, "signals": signals,
    }


def _text_signal(corroborated):
    return {
        "variable": "report", "observed_at": NOW,
        "evidence": {"text_report": {
            "corroborated": corroborated,
            "claim": "Fire in an apartment block.",
            "location_text": "רמת גן",
        }},
    }


def test_text_only_incident_routes_to_the_uncorroborated_handler():
    assert is_uncorroborated_report(_incident([_text_signal(False)])) is True


def test_one_instrument_signal_upgrades_the_incident_automatically():
    """The upgrade needs no rewrite: the incident stops meeting the test."""
    incident = _incident([_text_signal(False), {"variable": "frp", "evidence": {}}])

    assert is_uncorroborated_report(incident) is False


def test_a_corroborated_text_report_is_not_the_uncorroborated_lane():
    assert is_uncorroborated_report(_incident([_text_signal(True)])) is False


def test_an_incident_with_no_signals_is_not_assumed_to_be_a_rumour():
    assert is_uncorroborated_report(_incident([])) is False


# --------------------------------------------------------------------------
# The advisory itself
# --------------------------------------------------------------------------


def test_advisory_names_the_responsible_station_and_authority_with_phones():
    result = UncorroboratedReportHandler(planner=planner()).process(
        _incident([_text_signal(False)]),
        IncidentDispatchContext(
            incident_id="INC-1", hazard="fire", route="emergency",
            analysis_id="a", coordinator_routing_id="r", routed_by="t",
            routed_at=NOW, requested_at=NOW,
        ),
    )

    assert result.planner_status == "success"
    # The analyser is skipped outright - that is the design, not an omission.
    assert result.analysis_status == "skipped"
    assert result.analysis_result is None
    assert result.risk_assessment is None
    assert result.requires_resource_allocation is False

    plan = result.planner_result
    text = " ".join(action["action"] for action in plan["actions"])
    assert "03-6796444" in text                      # responsible police station
    assert "03-6753333" in text                      # local authority
    assert "102" in text                             # fire escalation number
    assert plan["contacts"]["police_station"]["basis"] == "responsible"
    assert any("unverified" in item.lower() for item in plan["limitations"])


def test_advisory_falls_back_to_national_numbers_when_nothing_is_on_file():
    empty = UncorroboratedReportPlanner(parties_lookup=lambda **_: {})
    plan = empty.plan(
        hazard="fire", latitude=32.07, longitude=34.82, location_text="somewhere"
    ).as_dict()

    assert "100" in " ".join(action["action"] for action in plan["actions"])


def test_advisory_survives_a_lookup_failure():
    def boom(**_):
        raise RuntimeError("db down")

    plan = UncorroboratedReportPlanner(parties_lookup=boom).plan(
        hazard="flood", latitude=32.07, longitude=34.82
    )

    assert plan.status == "success"
    assert "100" in " ".join(action["action"] for action in plan.actions)


def test_no_location_means_no_invented_contacts():
    plan = planner().plan(hazard="fire", latitude=None, longitude=None)

    assert plan.status == "skipped"
    assert plan.reason == "no_resolvable_location"
    assert plan.actions == []


if __name__ == "__main__":
    for name, case in sorted(globals().items()):
        if name.startswith("test_") and callable(case):
            case()
            print(f"ok  {name}")
    print("\nuncorroborated lane checks passed")


# --------------------------------------------------------------------------
# Projection: what the operator's feed actually receives
# --------------------------------------------------------------------------


def test_the_advisory_reaches_the_frontend_feed_as_its_own_type():
    """It must never render with the same marker as a confirmed event."""
    from ecoguard.coordinator.dispatcher import dispatch_incidents
    from ecoguard.coordinator.event_projection import project_processing_results

    incident = _incident([_text_signal(False)])
    writes = []

    results = dispatch_incidents(
        [incident],
        registry={("*", "uncorroborated"): UncorroboratedReportHandler(planner=planner())},
        at=NOW,
        projection_reader=lambda _: None,
    )
    assert [r.route for r in results] == ["uncorroborated"]

    project_processing_results(
        results,
        incident_reader=lambda _: incident,
        projection_reader=lambda _: None,
        writer=lambda record: writes.append(record),
    )

    assert len(writes) == 1
    event = writes[0].event_payload
    assert event["type"] == "other"                  # not "fire"
    assert event["classification"] == "advisory"     # not "emergency"
    assert event["analysis_status"] == "skipped"
    assert event["details"]["kind"] == "uncorroborated_report"
    assert event["details"]["claimed_hazard"] == "fire"
    assert event["details"]["corroborated"] is False
    assert event["details"]["contacts"]["police_station"]["phone"] == "03-6796444"
    assert "Unverified" in event["title"]
