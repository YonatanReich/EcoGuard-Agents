"""Raw Telegram channel messages. No classification, no location extraction.

Interpretation is deliberately absent. If the extractor ran here the original
Hebrew text would be discarded and old messages could never be re-read when the
prompt improves; storing raw also leaves a replayable corpus for tuning it.
"""

from __future__ import annotations

import asyncio
from typing import Any

from telethon import TelegramClient

from ecoguard.collection.fire.telegram.listener import CHANNELS, get_session_path, load_credentials
from ecoguard.collection.base import BaseCollector

# At a five-minute tick this covers far more than any of these channels post,
# and the unique constraint discards the overlap.
MESSAGES_PER_CHANNEL = 50


class TelegramCollector(BaseCollector):
    source = "telegram"

    def __init__(self, channels: tuple[str, ...] = CHANNELS):
        self.channels = channels

    async def _collect(self) -> list[dict[str, Any]]:
        api_id, api_hash = load_credentials()
        client = TelegramClient(str(get_session_path()), api_id, api_hash)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                # Logging in needs a code typed by a human, which a scheduled
                # job cannot do. Run ecoguard/collection/fire/telegram/listener.py once to
                # create the session; this collector then reuses it forever.
                raise RuntimeError(
                    "Telegram session is not authorised. Run "
                    "`python -m ecoguard.collection.fire.telegram.listener` once to log in."
                )

            records = []
            for channel in self.channels:
                async for message in client.iter_messages(channel, limit=MESSAGES_PER_CHANNEL):
                    text = message.raw_text
                    if not text or not text.strip():
                        continue
                    records.append({
                        # No location is known until the extractor runs in
                        # detection, so cell_id carries the message identity
                        # instead — it is what makes a re-poll idempotent.
                        "cell_id": f"{channel}:{message.id}",
                        "observed_at": message.date,
                        "payload": {
                            "channel": channel,
                            "message_id": message.id,
                            "text": text,
                            "posted_at": message.date.isoformat(),
                        },
                    })
            return records
        finally:
            await client.disconnect()

    def fetch(self) -> list[dict[str, Any]]:
        """Poll rather than listen: a scheduled worker cannot hold a socket open."""
        return asyncio.run(self._collect())
