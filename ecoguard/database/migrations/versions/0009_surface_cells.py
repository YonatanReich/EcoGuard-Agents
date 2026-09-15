"""surface_cells

Revision ID: surface_cells
Revises: 0008
Create Date: 2026-09-12

The identifier is deliberately not a number. Two sibling branches already
claim "0009" (the hydrology layers and the air-pollution catalog), and alembic
resolves a stored revision by *prefix*: a database stamped "0009" by either of
them matches a revision called "0009_surface" and `alembic upgrade head` then
reports success having done nothing at all. A non-numeric id cannot be
mistaken for theirs, so the same database fails loudly and asks for the
`alembic merge` those three heads need anyway.
"""

from alembic import op

revision = "surface_cells"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The static ground, on the same footprint-per-cell pattern as
    # population_cells and for the same reason: a fire polygon half over a
    # ridge should read half the ridge, and a cell-sized step in the answer as
    # the operator nudges an edge is worse than a slightly blurred one.
    #
    # Shape and cover share one table because they share one grid. Splitting
    # them would duplicate the polygon and its GiST index — together about 90%
    # of this table's size — to store nine floats that describe the same ground
    # as the row already there. Every caller wants both at once anyway: slope
    # says how fast a fire moves, cover says whether there is anything to burn,
    # and neither is an answer on its own.
    #
    # Three slope columns rather than one, because they answer different
    # questions. slope_deg is what the cell mostly is; slope_max_deg is the
    # steepest ground inside it, which is where a fire accelerates and what an
    # average over a 270 m cell hides. Storing only the mean would flatten
    # every gully in the country.
    #
    # aspect_deg is nullable on purpose: flat ground faces no direction, and a
    # NULL says that where 0 would claim "due north".
    #
    # The cover columns are *fractions of the cell*, not a single class. At
    # 270 m a cell holds some nine hundred 10 m WorldCover pixels and is almost
    # never pure; the mixture is the point. A cell that is half shrub and a
    # third built-up is the wildland-urban interface, and calling it
    # "shrubland" throws away the half of the description that decides who is
    # in danger. The dominant class is still one greatest() away.
    #
    # unmapped is the honest remainder: nodata, and the three WorldCover
    # classes Israel has none of (snow/ice, mangroves, moss/lichen), which are
    # not given columns of zeroes. The nine fractions sum to 1, so a cell that
    # starts reading mostly-unmapped is visibly wrong rather than quietly short.
    #
    # real, not double precision: GLO-90 is accurate to a few metres, the
    # derived angles to a fraction of a degree, and a fraction of nine hundred
    # pixels to about a thousandth. float8 would double the table to store
    # digits no source ever had.
    op.execute(
        """
        CREATE TABLE surface_cells (
          id                        bigserial PRIMARY KEY,
          cell                      geometry(Polygon, 4326) NOT NULL,

          elevation_m               real NOT NULL,
          slope_deg                 real NOT NULL,
          slope_max_deg             real NOT NULL,
          aspect_deg                real,

          tree_cover                real NOT NULL,
          shrubland                 real NOT NULL,
          grassland                 real NOT NULL,
          cropland                  real NOT NULL,
          built_up                  real NOT NULL,
          bare_sparse_vegetation    real NOT NULL,
          permanent_water           real NOT NULL,
          herbaceous_wetland        real NOT NULL,
          unmapped                  real NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX surface_cells_cell_idx ON surface_cells USING GIST (cell)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS surface_cells")
