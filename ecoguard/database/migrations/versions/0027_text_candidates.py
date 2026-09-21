"""What the classifier decided about one message, for one hazard.

Revision ID: text_candidates
Revises: text_sources
Create Date: 2026-09-21

A candidate is not a signal and not an event. It is a labelled claim extracted
from text that nobody has corroborated yet, and it is kept apart from
`observations` (which stores what a source said, verbatim and unjudged) and
from the incident pipeline (which is for things believed to be happening).

One row per message per hazard, rather than one row with a hazard array. Every
question triage asks is per hazard — "two distinct origins reporting *flood*
near here within two hours" — and an array turns each of those into an
unnest before it can be a join.

Tier is deliberately absent. It is read through `source_id` from
`text_sources` at the moment it is needed, so a channel corrected from
authority to unofficial does not leave a thousand rows asserting the old tier.
"""

from alembic import op


revision = "text_candidates"
down_revision = "text_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE text_candidates (
          id               bigserial PRIMARY KEY,
          observation_id   bigint NOT NULL
                             REFERENCES observations (id) ON DELETE CASCADE,
          source_id        text NOT NULL REFERENCES text_sources (source_id),
          hazard           text NOT NULL,

          -- The classifier's judgement. `relevant` and `literal` are kept
          -- apart because they fail differently: a metaphor is relevant and
          -- not literal, a weather forecast is literal and not a report of
          -- something happening.
          relevant         boolean NOT NULL,
          literal          boolean NOT NULL,
          -- A real earthquake 12,000 km away passes every other test here.
          in_israel        boolean NOT NULL,
          update_type      text NOT NULL DEFAULT 'none',

          -- As written in the message. Geocoding happens downstream, against
          -- the service-area grid, and storing the text keeps the extraction
          -- arguable after the fact.
          location_text    text,
          claim            text,
          details          jsonb NOT NULL DEFAULT '{}'::jsonb,

          -- Which path produced this row. `keywords` means the model call
          -- failed and the safety net caught it; those rows are weaker
          -- evidence and must stay distinguishable rather than blending in.
          classified_by    text NOT NULL,
          model_version    text,
          keyword_matched  boolean NOT NULL DEFAULT false,

          -- The message's own time, copied because every triage query filters
          -- on it and the alternative is joining observations for a window
          -- check that runs on every candidate.
          observed_at      timestamptz NOT NULL,
          created_at       timestamptz NOT NULL DEFAULT now(),

          CONSTRAINT text_candidates_hazard CHECK (
            hazard IN ('fire', 'flood', 'earthquake', 'air_quality')
          ),
          CONSTRAINT text_candidates_update_type CHECK (
            update_type IN ('new', 'update', 'contained', 'false_alarm', 'none')
          ),
          CONSTRAINT text_candidates_classified_by CHECK (
            classified_by IN ('model', 'keywords')
          ),
          -- Re-running the classifier over a message must correct the row it
          -- wrote last time, not add a second opinion beside it.
          CONSTRAINT text_candidates_identity UNIQUE (observation_id, hazard)
        )
        """
    )
    # The triage query: reportable candidates for one hazard in a time window.
    op.execute(
        """
        CREATE INDEX text_candidates_triage
          ON text_candidates (hazard, observed_at DESC)
          WHERE relevant AND literal AND in_israel
        """
    )
    op.execute(
        "CREATE INDEX text_candidates_source ON text_candidates (source_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE text_candidates")
