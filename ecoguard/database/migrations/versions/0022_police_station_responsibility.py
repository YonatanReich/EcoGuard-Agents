"""Connect towns to their responsible police stations.

Revision ID: police_station_responsibility
Revises: flood_incident_lifecycle
Create Date: 2026-09-19
"""

import csv

from alembic import op
from sqlalchemy import text

from ecoguard.paths import REFERENCE


revision = "police_station_responsibility"
down_revision = "flood_incident_lifecycle"
branch_labels = None
depends_on = None


CROSSWALK_PATH = (
    REFERENCE / "Town info" / "police_station_crosswalk.csv"
)


def upgrade() -> None:
    """Add connect towns to their responsible police stations."""
    # A town can be served by several stations, and one station serves many
    # towns. Keep that relationship normalized instead of storing DB keys in
    # a comma-separated or array column on towns.
    op.execute(
        """
        CREATE TABLE town_police_stations (
          town_id             text   NOT NULL
                                    REFERENCES towns(town_id) ON DELETE CASCADE,
          police_station_id   bigint NOT NULL
                                    REFERENCES police_stations(id),
          source_station_name text   NOT NULL,
          match_method        text   NOT NULL,
          match_confidence    real   NOT NULL,
          PRIMARY KEY (town_id, police_station_id),
          CONSTRAINT town_police_station_confidence CHECK (
            match_confidence >= 0 AND match_confidence <= 1
          )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX town_police_stations_station_idx
        ON town_police_stations (police_station_id)
        """
    )

    if CROSSWALK_PATH.exists():
        connection = op.get_bind()
        with CROSSWALK_PATH.open(encoding="utf-8-sig", newline="") as source:
            for row in csv.DictReader(source):
                published_station_id = row.get("police_station_id")
                if not published_station_id:
                    # Unresolved names deliberately use the runtime nearest-
                    # station fallback instead of inventing responsibility.
                    continue
                connection.execute(
                    text(
                        """
                        INSERT INTO town_police_stations (
                          town_id,
                          police_station_id,
                          source_station_name,
                          match_method,
                          match_confidence
                        )
                        SELECT
                          town.town_id,
                          station.id,
                          :source_station_name,
                          :match_method,
                          :match_confidence
                        FROM towns AS town
                        JOIN police_stations AS station
                          ON station.station_id = :published_station_id
                        WHERE :source_station_name = ANY(
                          string_to_array(town.police_station, ', ')
                        )
                        ON CONFLICT (town_id, police_station_id) DO NOTHING
                        """
                    ),
                    {
                        "source_station_name": row["towns_station_name"],
                        "match_method": row["match_method"],
                        "match_confidence": float(row["match_confidence"]),
                        "published_station_id": int(published_station_id),
                    },
                )

    # Police allocation assigns organisational responsibility, not a single
    # vehicle. A station may therefore receive several incidents, while the
    # same incident/station pair remains idempotent across retries.
    op.execute(
        "DROP INDEX IF EXISTS resource_allocations_active_police_idx"
    )
    op.execute(
        """
        CREATE UNIQUE INDEX resource_allocations_active_incident_police_idx
        ON resource_allocations (incident_id, police_station_id)
        WHERE released_at IS NULL AND police_station_id IS NOT NULL
        """
    )


def downgrade() -> None:
    """Remove connect towns to their responsible police stations."""
    op.execute(
        "DROP INDEX IF EXISTS resource_allocations_active_incident_police_idx"
    )
    op.execute(
        """
        CREATE UNIQUE INDEX resource_allocations_active_police_idx
        ON resource_allocations (police_station_id)
        WHERE released_at IS NULL AND police_station_id IS NOT NULL
        """
    )
    op.execute("DROP TABLE IF EXISTS town_police_stations")
