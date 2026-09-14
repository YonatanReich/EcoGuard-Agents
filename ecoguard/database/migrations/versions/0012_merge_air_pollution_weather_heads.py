"""Merge Air Pollution and current-main migration branches.

Revision ID: air_pollution_weather_merge
Revises: 0010, weather_baselines
"""

from __future__ import annotations

revision = "air_pollution_weather_merge"
down_revision = ("0010", "weather_baselines")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Join the two additive migration lineages without changing schema."""


def downgrade() -> None:
    """Moving below the merge point changes no schema."""
