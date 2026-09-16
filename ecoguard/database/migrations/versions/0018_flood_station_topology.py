"""Cache station-to-stream matches and complete downstream routes.

Revision ID: flood_station_topology
Revises: radar_frame_cache
Create Date: 2026-09-16
"""

from alembic import op


revision = "flood_station_topology"
down_revision = "radar_frame_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE flood_station_topology (
          hydrometric_station_id bigint PRIMARY KEY
            REFERENCES hydrometric_stations(id) ON DELETE CASCADE,
          stream_context         jsonb NOT NULL,
          downstream_route       jsonb NOT NULL,
          refreshed_at           timestamptz NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS flood_station_topology")
