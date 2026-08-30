from datetime import datetime, timezone
from types import SimpleNamespace

from scripts.build_historical_telegram_wildfire_pilot import CuratedLocation, normalize_message


def test_normalization_preserves_provenance_and_existing_tier_rules():
    message = SimpleNamespace(id=362, date=datetime(2025, 8, 24, 11, 28, tzinfo=timezone.utc), raw_text="שריפת חורש סמוך למבשרת ציון")
    firms = [{"candidate_id": "candidate-1", "_start": datetime(2025, 8, 24, 11, 30, tzinfo=timezone.utc), "_end": datetime(2025, 8, 24, 12, 0, tzinfo=timezone.utc), "_latitude": 31.806, "_longitude": 35.153}]
    geocoder = lambda _: {"status": "resolved", "latitude": 31.8057, "longitude": 35.1527}

    row = normalize_message(message, CuratedLocation("חורש סמוך למבשרת ציון", "מבשרת ציון"), firms, geocoder=geocoder)

    assert row["message_id"] == 362
    assert row["raw_message_text"] == message.raw_text
    assert row["firms_candidate_id"] == "candidate-1"
    assert row["label_confidence_tier"] == "multi_source_probable_fire"


def test_unresolved_location_is_rejected_without_coordinates():
    message = SimpleNamespace(id=1, date=datetime(2026, 1, 1, tzinfo=timezone.utc), raw_text="שריפה בשטח פתוח")
    result = normalize_message(message, CuratedLocation("מקום לא ברור", "מקום לא ברור"), [], geocoder=lambda _: {"status": "not_found", "latitude": None, "longitude": None})
    assert result is None
