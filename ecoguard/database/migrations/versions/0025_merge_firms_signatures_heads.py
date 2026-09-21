"""Rejoin the FIRMS signature branch with main's migration history.

Revision ID: firms_signatures_merge
Revises: firms_signatures, earthquake_flood_road_merge
Create Date: 2026-09-21

firms_signatures was cut from event_projections_towns_merge while the fire
pipeline branch developed, and main has since advanced through flood road
segments, police station responsibility and earthquake allocation policy.
Neither side touches the other's tables: firms_signatures adds per-cell
novelty columns to firms_baselines, and nothing on main reads them.

This exists for the same reason 0024 did, one merge earlier. Two revisions
sharing no ancestor leave Alembic with two heads, and `upgrade head` then
refuses to run rather than choosing an order -- which surfaces as missing
columns in unrelated tests rather than as a migration failure, because
nobody gets far enough to see a migration failure.

A split head produces no git conflict: each branch adds its own file and git
takes both cleanly, so only `alembic heads` reveals it.
"""

revision = "firms_signatures_merge"
down_revision = ("firms_signatures", "earthquake_flood_road_merge")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Nothing to do: this revision only joins migration histories."""


def downgrade() -> None:
    """Nothing to undo."""
