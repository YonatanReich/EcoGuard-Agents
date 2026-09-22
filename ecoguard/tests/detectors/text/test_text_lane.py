"""The lane between triage and the coordinator: placing, signalling, storing."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from ecoguard.database.repositories import weak_events as weak_store
from ecoguard.detectors.text.run import (
    _uncertainty_m,
    locate,
    reports_from_candidates,
    signal_from,
)
from ecoguard.detectors.text.triage import Report

AT = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
HAIFA = (32.794, 34.989)


def candidate(**overrides):
    base = {
        "id": 1,
        "observation_id": 100,
        "source_id": "telegram:-1001411503185",
        "tier": "unofficial",
        "hazard": "fire",
        "observed_at": AT,
        "claim": "fire reported in the Carmel forest",
        "location_text": "חיפה",
        "update_type": "new",
        "payload": {"peer_id": -1001411503185, "message_id": 42},
    }
    return {**base, **overrides}


def stub_locator(_location_text):
    return (HAIFA[0], HAIFA[1], 2000.0)


def no_match(_location_text):
    return None


# --- placing ---------------------------------------------------------------

def test_a_place_the_gazetteer_does_not_know_is_skipped_not_guessed():
    # A model asked for coordinates will supply plausible ones for a town it
    # invented. The gazetteer either knows the place or the report does not
    # become an event.
    located, unplaceable = reports_from_candidates(
        [candidate(location_text="ליד הצומת אחרי הפיצוציה")], locator=no_match
    )

    assert located == []
    assert unplaceable[0]["reason"] == "location_not_in_gazetteer"
    assert unplaceable[0]["location_text"] == "ליד הצומת אחרי הפיצוציה"


def test_the_origin_key_comes_from_the_stored_message_not_the_candidate():
    forwarded = candidate(payload={
        "peer_id": -1001, "message_id": 7,
        "forwarded_provenance": {"origin_peer_id": -100999, "origin_message_id": 5},
    })

    located, _ = reports_from_candidates([forwarded], locator=stub_locator)

    assert located[0].origin_key == "forward:-100999:5"


def test_town_size_becomes_the_location_uncertainty():
    # A town name locates an event to a town, not a point. A big municipality
    # honestly carries kilometres of uncertainty, and the corroboration radius
    # grows with it rather than being a constant.
    assert _uncertainty_m(12.0) > _uncertainty_m(1.0)
    assert _uncertainty_m(None) == 3000.0
    assert _uncertainty_m("not a number") == 3000.0
    assert _uncertainty_m(-5) == 3000.0


def test_locate_returns_nothing_for_an_empty_location():
    assert locate(None) is None
    assert locate("   ") is None


# --- signalling ------------------------------------------------------------

def test_a_text_signal_carries_no_rarity():
    # Nobody has a baseline for "how often does someone say there is a fire
    # here". A number here would let a rumour outrank a measurement wherever
    # the two are sorted together.
    located, _ = reports_from_candidates([candidate()], locator=stub_locator)
    signal = signal_from(located[0], {"kind": "independent_reports"})

    assert signal.rarity is None
    assert signal.hazard == "fire"
    assert signal.location.method == "text_report_gazetteer"


def test_an_official_report_signals_more_confidently_than_a_promoted_rumour():
    official, _ = reports_from_candidates(
        [candidate(tier="authority")], locator=stub_locator
    )
    unofficial, _ = reports_from_candidates([candidate()], locator=stub_locator)

    assert signal_from(official[0], {}).confidence == 1.0
    assert signal_from(unofficial[0], {}).confidence == 0.7


def test_the_basis_for_promotion_travels_with_the_signal():
    # An operator looking at the incident can see it began as a rumour and
    # what agreed with it.
    located, _ = reports_from_candidates([candidate()], locator=stub_locator)
    basis = {"kind": "structured_evidence", "incident_id": "INC-1"}

    evidence = signal_from(located[0], basis).evidence["text_report"]
    assert evidence["basis"] == basis
    assert evidence["tier"] == "unofficial"


def test_a_report_outside_the_service_area_produces_no_signal():
    # Cairo. Placeable, and not ours.
    report = Report(
        candidate_id=1, observation_id=1, source_id="rss:x", tier="media",
        hazard="fire", observed_at=AT, text="fire", origin_key="x",
        latitude=30.04, longitude=31.23, precision_m=1000.0,
    )

    assert signal_from(report, {}) is None


# --- storing ---------------------------------------------------------------

def test_a_weak_event_round_trips_and_resolves(database):
    weak_id = None
    try:
        weak_id = weak_store.save_weak_event({
            "hazard": "fire",
            "reports": [Report(
                candidate_id=1, observation_id=1,
                source_id="telegram:-1001411503185", tier="unofficial",
                hazard="fire", observed_at=AT, text="שריפה", origin_key="k",
                latitude=HAIFA[0], longitude=HAIFA[1], precision_m=2000.0,
            )],
            "latitude": HAIFA[0], "longitude": HAIFA[1], "precision_m": 2000.0,
            "location_text": "חיפה",
            "first_seen_at": AT, "last_seen_at": AT,
            "expires_at": AT + timedelta(hours=3),
        }, at=AT)

        assert weak_id.startswith("WEAK-20260921-")
        stored = {row["id"]: row for row in weak_store.open_weak_events("fire")}
        assert weak_id in stored
        # The report travels with it, so the card can name who said it.
        assert stored[weak_id]["reports"][0]["source_id"] == "telegram:-1001411503185"

        weak_store.resolve_weak_event(
            weak_id, status="promoted", resolution="independent_reports",
            incident_id="INC-20260921-0001",
        )
        assert weak_id not in {row["id"] for row in weak_store.open_weak_events()}
    finally:
        if weak_id:
            with database.connect() as connection:
                connection.execute(
                    text("DELETE FROM weak_events WHERE id = :id"), {"id": weak_id}
                )
                connection.commit()


def test_expiry_marks_unconfirmed_and_keeps_the_row(database):
    # Not deleted. A channel whose reports are never corroborated is one to
    # drop, and that is measurable only if the misses are still here to count.
    weak_id = None
    try:
        weak_id = weak_store.save_weak_event({
            "hazard": "flood", "reports": [],
            "latitude": HAIFA[0], "longitude": HAIFA[1], "precision_m": 2000.0,
            "location_text": "חיפה",
            "first_seen_at": AT, "last_seen_at": AT,
            "expires_at": AT + timedelta(hours=3),
        }, at=AT)

        assert weak_store.expire_weak_events([weak_id]) == 1

        with database.connect() as connection:
            row = connection.execute(
                text("SELECT status, resolution FROM weak_events WHERE id = :id"),
                {"id": weak_id},
            ).mappings().one()
        assert row["status"] == "unconfirmed"
        assert row["resolution"] == "expired_without_corroboration"
    finally:
        if weak_id:
            with database.connect() as connection:
                connection.execute(
                    text("DELETE FROM weak_events WHERE id = :id"), {"id": weak_id}
                )
                connection.commit()
