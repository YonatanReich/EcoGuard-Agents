"""Backward-compatible bootstrap import; no live evidence listener remains here."""

from ecoguard.collection.shared.telegram.listener import (  # noqa: F401
    discover_channels,
    main,
)
from ecoguard.collection.shared.telegram.policy import CHANNEL_POLICIES
from ecoguard.collection.shared.telegram.session import get_session_path, load_credentials

CHANNELS = tuple(policy.username for policy in CHANNEL_POLICIES)


if __name__ == "__main__":
    raise SystemExit(main())
