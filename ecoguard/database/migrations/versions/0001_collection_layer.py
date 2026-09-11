"""Extensions, observations and collector_runs

Revision ID: 0001
Revises:
Create Date: 2026-09-07
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extensions come first: observations.location is a PostGIS type, so
    # creating the table before postgis exists fails. vector is unused today
    # but enabling it now costs nothing and saves a migration later.
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Written as raw SQL rather than op.create_table so the geography column
    # and its GiST index read exactly as they will exist in the database.
    op.execute(
        """
        CREATE TABLE observations (
          id           bigserial PRIMARY KEY,
          source       text        NOT NULL,
          cell_id      text        NOT NULL,
          location     geography(Point, 4326),
          observed_at  timestamptz NOT NULL,
          ingested_at  timestamptz NOT NULL,
          payload      jsonb       NOT NULL,
          CONSTRAINT observations_identity UNIQUE (source, cell_id, observed_at)
        )
        """
    )
    op.execute("CREATE INDEX observations_source_ingested_at_idx ON observations (source, ingested_at)")
    op.execute("CREATE INDEX observations_location_idx ON observations USING GIST (location)")

    op.execute(
        """
        CREATE TABLE collector_runs (
          id            bigserial PRIMARY KEY,
          source        text        NOT NULL,
          started_at    timestamptz NOT NULL,
          finished_at   timestamptz,
          status        text        NOT NULL,
          rows_written  integer,
          error         text
        )
        """
    )
    op.execute("CREATE INDEX collector_runs_source_started_at_idx ON collector_runs (source, started_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS collector_runs")
    op.execute("DROP TABLE IF EXISTS observations")
    # The extensions are left installed: other databases in the same cluster
    # may depend on them, and re-enabling is cheap.
