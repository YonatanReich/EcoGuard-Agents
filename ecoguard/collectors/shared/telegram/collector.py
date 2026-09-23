"""Raw Telegram polling for the shared text-event classify-then-triage lane."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from telethon import TelegramClient

from ecoguard.collectors.base import BaseCollector
from ecoguard.database.repositories.observations import upsert_editable_observations
from ecoguard.database.repositories.text_sources import active_sources, record_poll
from ecoguard.collectors.shared.telegram.policy import (
    TelegramChannelPolicy,
    public_message_url,
)
from ecoguard.collectors.shared.telegram.session import get_session_path, load_credentials


MESSAGES_PER_CHANNEL = 50

# How far behind the cursor to start reading, so a post edited after it was
# first stored is seen again. Roughly "the last fifty messages on this channel".
EDIT_RECHECK_MESSAGES = 50


def _forwarded_provenance(message: object) -> dict[str, Any] | None:
    forwarded = getattr(message, "fwd_from", None)
    if forwarded is None:
        return None
    origin = getattr(forwarded, "from_id", None)
    origin_peer_id = next(
        (
            getattr(origin, field)
            for field in ("channel_id", "chat_id", "user_id")
            if getattr(origin, field, None) is not None
        ),
        None,
    )
    forwarded_at = getattr(forwarded, "date", None)
    return {
        "origin_peer_id": origin_peer_id,
        "origin_name": getattr(forwarded, "from_name", None),
        "origin_message_id": getattr(forwarded, "channel_post", None),
        "forwarded_at": (
            forwarded_at.isoformat() if isinstance(forwarded_at, datetime) else None
        ),
        "post_author": getattr(forwarded, "post_author", None),
    }


def message_record(
    *,
    policy: TelegramChannelPolicy,
    peer_id: int,
    resolved_username: str | None,
    channel_title: str | None,
    message: object,
    source_id: str | None = None,
) -> dict[str, Any] | None:
    """Normalize one text message without interpreting its event meaning."""
    policy.validate(peer_id=peer_id, resolved_username=resolved_username)
    raw_text = getattr(message, "raw_text", None)
    if not isinstance(raw_text, str) or not raw_text.strip():
        return None
    message_id = int(getattr(message, "id"))
    posted_at = getattr(message, "date")
    if not isinstance(posted_at, datetime) or posted_at.tzinfo is None:
        raise ValueError("Telegram message timestamp must carry a UTC offset")
    edited_at = getattr(message, "edit_date", None)
    return {
        "cell_id": f"telegram:{peer_id}:{message_id}",
        "observed_at": posted_at,
        "payload": {
            # The allowlist key. Tier is looked up from it at classification
            # time and is deliberately not copied in here: a tier corrected in
            # the table must not leave a stale copy in every stored message.
            "source_id": source_id,
            "kind": "telegram",
            "peer_id": peer_id,
            "configured_username": policy.username,
            "channel_username": resolved_username,
            "channel_title": channel_title,
            "message_id": message_id,
            "posted_at": posted_at.isoformat(),
            "edited_at": edited_at.isoformat() if isinstance(edited_at, datetime) else None,
            "raw_text": raw_text,
            "source_url": public_message_url(resolved_username, message_id),
            "source_verification": policy.verification(peer_id),
            "forwarded_provenance": _forwarded_provenance(message),
        },
    }


def policies_from_allowlist() -> tuple[tuple[TelegramChannelPolicy, str, int | None], ...]:
    """The active Telegram rows of `text_sources`, as policies to collect with.

    The allowlist owns which channels exist and what tier each one carries; the
    policy object still owns identity, because a pinned peer id is the only
    thing standing between a released username and a silent source swap. Each
    entry carries its `source_id` and its cursor alongside.
    """
    entries = []
    for source in active_sources("telegram"):
        entries.append((
            TelegramChannelPolicy(
                username=source.handle,
                role=source.tier,
                verification_tier=source.tier,
                # Kept so an operator can still override a pin from the
                # environment without a database write during an incident.
                peer_id_environment=f"TELEGRAM_PEER_ID_{source.handle.upper()}",
                verified_peer_id=source.peer_id,
            ),
            source.source_id,
            source.last_message_id,
        ))
    return tuple(entries)


class TelegramCollector(BaseCollector):
    source = "telegram"

    def __init__(
        self,
        channels: tuple[tuple[TelegramChannelPolicy, str, int | None], ...] | None = None,
    ) -> None:
        # Read at run time, not at import: a channel added to the allowlist
        # mid-shift must be collected on the next tick, not after a restart.
        self._channels = channels

    @property
    def channels(self) -> tuple[tuple[TelegramChannelPolicy, str, int | None], ...]:
        if self._channels is not None:
            return self._channels
        return policies_from_allowlist()

    def store(self, records: list[dict[str, Any]]) -> int:
        """Apply edits. Operational channels revise posts as incidents run."""
        return upsert_editable_observations(self.source, records)

    async def _collect(self) -> list[dict[str, Any]]:
        api_id, api_hash = load_credentials()
        client = TelegramClient(str(get_session_path()), api_id, api_hash)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise RuntimeError(
                    "Telegram session is not authorised. Run "
                    "`python -m ecoguard.collectors.shared.telegram.listener --discover` "
                    "once to log in and discover peer IDs."
                )
            records: list[dict[str, Any]] = []
            for policy, source_id, cursor in self.channels:
                entity = await client.get_entity(policy.username)
                peer_id = int(await client.get_peer_id(entity))
                username = getattr(entity, "username", None)
                title = getattr(entity, "title", None)
                policy.validate(peer_id=peer_id, resolved_username=username)

                # min_id is the backfill: everything published since the last
                # successful read, however long the process was down, instead
                # of the newest fifty and a hole. The limit still caps a first
                # run and a long outage — the cursor advances either way, so a
                # deeper backlog is caught over the next few ticks rather than
                # in one enormous fetch.
                #
                # The cursor is rewound before it is used, because an edit does
                # not change a message id: asking for strictly-newer messages
                # would collect a post once and never see it revised, and these
                # channels revise. Re-reading the last EDIT_RECHECK_MESSAGES
                # costs nothing to store — the upsert writes only rows whose
                # payload actually changed.
                #
                # ponytail: a fixed rewind, not edit tracking. It catches edits
                # to recent posts, which is what operational channels do; an
                # edit older than that window is missed. Telethon's
                # MessageEdited event is the upgrade if that ever matters.
                highest = cursor or 0
                async for message in client.iter_messages(
                    entity,
                    limit=MESSAGES_PER_CHANNEL,
                    min_id=max(0, (cursor or 0) - EDIT_RECHECK_MESSAGES),
                ):
                    highest = max(highest, int(getattr(message, "id", 0)))
                    record = message_record(
                        policy=policy,
                        peer_id=peer_id,
                        resolved_username=username,
                        channel_title=title,
                        message=message,
                        source_id=source_id,
                    )
                    if record is not None:
                        records.append(record)

                # An edited message keeps its id, so the cursor never hides one:
                # min_id filters by id and an edit does not change it. What the
                # cursor skips is only what has already been stored, and the
                # edit-aware upsert handles the rest.
                record_poll(source_id, last_message_id=highest or None)
            return records
        finally:
            await client.disconnect()

    def fetch(self) -> list[dict[str, Any]]:
        return asyncio.run(self._collect())
