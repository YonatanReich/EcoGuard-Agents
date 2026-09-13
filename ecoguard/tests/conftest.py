"""Test-wide setup for the collection layer.

ecoguard.database.engine raises at import when DATABASE_URL is missing, which
is the behaviour we want in production but would stop the parse-only tests from
even importing. A placeholder is enough for those: create_engine does not
connect. Tests that need a real database ask for the `database` fixture and
skip when nothing answers.
"""

import os
import socket

import pytest
from dotenv import load_dotenv

# .env first. load_dotenv does not overwrite variables that are already set, so
# seeding the placeholder before this line would silently pin every test to
# localhost and skip the whole database suite even with a real DATABASE_URL
# configured.
load_dotenv()

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://ecoguard:ecoguard@localhost:5432/ecoguard"
)

PROBE_TIMEOUT_SECONDS = 2.0


@pytest.fixture(scope="session")
def database():
    """Skip the test unless a Postgres with our tables is actually reachable."""
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    from ecoguard.database.engine import DATABASE_URL, engine

    # A TCP probe first: psycopg's own connect timeout defaults to minutes, so
    # without this every run on a machine with no database pays it before the
    # skip.
    url = make_url(DATABASE_URL)
    try:
        socket.create_connection(
            (url.host or "localhost", url.port or 5432), timeout=PROBE_TIMEOUT_SECONDS
        ).close()
    except OSError as error:
        pytest.skip(f"no Postgres listening at {url.host}:{url.port or 5432} ({error})")

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1 FROM observations LIMIT 1"))
            connection.execute(text("SELECT postgis_version()"))
    except Exception as error:
        pytest.skip(f"database at DATABASE_URL is not migrated: {type(error).__name__}")
    return engine
