"""observations.issued_at — the second time axis a forecast needs

Revision ID: observation_issued_at
Revises: surface_cells
Create Date: 2026-09-12

Non-numeric identifier for the same reason as surface_cells: sibling branches
claim "0009"/"0010" and alembic resolves stored revisions by prefix, so a
numeric id here could silently match theirs and turn `upgrade head` into a
no-op that reports success.
"""

from alembic import op

revision = "observation_issued_at"
down_revision = "surface_cells"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A measurement has one time: when it was taken. A forecast has two: when
    # it is *for*, and when it was *made*. The same hour is predicted over and
    # over as the run it came from gets newer, and those predictions disagree —
    # that disagreement is the useful part, because it is how you see a
    # forecast deteriorating toward a bad afternoon.
    #
    # observed_at keeps its meaning as "the hour this describes", so every
    # existing query keeps working unchanged and a forecast row lines up with
    # the observation of the same hour once that hour arrives. issued_at is the
    # run that produced it, and NULL means "nobody produced this, it was
    # measured" — which is precisely the distinction the weather collector's
    # docstring said a shared table could not make.
    op.execute("ALTER TABLE observations ADD COLUMN issued_at timestamptz")

    # NULLS NOT DISTINCT is what lets one table hold both. Under the default
    # rule two NULL issued_at rows count as different, so every re-fetch of an
    # observation would insert a duplicate instead of conflicting — silently
    # undoing the idempotency the whole collection layer depends on.
    #
    # Postgres 15 introduced it and this database is on 18, so the alternative
    # (a sentinel timestamp standing in for "measured") is not needed.
    op.execute("ALTER TABLE observations DROP CONSTRAINT observations_identity")
    op.execute(
        """
        ALTER TABLE observations
        ADD CONSTRAINT observations_identity
        UNIQUE NULLS NOT DISTINCT (source, cell_id, observed_at, issued_at)
        """
    )

    # Reading a forecast means "the newest run that covers this hour", which is
    # a descending scan on issued_at within one cell and hour. The unique
    # constraint's own index ascends, so it can serve the lookup but not the
    # ordering; this one costs a few MB and makes the common read a single
    # backwards index scan.
    op.execute(
        """
        CREATE INDEX observations_forecast_idx
        ON observations (source, cell_id, observed_at, issued_at DESC)
        WHERE issued_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS observations_forecast_idx")
    op.execute("ALTER TABLE observations DROP CONSTRAINT observations_identity")
    op.execute("DELETE FROM observations WHERE issued_at IS NOT NULL")
    op.execute(
        """
        ALTER TABLE observations
        ADD CONSTRAINT observations_identity
        UNIQUE (source, cell_id, observed_at)
        """
    )
    op.execute("ALTER TABLE observations DROP COLUMN issued_at")
