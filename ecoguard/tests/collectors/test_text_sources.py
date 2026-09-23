"""The allowlist, the feed parser, and the two things they must never do.

Tier must come from the table and nowhere else, and an edited message must
replace the text it revises rather than being discarded as a duplicate. Both
are properties an ordinary "does it collect?" test passes straight over.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from ecoguard.collectors.text.rss import (
    RssCollector,
    parse_items,
    strip_markup,
)
from ecoguard.database.repositories.text_sources import (
    OFFICIAL_TIERS,
    TextSource,
    active_sources,
    tier_for,
)


FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>test</title>
  <item>
    <guid>https://example.test/1</guid>
    <title>&#1513;&#1512;&#1497;&#1508;&#1492; באזור התעשייה</title>
    <description>&lt;img src="x.jpg"/&gt; צוותי כיבוי בדרך למקום</description>
    <link>https://example.test/1</link>
    <pubDate>Mon, 21 Sep 2026 15:35:49 +0300</pubDate>
  </item>
  <item>
    <title>item with no guid and no link</title>
    <pubDate>Mon, 21 Sep 2026 14:00:00 GMT</pubDate>
  </item>
</channel></rss>""".encode("utf-8")


def _source(**overrides) -> TextSource:
    defaults = dict(
        source_id="https://example.test/feed", kind="rss", handle="example",
        display_name="Example", tier="media", hazards=("fire",), peer_id=None,
        last_message_id=None, last_polled_at=None, etag=None, last_modified=None,
    )
    return TextSource(**{**defaults, **overrides})


# --- the feed parser -------------------------------------------------------

def test_items_carry_identity_title_and_an_aware_timestamp():
    items = parse_items(FEED)

    assert items[0]["identity"] == "https://example.test/1"
    assert items[0]["published_at"] == datetime(
        2026, 9, 21, 12, 35, 49, tzinfo=timezone.utc
    )
    # Every downstream consumer compares these against observation times, and
    # a naive datetime would compare wrong rather than fail.
    assert all(item["published_at"].tzinfo is not None for item in items)


def test_an_item_without_a_guid_falls_back_to_its_link_or_title():
    # Identity is what dedup runs on. A feed that omits guid must still produce
    # a stable key, or every poll re-reports the same item as new.
    assert parse_items(FEED)[1]["identity"] == "item with no guid and no link"


def test_markup_is_stripped_from_the_text_the_classifier_reads():
    item = parse_items(FEED)[0]

    assert strip_markup(item["summary"]) == "צוותי כיבוי בדרך למקום"
    # The raw summary is still what came off the wire: collection stores,
    # detection filters.
    assert "<img" in item["summary"]


def test_a_body_that_is_not_a_feed_raises_rather_than_returning_nothing():
    # Both of these would otherwise parse to zero items, which is exactly what
    # a quiet news hour looks like. An outlet serving an error page must not be
    # indistinguishable from an outlet with nothing to report.
    with pytest.raises(ValueError, match="not an RSS feed"):
        parse_items(b"<html>we are down for maintenance</html>")
    with pytest.raises(ValueError, match="well-formed"):
        parse_items(b"<rss><channel><item>truncated mid-resp")


def test_a_genuinely_empty_feed_is_not_an_error():
    # The other side of the boundary: a real feed with no items right now is a
    # quiet feed, not a broken one, and must not raise.
    assert parse_items(
        b'<?xml version="1.0"?><rss version="2.0"><channel>'
        b"<title>quiet</title></channel></rss>"
    ) == []


# --- conditional polling ---------------------------------------------------

def test_a_source_echoes_back_only_the_validators_it_holds():
    assert _source().conditional_headers() == {}
    assert _source(etag='W/"abc"').conditional_headers() == {"If-None-Match": 'W/"abc"'}
    assert _source(
        etag='W/"abc"', last_modified="Mon, 21 Sep 2026 12:00:00 GMT"
    ).conditional_headers() == {
        "If-None-Match": 'W/"abc"',
        "If-Modified-Since": "Mon, 21 Sep 2026 12:00:00 GMT",
    }


# --- the allowlist ---------------------------------------------------------

def test_media_and_authority_are_the_official_path_and_unofficial_is_not():
    assert _source(tier="authority").official
    assert _source(tier="media").official
    assert not _source(tier="unofficial").official
    assert "unofficial" not in OFFICIAL_TIERS


def test_an_unknown_source_has_no_tier_rather_than_the_weakest_one(database):
    # None must never be read as "unofficial". A message from a source nobody
    # curated is a configuration error; admitting it at the lowest tier would
    # quietly let an unvetted channel into the pipeline.
    assert tier_for("telegram:-1009999999999") is None


def test_the_seeded_fire_aggregator_is_unofficial(database):
    # It titles itself "כבאות והצלה ארצי" and its own description says it is
    # not the fire authority's channel. Any tier inferred from the name would
    # get this exactly wrong, which is why the table is the only authority.
    sources = {source.handle: source for source in active_sources("telegram")}

    assert sources["fireisrael7777"].tier == "unofficial"
    assert not sources["fireisrael7777"].official


def test_every_seeded_telegram_source_is_pinned_to_a_peer_id(database):
    # An unpinned channel is one a username transfer can silently replace.
    for source in active_sources("telegram"):
        assert source.peer_id is not None, source.handle


def test_a_telegram_row_without_a_peer_id_is_rejected_by_the_database(database):
    with database.connect() as connection:
        with pytest.raises(Exception) as error:
            connection.execute(text(
                "INSERT INTO text_sources (source_id, kind, handle, tier) "
                "VALUES ('telegram:unpinned', 'telegram', 'unpinned', 'unofficial')"
            ))
        connection.rollback()
    assert "text_sources_telegram_needs_peer" in str(error.value)


def test_an_edited_message_replaces_its_text_instead_of_being_discarded(database):
    # The reason this collector does not use the shared insert-and-ignore
    # writer. An operational channel edits a post as the incident develops,
    # and under insert-and-ignore the system keeps reasoning from the first
    # draft while the channel has already corrected it.
    from ecoguard.database.repositories.observations import (
        upsert_editable_observations,
    )

    at = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)

    def record(message: str):
        return [{
            "cell_id": "telegram:-1001411503185:test",
            "observed_at": at,
            "payload": {"raw_text": message},
        }]

    try:
        assert upsert_editable_observations("telegram_edit_test", record("שריפה")) == 1
        # An unchanged re-read writes nothing, so a collector that re-reads the
        # same window every five minutes does not touch every row each time.
        assert upsert_editable_observations("telegram_edit_test", record("שריפה")) == 0
        assert upsert_editable_observations(
            "telegram_edit_test", record("שריפה, פינוי בתים")
        ) == 1

        with database.connect() as connection:
            stored = connection.execute(text(
                "SELECT payload->>'raw_text' FROM observations "
                "WHERE source = 'telegram_edit_test'"
            )).all()
        assert stored == [("שריפה, פינוי בתים",)]
    finally:
        with database.connect() as connection:
            connection.execute(text(
                "DELETE FROM observations WHERE source = 'telegram_edit_test'"
            ))
            connection.commit()


def test_an_invented_tier_is_rejected_by_the_database(database):
    with database.connect() as connection:
        with pytest.raises(Exception) as error:
            connection.execute(text(
                "INSERT INTO text_sources (source_id, kind, handle, tier) "
                "VALUES ('https://x.test/f', 'rss', 'x', 'semi_official')"
            ))
        connection.rollback()
    assert "text_sources_tier" in str(error.value)
