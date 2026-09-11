"""Alembic environment. Online mode only — there is no offline SQL workflow."""

from __future__ import annotations

from alembic import context

from ecoguard.database.engine import engine
from ecoguard.database.models import Base

target_metadata = Base.metadata


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # PostGIS and pgvector install their own tables and types into the
            # database; without this, autogenerate proposes dropping them.
            include_schemas=False,
            include_object=lambda obj, name, type_, reflected, compare_to: not (
                type_ == "table" and name in {"spatial_ref_sys", "geography_columns", "geometry_columns"}
            ),
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
