"""add explicit air pollution baseline family

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-13
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preserve every profile ID and all dependent versions/buckets. The only
    # existing artifacts are the audited national-v2 completed-hour profiles.
    op.execute("""
        ALTER TABLE air_pollution_baseline_profiles
        ADD COLUMN baseline_family text
    """)
    op.execute("""
        UPDATE air_pollution_baseline_profiles
        SET baseline_family = 'completed_hour'
        WHERE baseline_family IS NULL
    """)
    op.execute("""
        ALTER TABLE air_pollution_baseline_profiles
        ADD CONSTRAINT air_pollution_baseline_profiles_family_ck
        CHECK (baseline_family IN ('completed_hour', 'five_minute_observation'))
    """)
    op.execute("""
        ALTER TABLE air_pollution_baseline_profiles
        ALTER COLUMN baseline_family SET NOT NULL
    """)
    op.execute("""
        ALTER TABLE air_pollution_baseline_profiles
        ADD CONSTRAINT air_pollution_baseline_profiles_identity_family
        UNIQUE (provider, station_id, channel_id, pollutant, canonical_unit, baseline_family)
    """)
    op.execute("""
        ALTER TABLE air_pollution_baseline_profiles
        DROP CONSTRAINT air_pollution_baseline_profiles_identity
    """)


def downgrade() -> None:
    # Once two families coexist, removing the dimension may create duplicate
    # five-column identities and destroy scientific provenance.
    raise RuntimeError(
        "0010 is data-preserving forward-only; baseline-family removal requires explicit review"
    )
