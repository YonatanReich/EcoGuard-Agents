"""The Telegram collector must stay raw: interpretation belongs to detection."""

import inspect

from ecoguard.collection.shared.telegram import collector as telegram


def test_no_classification_or_location_extraction_at_collection_time():
    """If extraction ran here the original text would be lost and old messages
    could never be re-read against an improved prompt."""
    source = inspect.getsource(telegram)

    assert "detect_fire_candidate" not in source
    assert "extract_fire_location" not in source
    assert "geocode" not in source
