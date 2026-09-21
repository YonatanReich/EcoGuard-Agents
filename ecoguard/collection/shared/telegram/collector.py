"""Raw Telegram polling for later Fire/Flood evidence processing."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from telethon import TelegramClient

from ecoguard.collection.base import BaseCollector
from ecoguard.collection.shared.telegram.policy import (
    CHANNEL_POLICIES,
    TelegramChannelPolicy,
    public_message_url,
)
from ecoguard.collection.shared.telegram.session import get_session_path, load_credentials


MESSAGES_PER_CHANNEL = 50


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


class TelegramCollector(BaseCollector):
    source = "telegram"

    def __init__(
        self,
        channels: tuple[TelegramChannelPolicy, ...] = CHANNEL_POLICIES,
    ) -> None:
        self.channels = channels

    async def _collect(self) -> list[dict[str, Any]]:
        api_id, api_hash = load_credentials()
        client = TelegramClient(str(get_session_path()), api_id, api_hash)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise RuntimeError(
                    "Telegram session is not authorised. Run "
                    "`python -m ecoguard.collection.shared.telegram.listener --discover` "
                    "once to log in and discover peer IDs."
                )
            records: list[dict[str, Any]] = []
            for policy in self.channels:
                entity = await client.get_entity(policy.username)
                peer_id = int(await client.get_peer_id(entity))
                username = getattr(entity, "username", None)
                title = getattr(entity, "title", None)
                policy.validate(peer_id=peer_id, resolved_username=username)
                async for message in client.iter_messages(entity, limit=MESSAGES_PER_CHANNEL):
                    record = message_record(
                        policy=policy,
                        peer_id=peer_id,
                        resolved_username=username,
                        channel_title=title,
                        message=message,
                    )
                    if record is not None:
                        records.append(record)
            return records
        finally:
            await client.disconnect()

    def fetch(self) -> list[dict[str, Any]]:
        return asyncio.run(self._collect())
