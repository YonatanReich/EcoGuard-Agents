"""The six Phase 3 scenarios, and the edges either side of each.

Every one runs against `triage()` directly: it decides and does not write, so
the whole of §4 is demonstrable without a database, a model or a network.

The pairs matter more than the cases. "Two reports promote" is only meaningful
beside "ten forwards of one report do not", because a rule that promotes on
count alone passes the first and fails the second — and fails it in production,
on a rumour, at three in the morning.
"""

from datetime import datetime, timedelta, timezone

from ecoguard.detectors.text.triage import (
    CORROBORATION_WINDOW,
    WEAK_EVENT_TTL,
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


def incident(hazard: str = "fire", *, at: datetime | None = None, location=HAIFA):
    return {
        "id": "INC-20260921-0001",
        "hazards": [hazard],
        "latitude": location[0],
        "longitude": location[1],
        "precision_m": 375.0,
        "last_signal_at": at or AT,
    }


# --- 1. an official report creates an event --------------------------------

def test_an_official_report_creates_an_event_with_no_corroboration():
    outcome = triage([report(1, tier="authority")], at=AT)

    assert len(outcome.events) == 1
    assert outcome.events[0]["basis"] == {"kind": "official_source", "tier": "authority"}
    assert outcome.weak_events == []


def test_media_is_the_official_path_too():
    # §3: an established outlet creates an event without confirmation. The
    # tier stays distinct from authority so the card can say which.
    outcome = triage([report(1, tier="media")], at=AT)

    assert len(outcome.events) == 1
    assert outcome.events[0]["basis"]["tier"] == "media"


# --- 2. one unofficial report stays weak, and expires ----------------------

def test_a_single_unofficial_report_stays_weak():
    outcome = triage([report(1)], at=AT)

    assert outcome.events == []
    assert len(outcome.weak_events) == 1
    assert outcome.weak_events[0]["expires_at"] == AT + WEAK_EVENT_TTL
    assert outcome.promoted == []


def test_a_weak_event_expires_when_its_window_passes():
    stored = {
        "id": "WEAK-1", "hazard": "fire",
        "latitude": HAIFA[0], "longitude": HAIFA[1], "precision_m": 500.0,
        "first_seen_at": AT - timedelta(hours=4),
        "last_seen_at": AT - timedelta(hours=4),
        "expires_at": AT - timedelta(hours=1),
    }

    outcome = triage([], open_weak_events=[stored], at=AT)

    assert outcome.expired == ["WEAK-1"]


def test_a_weak_event_inside_its_window_is_not_expired():
    stored = {
        "id": "WEAK-1", "hazard": "fire",
        "latitude": HAIFA[0], "longitude": HAIFA[1], "precision_m": 500.0,
        "first_seen_at": AT, "last_seen_at": AT,
        "expires_at": AT + timedelta(hours=1),
    }

    assert triage([], open_weak_events=[stored], at=AT).expired == []


# --- 3. two independent unofficial reports promote -------------------------

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

    assert len(outcome.promoted) == 2
    assert outcome.promoted[0]["basis"]["kind"] == "independent_reports"
    assert outcome.weak_events == []


def test_two_reports_too_far_apart_in_time_do_not_promote():
    # Same place, same hazard, three hours apart — outside the window, so they
    # are two separate claims rather than two witnesses to one event.
    outcome = triage(
        [
            report(1, origin="message:-1001:11"),
            report(2, origin="message:-1002:22",
                   at=AT + CORROBORATION_WINDOW + timedelta(minutes=1)),
        ],
        at=AT,
    )

    assert outcome.promoted == []
    assert len(outcome.weak_events) == 2


def test_two_reports_of_different_hazards_do_not_corroborate_each_other():
    outcome = triage(
        [
            report(1, hazard="fire", origin="message:-1001:11"),
            report(2, hazard="flood", origin="message:-1002:22",
                   text="הצפות ברחוב"),
        ],
        at=AT,
    )

    assert outcome.promoted == []
    assert len(outcome.weak_events) == 2


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

    assert outcome.promoted == []
    # And one weak event, not ten: the same rule that stops them promoting has
    # to stop them multiplying on the operator's map.
    assert len(outcome.weak_events) == 1
    assert len(outcome.weak_events[0]["reports"]) == 10


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

    assert outcome.promoted == []
    assert len(outcome.weak_events) == 1


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

    assert len(outcome.promoted) == 1
    basis = outcome.promoted[0]["basis"]
    assert basis["kind"] == "structured_evidence"
    assert basis["incident_id"] == "INC-20260921-0001"


def test_an_incident_of_another_hazard_does_not_promote():
    # A flood incident in the same street says nothing about a fire.
    outcome = triage([report(1, hazard="fire")], open_incidents=[incident("flood")], at=AT)

    assert outcome.promoted == []
    assert len(outcome.weak_events) == 1


def test_a_distant_incident_does_not_promote():
    outcome = triage(
        [report(1)],
        open_incidents=[incident("fire", location=(31.0, 34.8))],
        at=AT,
    )

    assert outcome.promoted == []


def test_an_official_report_nearby_promotes_an_unofficial_one():
    outcome = triage(
        [
            report(1, tier="unofficial", origin="message:-1001:11"),
            report(2, tier="authority", origin="message:-1002:22",
                   at=AT + timedelta(minutes=10)),
        ],
        at=AT,
    )

    assert len(outcome.events) == 1          # the official one
    assert len(outcome.promoted) == 1        # the unofficial one, carried up
    assert outcome.promoted[0]["basis"]["kind"] == "official_report"


# --- 6. an official false alarm closes an event ----------------------------

def test_an_official_false_alarm_closes():
    outcome = triage([report(1, tier="authority", update_type="false_alarm")], at=AT)

    assert len(outcome.closed) == 1
    assert outcome.closed[0]["reason"] == "official_false_alarm"
    assert outcome.events == []


def test_an_unofficial_retraction_does_not_close_an_event():
    # Anyone can post "false alarm". Only the body responsible for saying so
    # gets to end an event.
    outcome = triage([report(1, tier="unofficial", update_type="false_alarm")], at=AT)

    assert outcome.closed == []
    assert outcome.weak_events == []
    assert outcome.skipped[0]["reason"] == "unofficial_retraction_does_not_close"


# --- the location floor ----------------------------------------------------

def test_a_report_with_no_location_never_becomes_an_event():
    # Not even from an authority. "A post without a place is useless to us" —
    # there is nowhere to send anyone and nothing to put on a map.
    outcome = triage([report(1, tier="authority", location=None)], at=AT)

    assert outcome.events == []
    assert outcome.weak_events == []
    assert outcome.skipped[0]["reason"] == "no_resolvable_location"
