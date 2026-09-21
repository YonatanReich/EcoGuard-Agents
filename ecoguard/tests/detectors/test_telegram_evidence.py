from datetime import datetime, timedelta, timezone

from ecoguard.database.repositories.towns import (
    NamedTownLookupResult,
    NamedTownMatch,
    TownLookupStatus,
)
from ecoguard.detectors.telegram import evidence as telegram_evidence
from ecoguard.shared.cells import cell_by_id, cell_for, neighbours, service_area_cells
from ecoguard.shared.signals import AIR_POLLUTION, FIRE, FLOOD, HIGH, CellSignal


WHEN = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
LATITUDE = 32.794
LONGITUDE = 34.9896
CELL = cell_for(LATITUDE, LONGITUDE)
assert CELL is not None


def _signal(*, hazard=FIRE, source=None, severity=None):
    return CellSignal(
        cell_id=CELL,
        observed_at=WHEN,
        hazard=hazard,
        variable="frp" if hazard == FIRE else "discharge",
        value=20.0,
        unit="MW" if hazard == FIRE else "m3/s",
        source=source or (
            "firms" if hazard == FIRE else "water_authority_hydrometric_observations"
        ),
        rarity=1.0 if hazard == FIRE else None,
        direction=HIGH,
        confidence=0.8,
        severity=severity,
        evidence={"structured": True},
    )


def _row(text, *, at=WHEN, message_id=1, username="Israel_Police_100", peer=-1002843129862,
         forwarded=None):
    return {
        "id": message_id,
        "source": "telegram",
        "cell_id": f"telegram:{peer}:{message_id}",
        "observed_at": at,
        "payload": {
            "peer_id": peer,
            "configured_username": username,
            "channel_username": username,
            "channel_title": username,
            "message_id": message_id,
            "posted_at": at.isoformat(),
            "edited_at": None,
            "raw_text": text,
            "source_url": f"https://t.me/{username}/{message_id}",
            "forwarded_provenance": forwarded,
        },
    }


def _reader(rows):
    return lambda **_: rows


def _install_location(monkeypatch):
    monkeypatch.setattr(
        telegram_evidence,
        "extract_location",
        lambda text, event_type: {
            "location_text": "חיפה",
            "city": "חיפה",
            "street": None,
            "neighborhood": None,
            "confidence": 0.85,
        },
    )


def _geocoder(_):
    return {
        "status": "resolved",
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "confidence": 0.70,
        "precision": "city",
    }


def _enrich(signals, rows):
    return telegram_evidence.enrich_signals_with_telegram(
        signals,
        observation_reader=_reader(rows),
        geocoder=_geocoder,
        town_resolver=lambda **_: NamedTownLookupResult(
            status=TownLookupStatus.SUCCESS_EMPTY
        ),
        clock=lambda: WHEN + timedelta(minutes=1),
    )


def _town_resolver(
    name="מבשרת ציון", *, distance_m=0.0, contains_signal=True,
    outline_source="fabric/admin8",
):
    def resolve(**_):
        return NamedTownLookupResult(
            status=TownLookupStatus.SUCCESS_WITH_RESULTS,
            match=NamedTownMatch(
                town_id="mevaseret-zion" if name == "מבשרת ציון" else "haifa",
                name_he=name,
                name_en="Mevaseret Zion" if name == "מבשרת ציון" else "Haifa",
                place="town",
                cbs_code="1015" if name == "מבשרת ציון" else "4000",
                outline_source=outline_source,
                authority=name,
                authority_type="מועצה מקומית",
                distance_m=distance_m,
                contains_signal=contains_signal,
            ),
        )
    return resolve


def _empty_town_resolver(**_):
    return NamedTownLookupResult(status=TownLookupStatus.SUCCESS_EMPTY)


def _unresolved_geocoder(_):
    return {
        "status": "unresolved",
        "latitude": None,
        "longitude": None,
        "confidence": 0.0,
        "precision": None,
    }


def _results(signal):
    return signal.evidence["telegram_evidence"]["results"]


def test_no_structured_signals_means_no_output_and_no_read():
    called = False

    def reader(**_):
        nonlocal called
        called = True
        return []

    assert telegram_evidence.enrich_signals_with_telegram(
        [], observation_reader=reader
    ) == []
    assert called is False


def test_support_preserves_every_structured_field(monkeypatch):
    monkeypatch.setenv("TELEGRAM_PEER_ID_ISRAEL_POLICE_100", "-1002843129862")
    _install_location(monkeypatch)
    original = _signal(severity=0.4)
    enriched = _enrich([original], [_row("שריפה בחיפה")])[0]

    assert len(_enrich([original], [])) == 1
    for field in (
        "cell_id", "observed_at", "hazard", "variable", "value", "unit",
        "source", "rarity", "direction", "baseline", "location", "confidence",
        "severity",
    ):
        assert getattr(enriched, field) == getattr(original, field)
    result = _results(enriched)[0]
    assert result["status"] == "SUPPORTING"
    assert result["location_precision"] == "city"
    assert "locality_centroid_is_not_an_exact_incident_location" in result["limitations"]
    assert result["source_verification"]["event_verified"] is False


def test_fire_report_cannot_support_flood(monkeypatch):
    monkeypatch.setenv("TELEGRAM_PEER_ID_ISRAEL_POLICE_100", "-1002843129862")
    _install_location(monkeypatch)
    result = _results(_enrich([_signal(hazard=FLOOD)], [_row("שריפה בחיפה")])[0])[0]
    assert result["status"] == "UNMATCHED"
    assert result["candidate_event_type"] == "fire"
    assert "event_type" in result["failed_rules"]


def test_flood_report_cannot_support_fire(monkeypatch):
    monkeypatch.setenv("TELEGRAM_PEER_ID_ISRAEL_POLICE_100", "-1002843129862")
    _install_location(monkeypatch)
    result = _results(_enrich([_signal()], [_row("הצפה חמורה בחיפה")])[0])[0]
    assert result["status"] == "UNMATCHED"
    assert result["candidate_event_type"] == "flood"


def test_forecast_only_flood_warning_cannot_become_supporting_evidence(monkeypatch):
    monkeypatch.setenv(
        "TELEGRAM_PEER_ID_ISRAEL_POLICE_100", "-1002843129862"
    )
    signal = _enrich(
        [_signal(hazard=FLOOD)],
        [_row("חשש לשיטפונות באזור חיפה")],
    )[0]

    assert signal.evidence["telegram_evidence"]["supporting_count"] == 0
    assert _results(signal) == []


def test_air_pollution_bypasses_enrichment_unchanged():
    pollution = _signal(
        hazard=AIR_POLLUTION,
        source="air_pollution",
    )

    def forbidden_reader(**_):
        raise AssertionError("Air Pollution must not query Telegram")

    output = telegram_evidence.enrich_signals_with_telegram(
        [pollution], observation_reader=forbidden_reader
    )
    assert output == [pollution]
    assert output[0] is pollution


def test_unmatched_evidence_never_blocks_structured_signal(monkeypatch):
    monkeypatch.setenv("TELEGRAM_PEER_ID_ISRAEL_POLICE_100", "-1002843129862")
    _install_location(monkeypatch)
    original = _signal()
    output = _enrich(
        [original],
        [_row("שריפה בחיפה", at=WHEN + timedelta(hours=3, seconds=1))],
    )
    assert len(output) == 1
    assert _results(output[0])[0]["status"] == "UNMATCHED"
    assert output[0].hazard == FIRE


def test_failure_forwards_original_objects_unchanged():
    fire = _signal()
    flood = _signal(hazard=FLOOD)

    def failed_reader(**_):
        raise RuntimeError("database unavailable")

    output = telegram_evidence.enrich_signals_with_telegram(
        [fire, flood], observation_reader=failed_reader
    )
    assert output == [fire, flood]
    assert output[0] is fire
    assert output[1] is flood


def test_multiple_inputs_preserve_cardinality_and_never_emit_conflicting(monkeypatch):
    monkeypatch.setenv("TELEGRAM_PEER_ID_ISRAEL_POLICE_100", "-1002843129862")
    _install_location(monkeypatch)
    fire = _signal(severity=0.7)
    flood = _signal(hazard=FLOOD, severity=0.2)

    output = _enrich([fire, flood], [_row("שריפה בחיפה")])

    assert len(output) == 2
    assert output[0].severity == fire.severity
    assert output[1].severity == flood.severity
    assert all(
        result["status"] in {"SUPPORTING", "UNMATCHED"}
        for signal in output
        for result in _results(signal)
    )


def test_fire_from_a_non_structured_source_bypasses_telegram_unchanged():
    signal = _signal(source="telegram")

    def forbidden_reader(**_):
        raise AssertionError("non-structured Fire signals must not query Telegram")

    output = telegram_evidence.enrich_signals_with_telegram(
        [signal], observation_reader=forbidden_reader
    )

    assert output == [signal]
    assert output[0] is signal


def test_fire_temporal_boundary_is_inclusive(monkeypatch):
    monkeypatch.setenv("TELEGRAM_PEER_ID_ISRAEL_POLICE_100", "-1002843129862")
    _install_location(monkeypatch)
    rows = [
        _row("שריפה בחיפה", at=WHEN + timedelta(hours=3), message_id=1),
        _row("שריפה בחיפה סמוך", at=WHEN + timedelta(hours=3, seconds=1), message_id=2),
    ]
    results = _results(_enrich([_signal()], rows)[0])
    assert [result["status"] for result in results] == ["SUPPORTING", "UNMATCHED"]


def test_adjacent_cell_supports_but_distant_cell_does_not(monkeypatch):
    monkeypatch.setenv("TELEGRAM_PEER_ID_ISRAEL_POLICE_100", "-1002843129862")
    _install_location(monkeypatch)
    adjacent_id = neighbours(CELL)[0]
    adjacent = cell_by_id(adjacent_id)
    far = max(
        service_area_cells(),
        key=lambda item: abs(item.latitude - LATITUDE) + abs(item.longitude - LONGITUDE),
    )

    def geocoder_at(latitude, longitude):
        return lambda _: {
            "status": "resolved", "latitude": latitude, "longitude": longitude,
            "confidence": 0.70, "precision": "city",
        }

    adjacent_result = telegram_evidence.enrich_signals_with_telegram(
        [_signal()],
        observation_reader=_reader([_row("שריפה בחיפה")]),
        geocoder=geocoder_at(adjacent.latitude, adjacent.longitude),
        town_resolver=_empty_town_resolver,
        clock=lambda: WHEN,
    )
    distant_result = telegram_evidence.enrich_signals_with_telegram(
        [_signal()],
        observation_reader=_reader([_row("שריפה בחיפה")]),
        geocoder=geocoder_at(far.latitude, far.longitude),
        town_resolver=_empty_town_resolver,
        clock=lambda: WHEN,
    )
    assert _results(adjacent_result[0])[0]["cell_relation"] == "adjacent_cell"
    assert _results(adjacent_result[0])[0]["status"] == "SUPPORTING"
    assert _results(distant_result[0])[0]["cell_relation"] == "distant"
    assert _results(distant_result[0])[0]["status"] == "UNMATCHED"


def test_flood_has_its_own_configurable_boundary(monkeypatch):
    monkeypatch.setenv("TELEGRAM_PEER_ID_ISRAEL_POLICE_100", "-1002843129862")
    monkeypatch.setenv("TELEGRAM_FLOOD_CORROBORATION_WINDOW_MINUTES", "45")
    _install_location(monkeypatch)
    rows = [
        _row("הצפה בחיפה", at=WHEN + timedelta(minutes=45), message_id=1),
        _row("הצפות בחיפה", at=WHEN + timedelta(minutes=45, seconds=1), message_id=2),
    ]
    results = _results(_enrich([_signal(hazard=FLOOD)], rows)[0])
    assert [result["status"] for result in results] == ["SUPPORTING", "UNMATCHED"]


def test_wrong_peer_channel_cannot_support(monkeypatch):
    monkeypatch.delenv("TELEGRAM_PEER_ID_ISRAEL_POLICE_100", raising=False)
    _install_location(monkeypatch)
    result = _results(
        _enrich([_signal()], [_row("שריפה בחיפה", peer=-100999)])[0]
    )[0]
    assert result["status"] == "UNMATCHED"
    assert "source_policy" in result["failed_rules"]
    assert "channel_peer_id_did_not_match_pin" in result["limitations"]


def test_unofficial_aggregator_is_never_labelled_authoritative(monkeypatch):
    monkeypatch.setenv("TELEGRAM_PEER_ID_FIREISRAEL7777", "-1001411503185")
    _install_location(monkeypatch)
    row = _row(
        "שריפה בחיפה", username="fireisrael7777", peer=-1001411503185
    )
    result = _results(_enrich([_signal()], [row])[0])[0]
    assert result["status"] == "SUPPORTING"
    assert result["source_verification"]["tier"] == "unofficial_aggregator"
    assert result["source_verification"]["event_verified"] is False
    assert "unofficial_aggregator_is_not_authoritative" in result["limitations"]


def test_duplicate_or_forwarded_copy_does_not_multiply_support(monkeypatch):
    monkeypatch.setenv("TELEGRAM_PEER_ID_ISRAEL_POLICE_100", "-1002843129862")
    _install_location(monkeypatch)
    forwarded = {"origin_peer_id": 88, "origin_message_id": 9}
    rows = [
        _row("שריפה בחיפה", message_id=1, forwarded=forwarded),
        _row("שריפה בחיפה", message_id=2, forwarded=forwarded),
    ]
    enriched = _enrich([_signal()], rows)[0]
    results = _results(enriched)
    assert [result["status"] for result in results] == ["SUPPORTING", "UNMATCHED"]
    assert enriched.evidence["telegram_evidence"]["supporting_count"] == 1
    assert "independent_message" in results[1]["failed_rules"]


def test_shared_town_supports_fire_inside_named_locality(monkeypatch):
    monkeypatch.setenv("TELEGRAM_PEER_ID_ISRAEL_POLICE_100", "-1002843129862")
    output = telegram_evidence.enrich_signals_with_telegram(
        [_signal()],
        observation_reader=_reader([_row("שריפת חורש סמוך למבשרת ציון")]),
        town_resolver=_town_resolver(),
        geocoder=lambda _: (_ for _ in ()).throw(AssertionError("fallback not expected")),
        clock=lambda: WHEN,
    )

    result = _results(output[0])[0]
    assert result["status"] == "SUPPORTING"
    assert result["cell_relation"] == "inside_locality"
    assert result["location_precision"] == "locality"
    assert result["extracted_location"]["city"] == "מבשרת ציון"
    assert result["extracted_location"]["latitude"] is None
    assert result["extracted_location"]["longitude"] is None
    assert result["extracted_location"]["resolver"] == "shared_postgis_towns"
    assert "town_outline_is_not_an_exact_incident_location" in result["limitations"]


def test_shared_town_does_not_support_fire_in_distant_locality(monkeypatch):
    monkeypatch.setenv("TELEGRAM_PEER_ID_ISRAEL_POLICE_100", "-1002843129862")
    output = telegram_evidence.enrich_signals_with_telegram(
        [_signal()],
        observation_reader=_reader([_row("שריפת חורש סמוך למבשרת ציון")]),
        town_resolver=_town_resolver(distance_m=40_000.0, contains_signal=False),
        geocoder=lambda _: (_ for _ in ()).throw(AssertionError("fallback not expected")),
        clock=lambda: WHEN,
    )

    result = _results(output[0])[0]
    assert result["status"] == "UNMATCHED"
    assert result["cell_relation"] == "distant"
    assert "geographic_proximity" in result["failed_rules"]


def test_shared_town_resolves_explicit_flood_locality(monkeypatch):
    monkeypatch.setenv("TELEGRAM_PEER_ID_ISRAEL_POLICE_100", "-1002843129862")
    output = telegram_evidence.enrich_signals_with_telegram(
        [_signal(hazard=FLOOD)],
        observation_reader=_reader([_row("בשל הצפות בחיפה נחסם כביש")]),
        town_resolver=_town_resolver("חיפה", distance_m=2_000.0, contains_signal=False),
        geocoder=lambda _: (_ for _ in ()).throw(AssertionError("fallback not expected")),
        clock=lambda: WHEN,
    )

    result = _results(output[0])[0]
    assert result["status"] == "SUPPORTING"
    assert result["cell_relation"] == "near_locality"
    assert result["location_precision"] == "locality"
    assert result["extracted_location"]["town_id"] == "haifa"


def test_road_landmark_only_flood_remains_safely_unmatched(monkeypatch):
    monkeypatch.setenv("TELEGRAM_PEER_ID_ISRAEL_POLICE_100", "-1002843129862")
    resolver_called = False

    def no_town(**_):
        nonlocal resolver_called
        resolver_called = True
        return NamedTownLookupResult(status=TownLookupStatus.SUCCESS_EMPTY)

    output = telegram_evidence.enrich_signals_with_telegram(
        [_signal(hazard=FLOOD)],
        observation_reader=_reader([_row(
            "בשל הצפות נחסם כביש 90 בין נחל דרגות למלונות ים המלח"
        )]),
        town_resolver=no_town,
        geocoder=_unresolved_geocoder,
        clock=lambda: WHEN,
    )

    result = _results(output[0])[0]
    assert resolver_called is True
    assert result["status"] == "UNMATCHED"
    assert result["cell_relation"] == "unresolved"
    assert result["extracted_location"]["latitude"] is None
    assert result["extracted_location"]["longitude"] is None
