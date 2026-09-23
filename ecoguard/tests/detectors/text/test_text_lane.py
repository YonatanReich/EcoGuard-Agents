"""The lane between triage and the coordinator: placing, signalling, storing."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from ecoguard.database.repositories import weak_events as weak_store
from ecoguard.database.repositories.observations import upsert_observations
from ecoguard.database.repositories.text_candidates import store_candidates
from ecoguard.detectors.text import run as text_run
from ecoguard.detectors.text import classifier as text_classifier
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


def test_confidence_follows_corroboration_not_the_source_tier():
    """What used to key off `tier`. An 'authority' badge now buys nothing.

    A corroborated report carries 0.7 and an uncorroborated one 0.3 — the
    lowest confidence in the system, which is what an unconfirmed claim is
    worth — regardless of who posted it.
    """
    authority, _ = reports_from_candidates(
        [candidate(tier="authority")], locator=stub_locator
    )
    unofficial, _ = reports_from_candidates([candidate()], locator=stub_locator)

    for located in (authority, unofficial):
        assert signal_from(located[0], {}, corroborated=True).confidence == 0.7
        assert signal_from(located[0], {}, corroborated=False).confidence == 0.3


def test_the_signal_says_whether_anything_corroborated_it():
    located, _ = reports_from_candidates([candidate()], locator=stub_locator)

    corroborated = signal_from(located[0], {}, corroborated=True)
    bare = signal_from(located[0], {}, corroborated=False)

    assert corroborated.evidence["text_report"]["corroborated"] is True
    assert bare.evidence["text_report"]["corroborated"] is False


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


# --- runtime lifecycle -----------------------------------------------------

def _runtime_candidate(identifier, *, tier, triaged_at=None, source_id=None):
    return candidate(
        id=identifier,
        observation_id=identifier + 1000,
        source_id=source_id or f"telegram:-100{identifier}",
        tier=tier,
        triaged_at=triaged_at,
    )


def _runtime_report(item):
    return Report(
        candidate_id=item["id"], observation_id=item["observation_id"],
        source_id=item["source_id"], tier=item["tier"], hazard=item["hazard"],
        observed_at=item["observed_at"], text=item["claim"],
        origin_key=f"candidate:{item['id']}", latitude=HAIFA[0],
        longitude=HAIFA[1], precision_m=2000.0,
        location_text=item["location_text"], claim=item["claim"],
    )


def _wire_runtime(monkeypatch, candidates):
    from ecoguard.coordinator import incidents

    monkeypatch.setattr(
        text_run, "recent_candidates",
        lambda hazard, **_: candidates if hazard == "fire" else [],
    )
    monkeypatch.setattr(
        text_run, "reports_from_candidates",
        lambda rows: ([_runtime_report(row) for row in rows], []),
    )
    monkeypatch.setattr(incidents, "open_incidents", lambda: [])


def test_repeated_triage_does_not_send_a_candidate_twice(monkeypatch):
    item = _runtime_candidate(1, tier="media", source_id="https://ynet.test/rss")
    candidates = [item]
    coordinated = []

    _wire_runtime(monkeypatch, candidates)

    def mark(ids, *, at=None):
        for row in candidates:
            if row["id"] in set(ids):
                row["triaged_at"] = at
        return len(ids)

    monkeypatch.setattr(text_run, "mark_candidates_triaged", mark)

    text_run.run_text_triage(at=AT, coordinate=lambda signals: coordinated.append(signals))
    text_run.run_text_triage(at=AT, coordinate=lambda signals: coordinated.append(signals))

    assert len(coordinated) == 1
    assert [signal.source for signal in coordinated[0]] == ["https://ynet.test/rss"]
    assert item["triaged_at"] == AT


def test_an_uncorroborated_report_still_reaches_the_coordinator(monkeypatch):
    """The whole point of the change: it is passed on, not parked.

    Under the old model a lone report became a weak event and expired three
    hours later without an operator ever seeing it. It now leaves on the same
    tick, labelled, so the advisory planner can say who to phone.
    """
    item = _runtime_candidate(1, tier="unofficial")
    candidates = [item]
    coordinated = []

    _wire_runtime(monkeypatch, candidates)
    monkeypatch.setattr(text_run, "mark_candidates_triaged", lambda ids, **_: len(ids))

    outcome = text_run.run_text_triage(
        at=AT, coordinate=lambda signals: coordinated.append(signals)
    )

    assert outcome["uncorroborated"] == 1
    assert outcome["events"] == 0
    assert len(coordinated) == 1
    signal = coordinated[0][0]
    assert signal.evidence["text_report"]["corroborated"] is False
    assert signal.confidence == 0.3


def test_db_backed_telegram_and_y_net_pipeline_hands_off_only_once(database):
    source_ids = {
        "telegram": "telegram:-1001411503185",
        "rss": "https://www.ynet.co.il/Integration/StoryRss1854.xml",
    }
    cell_ids = {
        "telegram": "telegram-text-runtime-integration",
        "rss": "rss-text-runtime-integration",
    }
    observation_ids = []

    class ControlledClassifier:
        """Two witnesses, two wordings.

        The claims must differ: identical text from two channels is one claim
        retyped, and triage collapses it on purpose. Two people describing one
        fire in their own words is the case that should corroborate.
        """

        def classify(self, messages):
            return [{
                "observation_id": item["observation_id"],
                "source_id": item["source_id"],
                "observed_at": item["observed_at"],
                "hazards": ["fire"],
                "relevant": True,
                "literal": True,
                "in_israel": True,
                "update_type": "new",
                "location_text": "חיפה",
                "claim": (
                    "שריפה דווחה בחיפה"
                    if str(item["source_id"]).startswith("telegram:")
                    else "עשן כבד נראה מעל חיפה, כוחות כיבוי הוזעקו למקום"
                ),
                "details": {},
                "classified_by": "model",
                "model_version": "controlled-test",
                "keyword_hazards": ["fire"],
            } for item in messages]

    try:
        for kind in ("telegram", "rss"):
            payload = {
                "source_id": source_ids[kind],
                "raw_text": "שריפה דווחה בחיפה",
                "handle": kind,
                "display_name": kind,
            }
            if kind == "telegram":
                payload.update({"peer_id": -1001411503185, "message_id": 900001})
            else:
                payload["item_guid"] = "text-runtime-integration"
            upsert_observations(kind, [{
                "cell_id": cell_ids[kind], "observed_at": AT, "payload": payload,
            }])

        with database.connect() as connection:
            observation_ids = list(connection.execute(
                text(
                    "SELECT id FROM observations "
                    "WHERE cell_id IN (:telegram, :rss) ORDER BY id"
                ),
                cell_ids,
            ).scalars())
        assert len(observation_ids) == 2

        classified = text_classifier.classify_new_text(
            since=datetime.now(timezone.utc) - timedelta(minutes=5),
            classifier=ControlledClassifier(),
        )
        assert classified["messages"] == 2
        assert classified["candidates"] == 2

        coordinator_calls = []
        first = text_run.run_text_triage(
            at=AT, coordinate=lambda signals: coordinator_calls.append(list(signals))
        )
        second = text_run.run_text_triage(
            at=AT, coordinate=lambda signals: coordinator_calls.append(list(signals))
        )

        # Two distinct origins describing the same fire in the same place
        # corroborate each other. That used to depend on one of them being a
        # "media" source; it now depends only on them being independent.
        assert first["events"] == 2
        assert first["uncorroborated"] == 0
        assert second["events"] == 0
        assert second["uncorroborated"] == 0
        assert len(coordinator_calls) == 1
        assert {signal.source for signal in coordinator_calls[0]} == set(source_ids.values())
        telegram_signal = next(
            signal for signal in coordinator_calls[0]
            if signal.source == source_ids["telegram"]
        )
        assert telegram_signal.evidence["text_report"]["basis"]["kind"] == (
            "independent_reports"
        )
        assert telegram_signal.evidence["text_report"]["corroborated"] is True

        with database.connect() as connection:
            markers = connection.execute(
                text(
                    "SELECT triaged_at FROM text_candidates "
                    "WHERE observation_id = ANY(:ids)"
                ),
                {"ids": observation_ids},
            ).scalars().all()
        assert len(markers) == 2
        assert all(marker is not None for marker in markers)
    finally:
        if observation_ids:
            with database.connect() as connection:
                connection.execute(
                    text("DELETE FROM text_candidates WHERE observation_id = ANY(:ids)"),
                    {"ids": observation_ids},
                )
                connection.execute(
                    text("DELETE FROM observations WHERE id = ANY(:ids)"),
                    {"ids": observation_ids},
                )
                connection.commit()
