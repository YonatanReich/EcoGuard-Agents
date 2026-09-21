"""Backward-compatible import for the shared Telegram collector."""

from ecoguard.collection.shared.telegram.collector import (  # noqa: F401
    MESSAGES_PER_CHANNEL,
    TelegramCollector,
    message_record,
)
