"""Durable emergency-station allocations.

Revision ID: resource_allocations
Revises: event_projections
Create Date: 2026-09-17
"""

from alembic import op

revision = "resource_allocations"
down_revision = "event_projections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE resource_allocations (
          id                 bigserial        PRIMARY KEY,
          incident_id        text             NOT NULL
                                               REFERENCES incidents(id),
          fire_station_id    bigint           REFERENCES fire_stations(id),
          police_station_id  bigint           REFERENCES police_stations(id),
          mda_station_id     bigint           REFERENCES mda_stations(id),
          allocated_at       timestamptz      NOT NULL DEFAULT now(),
          released_at        timestamptz,
          release_reason     text,
          distance_km        double precision NOT NULL,
          risk_score         real             NOT NULL,
          risk_level         text             NOT NULL,

          CONSTRAINT resource_allocations_one_station CHECK (
            num_nonnulls(
              fire_station_id,
              police_station_id,
              mda_station_id
            ) = 1
          ),
          CONSTRAINT resource_allocations_distance CHECK (distance_km >= 0),
          CONSTRAINT resource_allocations_risk_score CHECK (
            risk_score >= 0 AND risk_score <= 100
          ),
          CONSTRAINT resource_allocations_release_time CHECK (
            released_at IS NULL OR released_at >= allocated_at
          )
        )
        """
    )

    # A partial unique index is the database-level no-double-assignment rule.
    op.execute(
        """
        CREATE UNIQUE INDEX resource_allocations_active_fire_idx
        ON resource_allocations (fire_station_id)
        WHERE released_at IS NULL AND fire_station_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX resource_allocations_active_police_idx
        ON resource_allocations (police_station_id)
        WHERE released_at IS NULL AND police_station_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX resource_allocations_active_mda_idx
        ON resource_allocations (mda_station_id)
        WHERE released_at IS NULL AND mda_station_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX resource_allocations_active_incident_idx
        ON resource_allocations (incident_id)
        WHERE released_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS resource_allocations")
