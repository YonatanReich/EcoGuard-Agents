"""weather_baselines — what normal looks like, per cell, per month, per hour

Revision ID: weather_baselines
Revises: observation_issued_at
Create Date: 2026-09-13

Non-numeric identifier for the same reason as the two before it: sibling
branches claim numeric ids and alembic resolves stored revisions by prefix.
"""

from alembic import op

revision = "weather_baselines"
down_revision = "observation_issued_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A table rather than more rows in observations, because this is not an
    # observation. Every other row in that table answers "what happened at this
    # place at this moment"; a row here answers "what usually happens at this
    # place in this month at this hour", which has no moment at all — it is a
    # distribution over many years collapsed into one bucket.
    #
    # It is also the missing denominator. Without it "anomalous" can only mean
    # "different from the trailing week", and the trailing week is contaminated
    # by whatever is happening — a heatwave that builds over six days never
    # looks unusual on any single one of them, and by day ten of a khamsin the
    # khamsin *is* the baseline. Those are exactly the slow, persistent
    # conditions that matter most for fire.
    #
    # Bucketing is month x hour, not month alone: 35 C at 14:00 in August is
    # ordinary and 35 C at 04:00 in August is extraordinary, and a month-only
    # bucket averages those into one meaningless number. Twelve months by
    # twenty-four hours is 288 buckets per cell per variable, each holding
    # roughly three hundred samples from ten years — enough for a p95 to mean
    # something.
    #
    # Both classical and robust statistics are stored. mean/std are familiar
    # and right for temperature; median/MAD survive the skew in precipitation
    # and wind, where a handful of storm hours drag a mean somewhere no actual
    # hour ever sat. The read side prefers the robust pair and falls back to
    # percentiles when MAD is zero, which is the normal state of precipitation.
    op.execute(
        """
        CREATE TABLE weather_baselines (
          cell_id   text     NOT NULL,
          variable  text     NOT NULL,
          month     smallint NOT NULL CHECK (month BETWEEN 1 AND 12),
          hour      smallint NOT NULL CHECK (hour BETWEEN 0 AND 23),
          samples   integer  NOT NULL,
          mean      real     NOT NULL,
          std       real     NOT NULL,
          median    real     NOT NULL,
          mad       real     NOT NULL,
          p05       real     NOT NULL,
          p25       real     NOT NULL,
          p75       real     NOT NULL,
          p95       real     NOT NULL,
          minimum   real     NOT NULL,
          maximum   real     NOT NULL,
          PRIMARY KEY (cell_id, variable, month, hour)
        )
        """
    )
    # The primary key already serves the only read there is — one bucket, by
    # all four of its coordinates — so no further index is created. Adding one
    # "for lookups by cell" would duplicate the key's own leading column.


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS weather_baselines")
