"""Road geometry used to locate flood response sites.

Revision ID: flood_road_segments
Revises: police_station_responsibility
Create Date: 2026-09-20
"""

from alembic import op


revision = "flood_road_segments"
down_revision = "police_station_responsibility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add road geometry used to locate flood response sites."""
    op.execute(
        """
        CREATE TABLE road_segments (
          id                 bigserial PRIMARY KEY,
          source             text        NOT NULL,
          source_feature_id  text        NOT NULL,
          road_class         text        NOT NULL,
          name               text,
          road_ref           text,
          bridge             boolean     NOT NULL DEFAULT false,
          tunnel             boolean     NOT NULL DEFAULT false,
          vehicle_access     boolean,
          geometry           geometry(MultiLineString, 4326) NOT NULL,
          properties         jsonb       NOT NULL DEFAULT '{}'::jsonb,
          imported_at        timestamptz NOT NULL,
          CONSTRAINT road_segments_identity
            UNIQUE (source, source_feature_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX road_segments_geometry_idx "
        "ON road_segments USING GIST (geometry)"
    )
    op.execute(
        "CREATE INDEX road_segments_class_idx "
        "ON road_segments (road_class)"
    )
    op.execute(
        "CREATE INDEX road_segments_ref_idx "
        "ON road_segments (road_ref) WHERE road_ref IS NOT NULL"
    )


def downgrade() -> None:
    """Remove road geometry used to locate flood response sites."""
    op.execute("DROP TABLE IF EXISTS road_segments")
