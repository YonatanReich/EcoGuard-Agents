"""SQLAlchemy engine and session factory for the EcoGuard Postgres store.

DATABASE_URL is read once, at import, so a missing or malformed connection
string fails when the process starts rather than on the first query inside a
scheduled collector run — where it would surface only as a `failed` row.

A proper pydantic-settings module replaces this later; for now it follows the
python-dotenv pattern already used across the repository.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Add it to .env, for example "
        "postgresql+psycopg://user:password@host/dbname?sslmode=require "
        "(see .env.example)."
    )

# create_engine does not connect, so an unreachable host is discovered on first
# use. pool_pre_ping discards connections a hosted Postgres has already closed,
# which a worker sleeping thirty minutes between ticks will meet constantly.
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)

Session = sessionmaker(bind=engine, expire_on_commit=False)
