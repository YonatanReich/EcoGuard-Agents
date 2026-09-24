"""Persist the one-police-station fallback when planning is unavailable.

Revision ID: planning_failure_police
Revises: text_candidate_triage
Create Date: 2026-09-24
"""

from alembic import op


revision = "planning_failure_police"
down_revision = "text_candidate_triage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Allow the explicit planning-failure policy with analyzed risk."""
    op.execute(
        """
        ALTER TABLE resource_allocations
          DROP CONSTRAINT resource_allocations_basis_check;

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
              risk_score IS NOT NULL
              AND risk_level IS NOT NULL
              AND allocation_policy = 'earthquake_minimum_response_v1'
              AND allocation_basis = 'protocol_recommended_units'
              AND quantity_source = 'ecoguard_minimum_response_policy'
            )
            OR
            (
              risk_score IS NOT NULL
              AND risk_level IS NOT NULL
              AND allocation_policy = 'planning_failure_police_minimum_v1'
              AND allocation_basis = 'planner_unavailable_emergency_minimum'
              AND quantity_source = 'ecoguard_fallback_policy'
            )
          );
        """
    )


def downgrade() -> None:
    """Remove fallback-policy rows and restore the previous constraint."""
    op.execute(
        """
        DELETE FROM resource_allocations
        WHERE allocation_policy = 'planning_failure_police_minimum_v1';

        ALTER TABLE resource_allocations
          DROP CONSTRAINT resource_allocations_basis_check;

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
