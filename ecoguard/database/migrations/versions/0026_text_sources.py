"""The curated allowlist of text sources, and the tier each one carries.

Revision ID: text_sources
Revises: firms_signatures_merge
Create Date: 2026-09-21

Tier is the one thing about a source that must never be inferred. The largest
Hebrew fire channel on Telegram is titled "כבאות והצלה ארצי" and declares in its
own description that it is *not* the fire authority's channel; any rule reading
the title would promote it to authority on day one. So tier lives here, in a
table an operator edits, and nothing computes it.

`peer_id` comes across from the four channels previously hard-coded in
`collection/shared/telegram/policy.py`. It is not decoration: a username can be
released and re-registered by somebody else, and pinning the numeric id is what
turns that from a silent source swap into a failure. A row with a NULL peer_id
has not been resolved yet and the collector refuses to read it.

`last_message_id` is the backfill cursor. A collector that only ever asks for
the newest 50 messages loses everything published while the process was down;
with the cursor it asks for what it has not seen.
"""

from alembic import op


revision = "text_sources"
down_revision = "firms_signatures_merge"
branch_labels = None
depends_on = None


# Seeded as `unofficial` on purpose, including the three that describe
# themselves as official channels of the police, the traffic division and MDA.
#
# The verification rule is that an authority row needs the channel to be linked
# from the body's own website, or to carry platform verification tied to it.
# Neither could be established on 2026-09-21: gov.il returns 403 to automated
# requests, mdais.org renders client-side, and none of the four shows a
# Telegram verified badge. A self-description is the claim, not the evidence.
#
# Promoting one later is a single UPDATE. Seeding it as authority now would put
# an unverified channel on the path that creates events with no corroboration,
# which is the failure this table exists to prevent.
SEED = (
    (
        "telegram:-1002843129862", "telegram", "Israel_Police_100",
        "דוברות משטרת ישראל", "unofficial", -1002843129862,
        "{fire,flood,earthquake,air_quality}",
        "t.me preview 2026-09-21: self-describes as the official police "
        "spokesperson channel, 9209 subscribers, no platform badge; gov.il "
        "link not checkable (403). Promote to authority once confirmed there.",
    ),
    (
        "telegram:-1001581748447", "telegram", "Atanpolice",
        "אגף התנועה משטרת ישראל", "unofficial", -1001581748447,
        "{flood}",
        "t.me preview 2026-09-21: traffic division reports and enforcement, "
        "16016 subscribers, no platform badge; gov.il link not checkable (403).",
    ),
    (
        "telegram:-1001177174722", "telegram", "mdaisrael",
        "מגן דוד אדום", "unofficial", -1001177174722,
        "{fire,flood,earthquake,air_quality}",
        "t.me preview 2026-09-21: self-describes as the official MDA channel, "
        "7917 subscribers, no platform badge; mdais.org renders client-side "
        "and could not be read.",
    ),
    (
        "telegram:-1001411503185", "telegram", "fireisrael7777",
        "כבאות והצלה ארצי", "unofficial", -1001411503185,
        "{fire}",
        "t.me preview 2026-09-21: 26046 subscribers, description states the "
        "channel is NOT official and directs verification to the spokespeople. "
        "Definitively unofficial — this is not pending confirmation. Note "
        "@fireisrael777 (three 7s) is a 489-subscriber clone with the same "
        "title and disclaimer; do not collect it by mistake.",
    ),
    # Feeds fetched and parsed on 2026-09-21; each returned RSS 2.0 with items
    # dated that day or the one before.
    (
        "https://www.ynet.co.il/Integration/StoryRss1854.xml", "rss", "ynet",
        "ynet — מבזקים", "media", None, "{fire,flood,earthquake,air_quality}",
        "fetched 2026-09-21, valid RSS 2.0, breaking-news feed",
    ),
    (
        "https://rss.walla.co.il/feed/1?type=main", "rss", "walla",
        "Walla — חדשות", "media", None, "{fire,flood,earthquake,air_quality}",
        "fetched 2026-09-21, valid RSS 2.0, main news feed",
    ),
    (
        "https://www.maariv.co.il/Rss/RssFeedsMivzakiChadashot", "rss", "maariv",
        "מעריב — מבזקי חדשות", "media", None, "{fire,flood,earthquake,air_quality}",
        "fetched 2026-09-21, valid RSS 2.0, breaking-news feed",
    ),
    (
        "https://www.haaretz.co.il/srv/rss---feedly", "rss", "haaretz",
        "הארץ", "media", None, "{fire,flood,earthquake,air_quality}",
        "fetched 2026-09-21, valid RSS 2.0",
    ),
    (
        "https://www.timesofisrael.com/feed/", "rss", "timesofisrael",
        "The Times of Israel", "media", None, "{fire,flood,earthquake,air_quality}",
        "fetched 2026-09-21, valid RSS 2.0, English",
    ),
    (
        "https://www.jpost.com/rss/rssfeedsisraelnews.aspx", "rss", "jpost",
        "The Jerusalem Post — Israel News", "media", None,
        "{fire,flood,earthquake,air_quality}",
        "fetched 2026-09-21, valid RSS 2.0, English",
    ),
)

# Seeded inactive rather than left out, so the row carries why it is not being
# polled instead of the knowledge living in somebody's head.
INACTIVE_SEED = (
    (
        "https://www.israelhayom.co.il/rss.xml", "rss", "israelhayom",
        "ישראל היום", "media", None, "{fire,flood,earthquake,air_quality}",
        "fetched 2026-09-21: valid RSS but a mixed everything-feed — the first "
        "items were daily horoscopes. Activate once a breaking-news feed URL "
        "is found on the outlet's RSS page.",
    ),
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE text_sources (
          source_id        text PRIMARY KEY,
          kind             text NOT NULL,
          handle           text NOT NULL,
          display_name     text,
          tier             text NOT NULL,
          hazards          text[] NOT NULL DEFAULT '{}',
          peer_id          bigint,
          last_message_id  bigint,
          last_polled_at   timestamptz,
          -- Returned by the feed and echoed back on the next poll. A
          -- breaking-news feed polled every few minutes is unchanged on most
          -- of those polls, and a 304 costs one round trip and no parsing.
          etag             text,
          last_modified    text,
          verified_by      text,
          verified_at      date,
          active           boolean NOT NULL DEFAULT true,
          CONSTRAINT text_sources_kind
            CHECK (kind IN ('telegram', 'rss')),
          CONSTRAINT text_sources_tier
            CHECK (tier IN ('authority', 'media', 'unofficial')),
          -- A Telegram row without a resolved peer id is an unpinned source,
          -- and an unpinned source is one a username transfer can silently
          -- replace. The collector will not read it; the constraint says so
          -- rather than leaving it to the collector to remember.
          CONSTRAINT text_sources_telegram_needs_peer
            CHECK (kind <> 'telegram' OR peer_id IS NOT NULL)
        )
        """
    )
    op.execute(
        "CREATE INDEX text_sources_active_kind ON text_sources (kind) "
        "WHERE active"
    )

    for row in (*SEED, *INACTIVE_SEED):
        source_id, kind, handle, display_name, tier, peer_id, hazards, why = row
        op.execute(
            f"""
            INSERT INTO text_sources (
              source_id, kind, handle, display_name, tier, hazards,
              peer_id, verified_by, verified_at, active
            ) VALUES (
              {_q(source_id)}, {_q(kind)}, {_q(handle)}, {_q(display_name)},
              {_q(tier)}, {_q(hazards)}::text[],
              {'NULL' if peer_id is None else peer_id},
              {_q(why)}, DATE '2026-09-21',
              {'true' if row in SEED else 'false'}
            )
            """
        )


def _q(value: str | None) -> str:
    """A single-quoted SQL literal. Seed data only — never user input."""
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def downgrade() -> None:
    op.execute("DROP TABLE text_sources")
