"""Build a bounded, manually reviewed official-Telegram wildfire pilot."""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from scripts.build_strong_historical_wildfire_ground_truth import (
    FIRMS_INPUT,
    confidence_tier,
    load_firms,
    match_firms,
)


OUTPUT_PATH = Path("data/generated/historical_wildfire_telegram_pilot_2023_2026.csv")
CHANNEL_IDENTIFIER = "Israel_Police_100"
OUTPUT_FIELDS = (
    "telegram_event_id", "channel_name", "channel_identifier", "message_id",
    "message_timestamp", "raw_message_text", "event_date", "location_text",
    "latitude", "longitude", "timestamp_precision", "location_precision",
    "event_type", "open_area_indicator", "source_authority",
    "telegram_source_url_or_identifier", "firms_match_status",
    "firms_candidate_id", "firms_match_count", "firms_distance_km",
    "firms_time_gap_hours", "label_confidence_tier", "notes",
)


@dataclass(frozen=True)
class CuratedLocation:
    location_text: str
    city: str
    street: str | None = None
    location_precision: str = "locality"


# These are provenance anchors for two manually reviewed public Police messages,
# not fabricated incidents. Other screened messages failed scope/location/FIRMS rules.
CURATED_MESSAGES = {
    362: CuratedLocation("חורש סמוך ליישוב מבשרת ציון", "מבשרת ציון"),
    4286: CuratedLocation("שטח פתוח סמוך ליישוב שמשית בעמק יזרעאל", "שמשית"),
}


def _session_path() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is required for secure Telegram session storage")
    return Path(local_app_data) / "EcoGuard" / "telegram" / "fire_listener"


def normalize_message(
    message: Any,
    location: CuratedLocation,
    firms: list[Mapping[str, Any]],
    *,
    geocoder: Callable[[dict], dict] | None = None,
) -> dict[str, Any] | None:
    """Normalize one reviewed message, retaining it only under existing Tier rules."""
    raw_text = str(message.raw_text or "").strip()
    if not raw_text:
        return None
    if geocoder is None:
        from services.nominatim_geocoding_service import geocode_fire_location
        geocoder = geocode_fire_location
    geocode = geocoder({
        "city": location.city,
        "street": location.street,
        "neighborhood": None,
        "confidence": 0.85,
    })
    if geocode.get("status") != "resolved":
        return None
    event = {
        "event_timestamp_start": message.date.isoformat(),
        "timestamp_precision": "minute",
        "latitude": geocode["latitude"],
        "longitude": geocode["longitude"],
        "location_precision": location.location_precision,
        "open_area_indicator": "true",
        "source_authority_level": "official_emergency_service",
    }
    firms_match = match_firms(event, firms)
    tier, _ = confidence_tier(event, firms_match)
    if tier not in {"strong_event_support", "multi_source_probable_fire"}:
        return None
    selected = firms_match["selected"]
    candidate = selected[2]
    message_id = int(message.id)
    return {
        "telegram_event_id": f"telegram_police_{message_id}",
        "channel_name": "דוברות משטרת ישראל",
        "channel_identifier": f"@{CHANNEL_IDENTIFIER}",
        "message_id": message_id,
        "message_timestamp": message.date.isoformat(),
        "raw_message_text": raw_text,
        "event_date": message.date.date().isoformat(),
        "location_text": location.location_text,
        "latitude": geocode["latitude"],
        "longitude": geocode["longitude"],
        "timestamp_precision": "minute",
        "location_precision": location.location_precision,
        "event_type": "wildfire_or_open_area_fire",
        "open_area_indicator": "true",
        "source_authority": "official_emergency_service",
        "telegram_source_url_or_identifier": f"https://t.me/{CHANNEL_IDENTIFIER}/{message_id}",
        "firms_match_status": firms_match["status"],
        "firms_candidate_id": candidate["candidate_id"],
        "firms_match_count": len(firms_match["matches"]),
        "firms_distance_km": round(selected[0], 6),
        "firms_time_gap_hours": round(selected[1], 6),
        "label_confidence_tier": tier,
        "notes": "Manually reviewed official Police message; coordinates are a geocoded named-locality/street reference, not an ignition point.",
    }


async def build(output_path: Path = OUTPUT_PATH) -> list[dict[str, Any]]:
    """Fetch only curated message IDs using the existing external session."""
    from dotenv import load_dotenv
    from telethon import TelegramClient

    load_dotenv(Path.cwd() / ".env")
    api_id, api_hash = os.getenv("TELEGRAM_API_ID"), os.getenv("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        raise RuntimeError("Telegram API configuration is missing")
    firms = load_firms(FIRMS_INPUT)
    async with TelegramClient(str(_session_path()), int(api_id), api_hash) as client:
        channel = await client.get_entity(CHANNEL_IDENTIFIER)
        if getattr(channel, "username", None) != CHANNEL_IDENTIFIER:
            raise RuntimeError("Telegram channel identity did not match the reviewed channel")
        messages = await client.get_messages(channel, ids=sorted(CURATED_MESSAGES))
    rows = []
    for message in sorted((item for item in messages if item), key=lambda item: item.id):
        row = normalize_message(message, CURATED_MESSAGES[message.id], firms)
        if row:
            rows.append(row)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(output_path)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    rows = asyncio.run(build(args.output))
    print(f"Wrote {len(rows)} Tier A/B Telegram pilot events to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
