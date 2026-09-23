"""Persist IMS radar frame watermarks for outage catch-up.

Revision ID: radar_frame_cache
Revises: flood_detector_runtime
Create Date: 2026-09-16
"""

from alembic import op


revision = "radar_frame_cache"
down_revision = "flood_detector_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add persist IMS radar frame watermarks for outage catch-up."""
    op.execute(
        """
        CREATE TABLE radar_frame_cache (
          source_file text PRIMARY KEY,
          observed_at timestamptz NOT NULL,
          cached_at timestamptz NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX radar_frame_cache_observed_at_idx "
        "ON radar_frame_cache (observed_at DESC)"
    )
    op.execute(
        """
        INSERT INTO radar_frame_cache (source_file, observed_at, cached_at)
        SELECT payload->>'source_file', max(observed_at), max(ingested_at)
        FROM observations
        WHERE source = 'ims_radar_ppi'
          AND payload ? 'source_file'
          AND payload->>'source_file' IS NOT NULL
        GROUP BY payload->>'source_file'
        ON CONFLICT (source_file) DO NOTHING
        """
    )


def downgrade() -> None:
    """Remove persist IMS radar frame watermarks for outage catch-up."""
    op.execute("DROP TABLE IF EXISTS radar_frame_cache")
