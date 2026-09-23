"""fire_stations

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-07
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add fire_stations."""
    # Raw SQL for the same reason as 0001: the geography column and its GiST
    # index read exactly as they will exist in the database.
    #
    # Unlike observations this is reference data, not a time series — one row
    # per station, replaced when the authority republishes its list. The
    # identity is (district, name) because station names are only unique
    # within a district in the published table.
    op.execute(
        """
        CREATE TABLE fire_stations (
          id        bigserial PRIMARY KEY,
          district  text    NOT NULL,
          name      text    NOT NULL,
          regional  boolean NOT NULL,
          address   text,
          location  geography(Point, 4326),
          geocode   jsonb   NOT NULL DEFAULT '{}'::jsonb,
          CONSTRAINT fire_stations_identity UNIQUE (district, name)
        )
        """
    )
    # location is nullable on purpose: a published address like "צומת האלה" has
    # no street and no locality, and a NULL is honest where a guessed centroid
    # would silently become a dispatch origin. geocode carries the provider's
    # status, confidence and matched text so an unresolved or coarse row is
    # visible to whatever reads this table.
    op.execute("CREATE INDEX fire_stations_location_idx ON fire_stations USING GIST (location)")


def downgrade() -> None:
    """Remove fire_stations."""
    op.execute("DROP TABLE IF EXISTS fire_stations")
