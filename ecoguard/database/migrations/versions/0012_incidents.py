"""incidents — one row per thing that is happening, however many times it is seen

Revision ID: incidents
Revises: weather_baselines
Create Date: 2026-09-14

Non-numeric identifier for the same reason as the three before it: sibling
branches claim numeric ids and alembic resolves stored revisions by prefix.
"""

from alembic import op

revision = "incidents"
down_revision = "weather_baselines"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add incidents — one row per thing that is happening, however many times it is seen."""
    # The first table in this system with a lifecycle. Everything else records
    # what arrived; this records what is *going on*, which means a row here
    # changes over time while an observation never does.
    #
    # It exists because detectors have no memory. A raging fire produces a
    # FIRMS hotspot every thirty minutes, a dozen Telegram messages and an
    # hourly weather anomaly, all describing one thing — and without somewhere
    # to write down "we already know about this", every one of them becomes a
    # fresh event and the same fire is analysed forty times.
    #
    # `hazards` is an array rather than a single column because a fire and the
    # air pollution downwind of it are one incident, not two. That is the
    # hybrid case: one id, several hazards, and `queues` then carrying both
    # `emergency` (send the brigade) and `non_emergency` (warn the towns
    # downwind). Two audiences, two actions, one event.
    #
    # `cells` is an array because an incident grows. A fire on a cell boundary
    # lights pixels either side, and a plume crosses several cells on its way
    # downwind; the incident owns every cell it has been seen in, which is what
    # lets the next signal find it.
    #
    # `status` is free text with two values and no CHECK constraint, following
    # collector_runs — the only other lifecycle here. A constraint would have to
    # be migrated every time a state is added, and the states are not settled.
    op.execute(
        """
        CREATE TABLE incidents (
          id              text        PRIMARY KEY,
          status          text        NOT NULL,
          primary_hazard  text        NOT NULL,
          hazards         text[]      NOT NULL,
          queues          text[]      NOT NULL,
          cells           text[]      NOT NULL,

          latitude        double precision,
          longitude       double precision,
          precision_m     real,
          location_method text,

          first_seen_at   timestamptz NOT NULL,
          last_signal_at  timestamptz NOT NULL,
          closed_at       timestamptz,

          signal_count    integer     NOT NULL,
          peak_rarity     real,

          links           jsonb       NOT NULL DEFAULT '[]'::jsonb,
          signals         jsonb       NOT NULL DEFAULT '[]'::jsonb
        )
        """
    )

    # Location is nullable on purpose and carries its own precision. A
    # satellite pixel is good to 375 m and a Telegram report naming only a town
    # is good to two kilometres; storing a bare lat/lon would make those look
    # identical, and an operator would read the second as a confident fix.
    # NULL means no point at all is known and the cells are the location.

    # The two reads this table actually gets. Everything else is by primary key.
    op.execute(
        "CREATE INDEX incidents_open_idx ON incidents (status, last_signal_at DESC)"
    )
    # GIN because the dedup question is "which open incident already contains
    # this cell", which is array containment and not a b-tree lookup.
    op.execute("CREATE INDEX incidents_cells_idx ON incidents USING GIN (cells)")


def downgrade() -> None:
    """Remove incidents — one row per thing that is happening, however many times it is seen."""
    op.execute("DROP INDEX IF EXISTS incidents_cells_idx")
    op.execute("DROP INDEX IF EXISTS incidents_open_idx")
    op.execute("DROP TABLE IF EXISTS incidents")
