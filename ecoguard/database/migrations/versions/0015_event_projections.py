"""Generic durable SharedEvent projections keyed by Coordinator incident.

Revision ID: event_projections
Revises: air_pollution_firms_merge
Create Date: 2026-09-16
"""

from alembic import op

revision = "event_projections"
down_revision = "air_pollution_firms_merge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE event_projections (
          incident_id                  text        PRIMARY KEY
                                                   REFERENCES incidents(id)
                                                   ON DELETE CASCADE,
          hazard                       text        NOT NULL,
          route                        text        NOT NULL,
          processing_status            text        NOT NULL,
          analysis_status              text,
          planner_status               text,
          analysis_id                  text,
          coordinator_routing_id       text,
          handler                      text,
          event_payload                jsonb,
          last_successful_event_payload jsonb,
          failure_stage                text,
          failure_reason               text,
          retryable                    boolean     NOT NULL DEFAULT false,
          attempt_count                integer     NOT NULL DEFAULT 1,
          last_attempt_at              timestamptz NOT NULL,
          last_success_at              timestamptz,
          processed_at                 timestamptz NOT NULL,
          created_at                   timestamptz NOT NULL DEFAULT now(),
          updated_at                   timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX event_projections_delivery_idx "
        "ON event_projections (updated_at DESC) WHERE event_payload IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX event_projections_retry_idx "
        "ON event_projections (last_attempt_at) WHERE retryable"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS event_projections_retry_idx")
    op.execute("DROP INDEX IF EXISTS event_projections_delivery_idx")
    op.execute("DROP TABLE IF EXISTS event_projections")
