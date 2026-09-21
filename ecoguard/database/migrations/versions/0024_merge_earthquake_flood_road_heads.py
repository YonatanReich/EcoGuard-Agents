"""Rejoin the earthquake allocation policy and flood road segment branches.

Revision ID: earthquake_flood_road_merge
Revises: earthquake_allocation_policy, flood_road_segments
Create Date: 2026-09-21

Both branches were cut from flood_incident_lifecycle and merged to main
independently -- earthquake allocation policy with PR #42, flood road segments
earlier by way of police_station_responsibility. Neither touches the other's
tables, so nothing here has to reconcile schema.

What it does reconcile is the graph. Two revisions sharing a parent leave
Alembic with two heads, and `upgrade head` then refuses to run at all rather
than guessing an order. The columns earthquake allocation writes --
allocation_policy, allocation_basis, quantity_source on resource_allocations --
were therefore unreachable on every database, which surfaced as
UndefinedColumn in the resource allocation and lock tests rather than as a
migration error, because nobody was able to migrate in the first place.

Worth noting for the next merge: a split head produces no git conflict. Each
branch adds its own file and git takes both cleanly; only the revision graph
disagrees. Checking `alembic heads` after merging a branch that carries a
migration is the cheap way to catch it.
"""

revision = "earthquake_flood_road_merge"
down_revision = ("earthquake_allocation_policy", "flood_road_segments")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Nothing to do: this revision only joins migration histories."""


def downgrade() -> None:
    """Nothing to undo."""
