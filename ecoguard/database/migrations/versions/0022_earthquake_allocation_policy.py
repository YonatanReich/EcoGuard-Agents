"""Allow policy-driven Earthquake resource allocations.

Revision ID: earthquake_allocation_policy
Revises: flood_incident_lifecycle
Create Date: 2026-09-20
"""

from alembic import op


revision = "earthquake_allocation_policy"
down_revision = "flood_incident_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Allow earthquake allocations to be driven by policy."""
    op.execute(
        """
        ALTER TABLE resource_allocations
          ALTER COLUMN risk_score DROP NOT NULL,
          ALTER COLUMN risk_level DROP NOT NULL,
          ADD COLUMN allocation_policy text,
          ADD COLUMN allocation_basis text,
          ADD COLUMN quantity_source text;

        ALTER TABLE resource_allocations
          ADD CONSTRAINT resource_allocations_basis_check CHECK (
            (
              risk_score IS NOT NULL
              AND risk_level IS NOT NULL
              AND allocation_policy IS NULL
              AND allocation_basis IS NULL
              AND quantity_source IS NULL
            )
            OR
            (
              risk_score IS NULL
              AND risk_level IS NULL
              AND allocation_policy = 'earthquake_minimum_response_v1'
              AND allocation_basis = 'protocol_recommended_units'
              AND quantity_source = 'ecoguard_minimum_response_policy'
            )
          );
        """
    )


def downgrade() -> None:
    """Remove policy-driven earthquake allocations."""
    op.execute(
        """
        DELETE FROM resource_allocations WHERE allocation_policy IS NOT NULL;
        ALTER TABLE resource_allocations
          DROP CONSTRAINT resource_allocations_basis_check,
          DROP COLUMN quantity_source,
          DROP COLUMN allocation_basis,
          DROP COLUMN allocation_policy,
          ALTER COLUMN risk_level SET NOT NULL,
          ALTER COLUMN risk_score SET NOT NULL;
        """
    )
