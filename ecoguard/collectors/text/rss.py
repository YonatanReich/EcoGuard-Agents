"""News feeds in, raw text observations out. No interpretation here.

Stores the headline and the summary, never the article body: the classifier
only ever sees a headline and a summary anyway, and storing whole articles from
commercial outlets buys nothing and raises a copyright question.

ETag / If-Modified-Since are sent because a breaking-news feed is polled every
few minutes and is unchanged on most of those polls; a 304 costs one round trip
and no parsing.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any
from xml.etree import ElementTree

import requests

from ecoguard.collectors.base import BaseCollector
from ecoguard.database.repositories.text_sources import TextSource, active_sources, record_poll

logger = logging.getLogger(__name__)

SOURCE = "rss"
TIMEOUT_SECONDS = 20.0
MAX_ITEMS_PER_FEED = 100

# A feed that has not been seen before is read once and no further back. The
# archive of a news site is not an incident feed, and classifying a week of
# backlog on first run would spend a lot of tokens to learn about last Tuesday.
FIRST_RUN_ITEM_LIMIT = 20

# ponytail: RSS 2.0 only. Every feed on the allowlist returned RSS 2.0 when it
# was verified; Atom needs namespace handling and nothing needs it yet. A feed
# that parses to zero items logs a warning and is skipped, so an Atom-only feed
# added later is a visible gap rather than a silent one.
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"


# Several feeds put a thumbnail <img> and a wrapping <a> inside <description>.
# ponytail: a tag-stripping regex, not a parser. These are feed summaries, not
# documents; if a feed ever needs real HTML handling, the raw summary is stored
# alongside and can be re-derived.
_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")


def strip_markup(value: str | None) -> str | None:
    """Readable text from a feed summary: tags out, entities resolved."""
    if value is None:
        return None
    text = _SPACES.sub(" ", _TAGS.sub(" ", unescape(value))).strip()
    return text or None


def _text(item: ElementTree.Element, tag: str) -> str | None:
    found = item.find(tag)
    if found is None or found.text is None:
        return None
    stripped = found.text.strip()
    return stripped or None


def _published_at(item: ElementTree.Element) -> datetime | None:
    raw = _text(item, "pubDate")
    if raw is None:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    # RFC 822 permits a floating time. Treating one as UTC is a guess, but the
    # alternative is discarding the item, and every feed checked sends an
    # offset.
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_items(body: bytes) -> list[dict[str, Any]]:
    """Every item in an RSS 2.0 body, newest first as the feed ordered them."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as error:
        raise ValueError(f"feed is not well-formed XML: {error}") from error

    # An outage page is often well-formed XML, and an outage page parses to
    # zero items — which is exactly what a quiet news hour looks like. A feed
    # that is genuinely quiet still has a <channel>; one that has been replaced
    # by something else does not, and that difference is worth an exception
    # rather than a silent empty list.
    if root.find("channel") is None:
        raise ValueError(
            f"not an RSS feed: root element is <{root.tag}> with no <channel>"
        )

    items = []
    for item in root.iterfind(".//item"):
        # guid, then link, then title: the identity has to survive a feed that
        # omits guid, and a headline is the last thing that is stable.
        identity = _text(item, "guid") or _text(item, "link") or _text(item, "title")
        title = _text(item, "title")
        if identity is None or title is None:
            continue
        items.append({
            "identity": identity,
            "title": title,
            "summary": _text(item, "description"),
            "link": _text(item, "link"),
            "published_at": _published_at(item),
        })
    return items[:MAX_ITEMS_PER_FEED]


def _record(source: TextSource, item: dict[str, Any], at: datetime) -> dict[str, Any]:
    published_at = item["published_at"] or at
    summary = strip_markup(item["summary"])
    return {
        # The same shape the Telegram collector uses: a synthetic cell_id that
        # is really a message identity, because these rows describe a text, not
        # a place. Geocoding happens downstream, from what the text says.
        "cell_id": f"rss:{source.handle}:{item['identity']}",
        "observed_at": published_at,
        "payload": {
            "source_id": source.source_id,
            "kind": "rss",
            "handle": source.handle,
            "display_name": source.display_name,
            "item_guid": item["identity"],
            "title": item["title"],
            # The summary is stored exactly as the feed sent it, markup and
            # all, because principle 2 is that collection stores and detection
            # filters. `raw_text` is the filtered view, derived here so every
            # consumer does not re-solve it.
            "summary": item["summary"],
            "raw_text": (
                f"{item['title']}\n{summary}" if summary else item["title"]
            ),
            "source_url": item["link"],
            "posted_at": published_at.isoformat(),
        },
    }


class RssCollector(BaseCollector):
    """Poll every active RSS row on the allowlist. One failure is one feed."""

    source = SOURCE

    def __init__(self, sources: list[TextSource] | None = None) -> None:
        self._sources = sources

    def fetch(self) -> list[dict[str, Any]]:
        feeds = self._sources if self._sources is not None else active_sources("rss")
        at = datetime.now(timezone.utc)
        records: list[dict[str, Any]] = []
        for feed in feeds:
            try:
                records.extend(self._fetch_one(feed, at))
            except Exception:
                # One outlet's outage, TLS expiry or malformed morning must not
                # cost the other seven their poll.
                logger.exception("rss: %s failed; continuing", feed.handle)
        return records

    def _fetch_one(self, feed: TextSource, at: datetime) -> list[dict[str, Any]]:
        response = requests.get(
            feed.source_id,
            timeout=TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT, **feed.conditional_headers()},
        )
        if response.status_code == 304:
            # Unchanged since the last poll. The cursor still moves so
            # last_polled_at reflects that the feed was reached — a feed that
            # is quiet and a feed that is unreachable must not look alike.
            record_poll(
                feed.source_id,
                etag=feed.etag,
                last_modified=feed.last_modified,
                at=at,
            )
            return []
        response.raise_for_status()

        items = parse_items(response.content)
        if not items:
            logger.warning("rss: %s parsed to zero items", feed.handle)
            return []
        if feed.never_polled:
            items = items[:FIRST_RUN_ITEM_LIMIT]

        record_poll(
            feed.source_id,
            etag=response.headers.get("ETag"),
            last_modified=response.headers.get("Last-Modified"),
            at=at,
        )
        return [_record(feed, item, at) for item in items]
