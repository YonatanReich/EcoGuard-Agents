"""Shared national locality reference layer.

Revision ID: localities
Revises: event_projections
Create Date: 2026-09-17
"""

from alembic import op


revision = "localities"
down_revision = "event_projections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE localities (
          locality_code       text                    PRIMARY KEY,
          name_he             text                    NOT NULL,
          name_en             text,
          locality_type       text,
          boundary            geometry(MultiPolygon, 4326) NOT NULL,
          representative_point geometry(Point, 4326) NOT NULL,
          source              text,
          source_resource_id  text,
          source_updated_at   timestamptz,
          imported_at         timestamptz             NOT NULL DEFAULT now(),
          source_version      text,
          source_checksum     varchar(64),
          raw_properties      jsonb,
          CONSTRAINT localities_code_not_blank
            CHECK (btrim(locality_code) <> ''),
          CONSTRAINT localities_name_he_not_blank
            CHECK (btrim(name_he) <> ''),
          CONSTRAINT localities_boundary_valid
            CHECK (ST_IsValid(boundary) AND NOT ST_IsEmpty(boundary)),
          CONSTRAINT localities_representative_point_valid
            CHECK (NOT ST_IsEmpty(representative_point)),
          CONSTRAINT localities_checksum_format
            CHECK (source_checksum IS NULL OR source_checksum ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute(
        "CREATE INDEX localities_boundary_gix "
        "ON localities USING GIST (boundary)"
    )
    op.execute(
        "CREATE INDEX localities_representative_point_gix "
        "ON localities USING GIST (representative_point)"
    )
    op.execute(
        "CREATE INDEX localities_representative_point_geography_gix "
        "ON localities USING GIST ((representative_point::geography))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS localities_representative_point_geography_gix")
    op.execute("DROP INDEX IF EXISTS localities_representative_point_gix")
    op.execute("DROP INDEX IF EXISTS localities_boundary_gix")
    op.execute("DROP TABLE IF EXISTS localities")
