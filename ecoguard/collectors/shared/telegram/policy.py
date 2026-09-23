"""Which Telegram channels are read, and how their identity is checked.

A channel name can be released and taken over by someone else, so each one is
also pinned to its numeric identity; a channel that answers under the right
name but the wrong number is refused."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any


_PUBLIC_USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")


class TelegramChannelIdentityError(RuntimeError):
    """A configured username resolved to an unexpected Telegram peer."""


@dataclass(frozen=True)
class TelegramChannelPolicy:
    username: str
    role: str
    verification_tier: str
    peer_id_environment: str
    verified_peer_id: int | None = None

    @property
    def pinned_peer_id(self) -> int | None:
        """The numeric identity this channel is pinned to, if any."""
        raw = os.getenv(self.peer_id_environment)
        if raw is None or not raw.strip():
            return self.verified_peer_id
        try:
            configured = int(raw)
        except ValueError as error:
            raise RuntimeError(
                f"{self.peer_id_environment} must be a Telegram numeric peer ID"
            ) from error
        if self.verified_peer_id is not None and configured != self.verified_peer_id:
            raise TelegramChannelIdentityError(
                f"{self.peer_id_environment}={configured} conflicts with verified "
                f"peer {self.verified_peer_id} for {self.username!r}"
            )
        return configured

    def verification(self, peer_id: int) -> dict[str, Any]:
        """Whether the channel that answered is the one we pinned, and in what role."""
        pinned = self.pinned_peer_id
        verified = pinned is not None and peer_id == pinned
        return {
            "tier": self.verification_tier if verified else "unverified",
            "role": self.role,
            "peer_id_pinned": pinned is not None,
            "peer_id_verified": verified,
            "event_verified": False,
        }

    def validate(self, *, peer_id: int, resolved_username: str | None) -> None:
        """Reject a channel whose name or numeric identity does not match what was configured.

        A username can be released and re-registered by someone else, so the
        numeric identity is what is trusted.
        """
        if not resolved_username or resolved_username.casefold() != self.username.casefold():
            raise TelegramChannelIdentityError(
                f"configured Telegram username {self.username!r} resolved as "
                f"{resolved_username!r}"
            )
        pinned = self.pinned_peer_id
        if pinned is not None and peer_id != pinned:
            raise TelegramChannelIdentityError(
                f"configured Telegram username {self.username!r} resolved to peer "
                f"{peer_id}, expected pinned peer {pinned}"
            )


CHANNEL_POLICIES = (
    TelegramChannelPolicy(
        "Israel_Police_100", "official_supporting_source", "official_supporting",
        "TELEGRAM_PEER_ID_ISRAEL_POLICE_100", -1002843129862,
    ),
    TelegramChannelPolicy(
        "Atanpolice", "official_supporting_source", "official_supporting",
        "TELEGRAM_PEER_ID_ATANPOLICE", -1001581748447,
    ),
    TelegramChannelPolicy(
        "mdaisrael", "official_supporting_source", "official_supporting",
        "TELEGRAM_PEER_ID_MDAISRAEL", -1001177174722,
    ),
    TelegramChannelPolicy(
        "fireisrael7777", "unofficial_aggregator", "unofficial_aggregator",
        "TELEGRAM_PEER_ID_FIREISRAEL7777", -1001411503185,
    ),
)


def policy_for_username(username: object) -> TelegramChannelPolicy | None:
    """The policy configured for this channel name, if there is one."""
    if not isinstance(username, str):
        return None
    folded = username.removeprefix("@").casefold()
    return next(
        (policy for policy in CHANNEL_POLICIES if policy.username.casefold() == folded),
        None,
    )


def public_message_url(username: str | None, message_id: int) -> str | None:
    """A link to one message, when the channel is public enough to have one."""
    if not username or not _PUBLIC_USERNAME.fullmatch(username):
        return None
    return f"https://t.me/{username}/{message_id}"
