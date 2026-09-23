"""population_cells

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-10
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add population_cells."""
    # One row per raster pixel of a population-count grid, as the pixel's own
    # footprint rather than its centre. That is what makes a drawn polygon
    # answerable: a cell only half inside the polygon contributes half its
    # people, so the total does not jump by a whole cell as the user nudges an
    # edge. Counting centroids instead is a cell-sized error on any polygon
    # near the grid's own resolution, which is most of what gets drawn.
    #
    # geometry, not geography: the only thing asked of these cells is the ratio
    # ST_Area(intersection) / ST_Area(cell). Both sides carry the same planar
    # distortion across one 100 m cell, so the ratio is exact and costs none of
    # geography's spheroid arithmetic. The polygon's own reported area is
    # measured in geography, where it matters.
    op.execute(
        """
        CREATE TABLE population_cells (
          id          bigserial PRIMARY KEY,
          cell        geometry(Polygon, 4326) NOT NULL,
          population  double precision NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX population_cells_cell_idx ON population_cells USING GIST (cell)")


def downgrade() -> None:
    """Remove population_cells."""
    op.execute("DROP TABLE IF EXISTS population_cells")
