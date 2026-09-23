"""mda_stations

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-10
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add mda_stations."""
    # Same shape as fire_stations and police_stations: a geography(Point, 4326)
    # under a GiST index, so a "nearest responder" query reads identically
    # against any of the three and they union without casting.
    #
    # location is nullable, as on fire_stations and unlike police_stations:
    # Magen David Adom publishes a roster of station names and addresses with no
    # coordinates, and 36 of the 169 entries give no address at all.
    op.execute(
        """
        CREATE TABLE mda_stations (
          id          bigserial PRIMARY KEY,
          station_id  integer NOT NULL,
          name        text    NOT NULL,
          locality    text,
          address     text,
          location    geography(Point, 4326),
          source      jsonb   NOT NULL DEFAULT '{}'::jsonb,
          CONSTRAINT mda_stations_identity UNIQUE (station_id)
        )
        """
    )
    op.execute("CREATE INDEX mda_stations_location_idx ON mda_stations USING GIST (location)")


def downgrade() -> None:
    """Remove mda_stations."""
    op.execute("DROP TABLE IF EXISTS mda_stations")
