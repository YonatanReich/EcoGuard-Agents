"""police_stations

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-10
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add police_stations."""
    # Deliberately the same shape as fire_stations: a geography(Point, 4326)
    # under a GiST index. A later "nearest responder to this event" query then
    # reads identically whichever table it runs against, and the two can be
    # unioned without casting.
    #
    # Unlike fire_stations, location is NOT NULL. The Israel Police publishes a
    # coordinate for every station, so a row without one would mean the loader
    # dropped it rather than that the position is unknown.
    op.execute(
        """
        CREATE TABLE police_stations (
          id          bigserial PRIMARY KEY,
          station_id  bigint  NOT NULL,
          name        text    NOT NULL,
          kind        text    NOT NULL,
          city        text,
          address     text,
          phone       text,
          location    geography(Point, 4326) NOT NULL,
          source      jsonb   NOT NULL DEFAULT '{}'::jsonb,
          CONSTRAINT police_stations_identity UNIQUE (station_id)
        )
        """
    )
    op.execute("CREATE INDEX police_stations_location_idx ON police_stations USING GIST (location)")
    # The published list mixes district headquarters, regional headquarters,
    # full stations and small posts; kind is what tells a dispatcher which.
    op.execute("CREATE INDEX police_stations_kind_idx ON police_stations (kind)")


def downgrade() -> None:
    """Remove police_stations."""
    op.execute("DROP TABLE IF EXISTS police_stations")
