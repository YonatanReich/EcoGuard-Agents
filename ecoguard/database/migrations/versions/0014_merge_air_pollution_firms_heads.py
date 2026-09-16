"""Merge Air Pollution and Fire incident migration heads."""

from __future__ import annotations

revision = "air_pollution_firms_merge"
down_revision = ("air_pollution_weather_merge", "firms_baselines")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
