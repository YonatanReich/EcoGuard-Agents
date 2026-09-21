"""Reports nobody has corroborated yet, kept apart from incidents.

Revision ID: weak_events
Revises: text_candidates
Create Date: 2026-09-21

An incident means "this is happening". A weak event means "somebody unofficial
said this is happening and nothing else agrees yet". Putting the second in the
incidents table behind a flag would mean every consumer that currently reads an
incident — the analyser, the planner, the allocator, the map — has to learn the
flag, and the one that forgets dispatches an engine to a rumour.

So they live here, and a weak event that earns corroboration is *promoted*: it
emits a signal like any detector and the coordinator makes it an incident
through the ordinary path. Nothing downstream needs to know it was ever weak.

Statuses:
  open         reported, waiting for corroboration, on the operator's map
  promoted     corroborated; `incident_id` is the incident it became
  unconfirmed  the window expired with nothing agreeing. Not deleted: a
               channel whose reports are never corroborated is a channel to
               drop, and that is measurable only if the misses are kept.
  dismissed    an operator said no
  confirmed    an operator said yes, which counts as an official source
"""

from alembic import op


revision = "weak_events"
down_revision = "text_candidates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE weak_events (
          id             text PRIMARY KEY,
          hazard         text NOT NULL,
          status         text NOT NULL DEFAULT 'open',

          cell_id        text,
          latitude       double precision,
          longitude      double precision,
          -- How loosely the place is known. A town outline gives kilometres,
          -- a street gives hundreds of metres, and the corroboration radius is
          -- built from this rather than from a fixed number.
          precision_m    real,
          location_text  text,

          first_seen_at  timestamptz NOT NULL,
          last_seen_at   timestamptz NOT NULL,
          expires_at     timestamptz NOT NULL,
          resolved_at    timestamptz,

          -- Every report backing this, each with its origin key. The key is
          -- what makes "two independent reports" countable: ten channels
          -- forwarding one message share an origin and count once.
          reports        jsonb NOT NULL DEFAULT '[]'::jsonb,
          -- Why it was promoted, or why it expired. An operator asking "why is
          -- this on my map" gets an answer without a log search.
          resolution     text,
          incident_id    text,

          confirmed_by   text,
          confirmed_at   timestamptz,

          CONSTRAINT weak_events_hazard CHECK (
            hazard IN ('fire', 'flood', 'earthquake', 'air_quality')
          ),
          CONSTRAINT weak_events_status CHECK (
            status IN ('open', 'promoted', 'unconfirmed', 'dismissed', 'confirmed')
          )
        )
        """
    )
    op.execute(
        "CREATE INDEX weak_events_open ON weak_events (hazard, last_seen_at DESC) "
        "WHERE status = 'open'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE weak_events")
