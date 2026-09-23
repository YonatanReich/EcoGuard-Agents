"""Credential and external Telethon-session handling."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def load_credentials() -> tuple[int, str]:
    """The Telegram API credentials, failing clearly when they are absent."""
    load_dotenv()
    raw_api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    if not raw_api_id or not api_hash:
        raise RuntimeError("Telegram API credentials are missing from the environment.")
    try:
        return int(raw_api_id), api_hash
    except ValueError as error:
        raise RuntimeError("TELEGRAM_API_ID must be a valid integer.") from error


def get_session_path() -> Path:
    """Where the logged-in Telegram session is kept on this machine."""
    local_app_data = os.getenv("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is required for secure Telegram session storage.")
    directory = Path(local_app_data) / "EcoGuard" / "telegram"
    directory.mkdir(parents=True, exist_ok=True)
    # Preserve the established external filename so existing authorised
    # sessions survive the Fire-to-shared ownership move.
    return directory / "fire_listener"
