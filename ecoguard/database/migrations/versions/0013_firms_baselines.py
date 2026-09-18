"""firms_baselines — how often each cell lights up, so a fire can be told from a furnace

Revision ID: firms_baselines
Revises: incidents
Create Date: 2026-09-16

Non-numeric identifier for the same reason as the four before it: sibling
branches claim numeric ids and alembic resolves stored revisions by prefix.
"""

from alembic import op

revision = "firms_baselines"
down_revision = "incidents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A satellite hotspot has no magnitude to place on a distribution. It is a
    # yes, and the only sensible baseline is how often this cell says yes —
    # which is what `rarity_from_rate` in shared/signals.py was written for and
    # has had nothing to read until now.
    #
    # The distinction it buys is not subtle. One cell in the Rishon LeZion
    # industrial belt has lit on eight days out of ten, every single time
    # between 22:52 and 00:33, always at 0.5-2.0 MW: a fixed installation on a
    # night shift. Without this table it opens an incident every night forever,
    # and an emergency queue that cries wolf nightly is worse than no queue,
    # because people learn to skim it.
    #
    # `days_observed` is stored per row even though the backfill covers every
    # cell over the same window. It makes a rate self-contained — a reader
    # never has to know how the table was built to divide two numbers — and it
    # survives a later backfill that extends some cells and not others.
    #
    # Unlike weather_baselines this is complete by construction. FIRMS is
    # fetched as one bounding box covering the whole service area, so a cell
    # with no fires gets a row saying zero rather than no row at all. "Never
    # lights up" and "never checked" are different facts, and the first is the
    # strongest evidence this table holds.
    op.execute(
        """
        CREATE TABLE firms_baselines (
          cell_id        text    PRIMARY KEY,
          days_observed  integer NOT NULL,
          detection_days integer NOT NULL,
          detections     integer NOT NULL,
          peak_frp_mw    real,
          window_start   date    NOT NULL,
          window_end     date    NOT NULL,
          built_at       timestamptz NOT NULL DEFAULT now(),

          CONSTRAINT firms_baselines_days_sane
            CHECK (days_observed > 0 AND detection_days BETWEEN 0 AND days_observed)
        )
        """
    )
    # The only read is by cell_id, which the primary key already serves. No
    # further index: one "for lookups by rate" would duplicate a full scan of
    # a table with one row per cell.


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS firms_baselines")
