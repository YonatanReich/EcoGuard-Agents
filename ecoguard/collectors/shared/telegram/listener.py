"""Interactive Telegram session bootstrap and stable peer-ID discovery."""

from __future__ import annotations

import argparse
import asyncio
from getpass import getpass

from telethon import TelegramClient

from ecoguard.collectors.shared.telegram.policy import CHANNEL_POLICIES
from ecoguard.collectors.shared.telegram.session import get_session_path, load_credentials


async def discover_channels() -> list[dict[str, object]]:
    """Log in interactively and resolve each configured channel to its numeric identity."""
    api_id, api_hash = load_credentials()
    client = TelegramClient(str(get_session_path()), api_id, api_hash)
    await client.start(
        code_callback=lambda: getpass("Telegram login code: "),
        password=lambda: getpass("Telegram two-step verification password: "),
    )
    try:
        discovered = []
        for policy in CHANNEL_POLICIES:
            entity = await client.get_entity(policy.username)
            peer_id = int(await client.get_peer_id(entity))
            username = getattr(entity, "username", None)
            policy.validate(peer_id=peer_id, resolved_username=username)
            discovered.append({
                "configured_username": policy.username,
                "resolved_username": username,
                "title": getattr(entity, "title", None),
                "peer_id": peer_id,
                "pin_environment": policy.peer_id_environment,
                "currently_pinned": policy.pinned_peer_id,
            })
        return discovered
    finally:
        await client.disconnect()


def main() -> int:
    """Run channel discovery from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--discover", action="store_true",
        help="resolve configured usernames and print peer IDs to pin",
    )
    args = parser.parse_args()
    if not args.discover:
        parser.error("--discover is required; this utility does not run a live listener")
    for item in asyncio.run(discover_channels()):
        print(
            f"@{item['resolved_username']} peer_id={item['peer_id']} "
            f"pin={item['pin_environment']} current={item['currently_pinned'] or 'unset'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
