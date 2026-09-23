"""Merge Air Pollution and Fire incident migration heads."""

from __future__ import annotations

revision = "air_pollution_firms_merge"
down_revision = ("air_pollution_weather_merge", "firms_baselines")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Rejoin the air-pollution and fire migration histories."""
    pass


def downgrade() -> None:
    """Split the two migration histories again."""
    pass
