"""merge the towns and air-pollution heads

Revision ID: towns_air_pollution_merge
Revises: air_pollution_weather_merge, towns
Create Date: 2026-09-17

Two features grew from `weather_baselines` at the same time — air pollution on
main, fire events on this branch — so merging the branches leaves alembic with
two heads and `alembic upgrade head` refusing to choose between them.

This joins them. It has no upgrade body of its own: nothing here changes the
schema, it only records that the two lines are one again. Same shape as
0012_merge_air_pollution_weather_heads, which did this for the previous pair.

Non-numeric identifier for the same reason as the ones before it: sibling
branches claim numeric ids and alembic resolves stored revisions by prefix.
"""

revision = "towns_air_pollution_merge"
down_revision = ("air_pollution_weather_merge", "towns")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Nothing to do: a merge revision only rejoins the history."""


def downgrade() -> None:
    """Nothing to undo."""
