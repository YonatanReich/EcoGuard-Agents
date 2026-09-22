"""Corroboration, and the edges either side of it.

Every one runs against `triage()` directly: it decides and does not write, so
the whole lane is demonstrable without a database, a model or a network.

The pairs matter more than the cases. "Two reports corroborate" is only
meaningful beside "ten forwards of one report do not", because a rule that
counts reports passes the first and fails the second — and fails it in
production, on a rumour, at three in the morning.

There is no source tier here any more. Nothing is believed because of who
posted it; a report is either corroborated by something independent or it is
passed on labelled uncorroborated.
"""

from datetime import datetime, timedelta, timezone

from ecoguard.detectors.text.triage import (
    CORROBORATION_WINDOW,
    Report,
    distinct_origins,
    near_duplicate,
    origin_key,
    triage,
)

AT = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)

# One place, so every scenario differs only in who reported and how often.
HAIFA = (32.794, 34.989)


def report(
    observation_id: int,
    *,
    tier: str = "unofficial",
    hazard: str = "fire",
    text: str = "שריפה גדולה ביער הכרמל, כוחות כיבוי בדרך",
    origin: str | None = None,
    at: datetime | None = None,
    location=HAIFA,
    precision_m: float = 500.0,
    update_type: str = "new",
) -> Report:
    latitude, longitude = location if location else (None, None)
    return Report(
        candidate_id=observation_id,
        observation_id=observation_id,
        source_id=f"telegram:-100{observation_id}",
        tier=tier,
        hazard=hazard,
        observed_at=at or AT,
        text=text,
        origin_key=origin or f"message:-100{observation_id}:{observation_id}",
        latitude=latitude,
        longitude=longitude,
        precision_m=precision_m,
        location_text="יער הכרמל",
        update_type=update_type,
    )


def incident(
    hazard: str = "fire", *, at: datetime | None = None, location=HAIFA,
    signals=None,
):
    """An open incident. Instrument-backed unless told otherwise.

    `signals` is load-bearing: only instrument evidence corroborates. An
    incident built from text alone is itself an unconfirmed claim, and letting
    it promote the next report would route straight around forward-dedup.
    """
    return {
        "id": "INC-20260921-0001",
        "hazards": [hazard],
        "latitude": location[0],
        "longitude": location[1],
        "precision_m": 375.0,
        "last_signal_at": at or AT,
        "signals": [{"variable": "frp", "evidence": {}}] if signals is None else signals,
    }


# --- a lone report is uncorroborated, not parked ---------------------------

def test_a_lone_report_is_passed_on_as_uncorroborated():
    outcome = triage([report(1)], at=AT)

    assert outcome.events == []
    assert len(outcome.uncorroborated) == 1
    assert outcome.uncorroborated[0]["basis"]["kind"] == "uncorroborated_report"


def test_the_source_tier_changes_nothing():
    """What used to be the whole of rule one: an 'authority' post was an event.

    It is now treated exactly like any other claim, because a self-described
    official channel is still just a channel — three of the four Telegram
    sources on the allowlist describe themselves that way and none could be
    verified.
    """
    for tier in ("authority", "media", "unofficial"):
        outcome = triage([report(1, tier=tier)], at=AT)
        assert outcome.events == [], tier
        assert len(outcome.uncorroborated) == 1, tier


def test_two_distinct_origins_promote_to_an_event():
    outcome = triage(
        [
            report(1, origin="message:-1001:11"),
            report(2, origin="message:-1002:22",
                   text="דיווח על שריפה באזור הכרמל, עשן כבד נראה מרחוק",
                   at=AT + timedelta(minutes=20)),
        ],
        at=AT,
    )

    assert len(outcome.events) == 2
    assert outcome.events[0]["basis"]["kind"] == "independent_reports"
    assert outcome.uncorroborated == []


def test_two_reports_too_far_apart_in_time_do_not_promote():
    # Same place, same hazard, three hours apart — outside the window, so they
    # are two separate claims rather than two witnesses to one event. Different
    # wording, so the near-duplicate collapse is not what separates them here.
    outcome = triage(
        [
            report(1, origin="message:-1001:11"),
            report(2, origin="message:-1002:22",
                   text="עשן כבד נראה מכיוון הכרמל, תושבים מדווחים על ריח שרוף",
                   at=AT + CORROBORATION_WINDOW + timedelta(minutes=1)),
        ],
        at=AT,
    )

    assert outcome.events == []
    assert len(outcome.uncorroborated) == 2


def test_two_reports_of_different_hazards_do_not_corroborate_each_other():
    outcome = triage(
        [
            report(1, hazard="fire", origin="message:-1001:11"),
            report(2, hazard="flood", origin="message:-1002:22",
                   text="הצפות ברחוב"),
        ],
        at=AT,
    )

    assert outcome.events == []
    assert len(outcome.uncorroborated) == 2


# --- 4. ten forwards of one message do not promote -------------------------

def test_ten_forwards_of_one_message_are_one_origin_and_do_not_promote():
    # The rule that keeps the unofficial tier from confirming itself. Without
    # forward-dedup this promotes on the second repost, and every rumour on
    # Telegram is an event within a minute.
    forwards = [
        report(index, origin="forward:-100999:5",
               at=AT + timedelta(minutes=index))
        for index in range(1, 11)
    ]

    outcome = triage(forwards, at=AT)

    assert outcome.events == []
    # And one weak event, not ten: the same rule that stops them promoting has
    # to stop them multiplying on the operator's map.
    assert len(outcome.uncorroborated) == 1
    # Nine of the ten are recorded as the same origin rather than silently lost.
    assert [item["reason"] for item in outcome.skipped] == (
        ["same_claim_already_reported"] * 9
    )


def test_a_retyped_copy_is_not_an_independent_origin():
    # No forward metadata at all — a channel that retyped another's post. Text
    # similarity is the only thing left to catch it.
    outcome = triage(
        [
            report(1, origin="message:-1001:11",
                   text="שריפה גדולה ביער הכרמל, כוחות כיבוי בדרך"),
            report(2, origin="message:-1002:22",
                   text="שריפה גדולה ביער הכרמל, כוחות כיבוי בדרך!",
                   at=AT + timedelta(minutes=5)),
        ],
        at=AT,
    )

    assert outcome.events == []
    assert len(outcome.uncorroborated) == 1


def test_two_genuinely_different_wordings_remain_independent():
    # The other side of that boundary. Two witnesses describe one fire in
    # their own words and share little but the place name; treating those as
    # duplicates would suppress exactly the corroboration we want.
    assert not near_duplicate(
        "שריפה גדולה ביער הכרמל, כוחות כיבוי בדרך",
        "עשן כבד נראה מכיוון הכרמל, תושבים מדווחים על ריח שרוף",
    )


def test_origin_key_prefers_the_original_over_the_repeater():
    forwarded = origin_key({
        "peer_id": -1001, "message_id": 77,
        "forwarded_provenance": {"origin_peer_id": -100999, "origin_message_id": 5},
    })
    direct = origin_key({"peer_id": -1001, "message_id": 77})

    assert forwarded == "forward:-100999:5"
    assert direct == "message:-1001:77"
    # Two channels forwarding the same post produce the same key.
    assert forwarded == origin_key({
        "peer_id": -1002, "message_id": 88,
        "forwarded_provenance": {"origin_peer_id": -100999, "origin_message_id": 5},
    })


def test_distinct_origins_collapses_forwards_and_copies_together():
    reports = [
        report(1, origin="forward:-100999:5"),
        report(2, origin="forward:-100999:5"),
        report(3, origin="message:-1003:33",
               text="עשן כבד נראה מכיוון הכרמל, תושבים מדווחים"),
    ]

    assert distinct_origins(reports) == 2


# --- 5. structured evidence promotes ---------------------------------------

def test_an_open_incident_from_instrument_data_promotes_an_unofficial_report():
    # The FIRMS hotspot case. No new code reads FIRMS here: a hotspot is
    # already an open fire incident, so "is there satellite evidence near this
    # rumour" is asked of the store that already knows.
    outcome = triage([report(1)], open_incidents=[incident("fire")], at=AT)

    assert len(outcome.events) == 1
    basis = outcome.events[0]["basis"]
    assert basis["kind"] == "structured_evidence"
    assert basis["incident_id"] == "INC-20260921-0001"


def test_an_incident_of_another_hazard_does_not_promote():
    # A flood incident in the same street says nothing about a fire.
    outcome = triage([report(1, hazard="fire")], open_incidents=[incident("flood")], at=AT)

    assert outcome.events == []
    assert len(outcome.uncorroborated) == 1


def test_a_distant_incident_does_not_promote():
    outcome = triage(
        [report(1)],
        open_incidents=[incident("fire", location=(31.0, 34.8))],
        at=AT,
    )

    assert outcome.events == []


def test_an_incident_built_only_from_text_does_not_corroborate():
    """The self-corroboration trap, now that rumours become incidents too.

    Report A opens an incident; forward B lands nearby and sees "an open fire
    incident". Counting that would promote B on the strength of A and route
    straight around forward-dedup, so only instrument evidence counts.
    """
    rumour = incident("fire", signals=[
        {"variable": "report", "evidence": {"text_report": {"corroborated": False}}},
    ])

    outcome = triage([report(1)], open_incidents=[rumour], at=AT)

    assert outcome.events == []
    assert len(outcome.uncorroborated) == 1


# --- retractions ------------------------------------------------------------

def test_a_retraction_is_recorded_but_never_closes_anything():
    """Without tiers nothing can tell an authoritative retraction from any other
    message, and auto-closing a live incident on an unverifiable say-so is the
    one error in this lane that gets somebody hurt.
    """
    for tier in ("authority", "unofficial"):
        outcome = triage([report(1, tier=tier, update_type="false_alarm")], at=AT)
        assert outcome.closed == [], tier
        assert outcome.events == [], tier
        assert outcome.uncorroborated == [], tier
        assert outcome.skipped[0]["reason"] == "retraction_recorded_not_acted_on"


# --- the location floor ----------------------------------------------------

def test_a_report_with_no_location_never_becomes_an_event():
    # There is nowhere to send anyone, nothing to put on a map, and no town
    # whose police station the advisory could name.
    outcome = triage([report(1, location=None)], at=AT)

    assert outcome.events == []
    assert outcome.uncorroborated == []
    assert outcome.skipped[0]["reason"] == "no_resolvable_location"
