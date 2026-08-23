"""Standalone Telegram channel listener for fire-intelligence exploration.

This proof of concept prints new messages from a small, fixed set of public
channels. It intentionally has no classification, filtering, persistence, or
web application integration.
"""

import asyncio
import os
from getpass import getpass
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, events

from agents.hebrew_fire_location_extractor import extract_fire_location
from agents.telegram_fire_candidate_filter import detect_fire_candidate
from services.nominatim_geocoding_service import geocode_fire_location


CHANNELS = (
    "mdaisrael",
    "Israel_Police_100",
    "fireisrael7777",
)


def skipped_geocode_result() -> dict:
    """Return an explicit result when the listener must not call Nominatim."""
    return {
        "latitude": None,
        "longitude": None,
        "display_name": None,
        "confidence": 0.0,
        "precision": None,
        "status": "skipped",
    }


def load_credentials() -> tuple[int, str]:
    """Load and validate Telegram API credentials without logging them."""
    load_dotenv()

    api_id_value = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")

    if not api_id_value or not api_hash:
        raise RuntimeError(
            "Telegram API credentials are missing from the environment."
        )

    try:
        api_id = int(api_id_value)
    except ValueError as error:
        raise RuntimeError(
            "TELEGRAM_API_ID must be a valid integer."
        ) from error

    return api_id, api_hash


def get_session_path() -> Path:
    """Return a Telethon session path outside the repository on Windows."""
    local_app_data = os.getenv("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError(
            "LOCALAPPDATA is required for secure Telegram session storage."
        )

    session_directory = Path(local_app_data) / "EcoGuard" / "telegram"
    session_directory.mkdir(parents=True, exist_ok=True)
    return session_directory / "fire_listener"


async def main() -> None:
    """Connect to Telegram and print new messages from configured channels."""
    api_id, api_hash = load_credentials()
    client = TelegramClient(str(get_session_path()), api_id, api_hash)
    seen_messages: set[tuple[int, int]] = set()

    @client.on(events.NewMessage(chats=CHANNELS))
    async def handle_new_message(event: events.NewMessage.Event) -> None:
        message_key = (event.chat_id, event.message.id)
        if message_key in seen_messages:
            return
        seen_messages.add(message_key)

        result = detect_fire_candidate(event.raw_text)
        if not result["is_fire_candidate"]:
            return
        location = extract_fire_location(event.raw_text)
        geocode = (
            geocode_fire_location(location)
            if location["confidence"] >= 0.80 and location["city"]
            else skipped_geocode_result()
        )

        chat = await event.get_chat()
        username = getattr(chat, "username", None)
        title = getattr(chat, "title", None)
        channel = f"@{username}" if username else title or "unknown"

        print("FIRE CANDIDATE")
        print("type: live")
        print(f"channel: {channel}")
        print(f"timestamp: {event.message.date.isoformat()}")
        print(f"fire_confidence: {result['confidence']}")
        print(f"matched_terms: {result['matched_terms']}")
        print(f"reason: {result['reason']}")
        print(f"location_text: {location['location_text']}")
        print(f"city: {location['city']}")
        print(f"street: {location['street']}")
        print(f"neighborhood: {location['neighborhood']}")
        print(f"location_confidence: {location['confidence']}")
        print(f"geocode_status: {geocode['status']}")
        print(f"latitude: {geocode['latitude']}")
        print(f"longitude: {geocode['longitude']}")
        print(f"geocode_precision: {geocode['precision']}")
        print(f"geocode_confidence: {geocode['confidence']}")
        print(f"geocode_display_name: {geocode['display_name']}")
        print(f"text: {event.raw_text}")
        print("---")

    await client.start(
        code_callback=lambda: getpass("Telegram login code: "),
        password=lambda: getpass("Telegram two-step verification password: "),
    )

    for configured_channel in CHANNELS:
        chat = await client.get_entity(configured_channel)
        username = getattr(chat, "username", None)
        title = getattr(chat, "title", None)
        channel = f"@{username}" if username else title or configured_channel
        chat_id = await client.get_peer_id(chat)

        recent_messages = []

        async for message in client.iter_messages(
            chat,
            limit=100,
        ):
            raw_text = message.raw_text
            if not raw_text or not raw_text.strip():
                continue

            recent_messages.append((message, raw_text))
            if len(recent_messages) == 20:
                break

        for message, raw_text in reversed(recent_messages):
            message_key = (chat_id, message.id)
            if message_key in seen_messages:
                continue
            seen_messages.add(message_key)

            result = detect_fire_candidate(raw_text)
            if not result["is_fire_candidate"]:
                continue
            location = extract_fire_location(raw_text)
            geocode = (
                geocode_fire_location(location)
                if location["confidence"] >= 0.80 and location["city"]
                else skipped_geocode_result()
            )

            print("FIRE CANDIDATE")
            print("type: historical")
            print(f"channel: {channel}")
            print(f"timestamp: {message.date.isoformat()}")
            print(f"fire_confidence: {result['confidence']}")
            print(f"matched_terms: {result['matched_terms']}")
            print(f"reason: {result['reason']}")
            print(f"location_text: {location['location_text']}")
            print(f"city: {location['city']}")
            print(f"street: {location['street']}")
            print(f"neighborhood: {location['neighborhood']}")
            print(f"location_confidence: {location['confidence']}")
            print(f"geocode_status: {geocode['status']}")
            print(f"latitude: {geocode['latitude']}")
            print(f"longitude: {geocode['longitude']}")
            print(f"geocode_precision: {geocode['precision']}")
            print(f"geocode_confidence: {geocode['confidence']}")
            print(f"geocode_display_name: {geocode['display_name']}")
            print(f"text: {raw_text}")
            print("---")

    print("Telegram fire intelligence listener is running.")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
