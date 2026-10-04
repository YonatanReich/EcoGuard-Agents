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

# An explicit test database wins over whatever .env configured, and is set into
# the environment here rather than passed around because
# `ecoguard.database.engine` builds its engine from DATABASE_URL at import time
# and some test modules import it during collection — which happens after this
# module is executed, and only after.
TEST_DATABASE_URL_VARIABLE = "ECOGUARD_TEST_DATABASE_URL"

_test_database_url = os.environ.get(TEST_DATABASE_URL_VARIABLE)
if _test_database_url:
    os.environ["DATABASE_URL"] = _test_database_url

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://ecoguard:ecoguard@localhost:5432/ecoguard"
)

PROBE_TIMEOUT_SECONDS = 2.0

# Where a database may be emptied. The destructive fixtures are not subtle —
# `clean` in test_coordinator.py runs `DELETE FROM incidents` on setup and again
# on teardown — and every one of them depends on the `database` fixture below,
# so this is the only place that has to refuse.
#
# It exists because `pytest ecoguard/tests/coordinator` is an ordinary-looking
# command that says nothing about which database it is about to empty, and .env
# points at the deployed one. Reading the URL off .env and deleting from it was
# a live-data loss waiting for whoever ran the suite without thinking about it.
#
# A remote URL is therefore never used implicitly. Naming it in
# ECOGUARD_TEST_DATABASE_URL is the opt-in, because that variable cannot be set
# by accident and cannot be the deployed database unless somebody typed it there.
LOCAL_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", ""})


@pytest.fixture(scope="session")
def database():
    """Skip unless a Postgres we are *allowed to empty* is reachable and migrated."""
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    from ecoguard.database.engine import DATABASE_URL, engine

    if (
        make_url(DATABASE_URL).host not in LOCAL_DATABASE_HOSTS
        and not _test_database_url
    ):
        pytest.skip(
            f"refusing to run destructive database tests against "
            f"{make_url(DATABASE_URL).host}: it is not local and was not named in "
            f"{TEST_DATABASE_URL_VARIABLE}. These fixtures DELETE rows. Set "
            f"{TEST_DATABASE_URL_VARIABLE} to a scratch database to run them."
        )

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
