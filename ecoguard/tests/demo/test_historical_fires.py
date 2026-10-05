from datetime import datetime, timedelta, timezone

from ecoguard.api.scenario import SCENARIOS
from ecoguard.demo.scenarios import historical_fires as h

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def test_registered_with_both_fires():
    assert SCENARIOS["historical_fires"] == "ecoguard.demo.scenarios.historical_fires"
    assert [event["id"] for event in h.GROUND_TRUTH] == ["HF1", "HF2"]


def test_nothing_seeded_is_from_after_the_checkpoint():
    """The whole demo rests on this: no evidence the system could not yet have had."""
    rows = h.build_rows(NOW)
    assert {source for source, *_ in rows} == {"firms", "weather", "rss"}
    assert all(observed <= NOW - timedelta(minutes=5) for _, _, observed, _ in rows)


def test_checkpoints_follow_the_first_published_pixel():
    # Carmel: MODIS 10:10 UTC + 106 min lag + one wave. Jerusalem: Meteosat
    # 07:07 UTC + 43 min + one wave.
    assert h.checkpoint("carmel_2010") == datetime(2010, 12, 2, 12, 6, tzinfo=timezone.utc)
    assert h.checkpoint("jerusalem_2025") == datetime(2025, 4, 30, 8, 0, tzinfo=timezone.utc)


def test_an_updated_article_counts_from_when_its_text_was_true():
    """ynet's 10:45 article was rewritten by 15:30; seeding it at 10:45 leaks the evacuations."""
    urls = {payload["source_url"] for source, _, _, payload in h.build_rows(NOW) if source == "rss"}
    assert "https://www.ynet.co.il/news/article/ryw8nnkxeg" not in urls
