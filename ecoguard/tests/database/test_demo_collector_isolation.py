"""A live collector cannot write into a demo schema, whatever the timing.

Both directions of a real contamination. A scenario was started while
`gsi_earthquake` was mid-run; `job.pause()` does not stop a job already
executing, so its next connection came from the freshly disposed pool carrying
`demo_b, public`. Five real earthquakes landed in `demo_b.observations`, and its
run record opened in `demo_b` and closed in `public`, leaving a row stuck at
`running` in one schema and an orphan in the other.

Pausing narrows that window; separate pools close it.
"""

from sqlalchemy import text

from ecoguard.database.engine import (
    Session,
    collector_database,
    collector_engine,
    engine,
    is_collector_context,
    use_sandbox,
)


def _search_path() -> str:
    """Where a session opened right now would write."""
    with Session() as session:
        return session.execute(text("show search_path")).scalar()


def test_a_collector_stays_on_public_while_a_scenario_holds_the_sandbox():
    """The leak that happened: a collector running during a demo wrote to it."""
    try:
        use_sandbox("demo_b")
        assert _search_path().startswith("demo_b"), "the pipeline follows the sandbox"

        with collector_database():
            assert _search_path() == "public", (
                "a collector must never inherit the scenario's schema"
            )
    finally:
        use_sandbox(None)

    assert _search_path() == "public"


def test_the_context_does_not_leak_out_of_its_block():
    """A collector finishing must not leave the pipeline pinned to public."""
    assert is_collector_context() is False
    with collector_database():
        assert is_collector_context() is True
    assert is_collector_context() is False


def test_switching_the_sandbox_does_not_disturb_the_collector_pool():
    """use_sandbox disposes only the pipeline pool, by design.

    Disposing the collector pool too would be harmless but pointless, and it
    would reintroduce the coupling this split exists to remove.
    """
    with collector_database():
        with Session() as session:
            session.execute(text("select 1"))

    before = collector_engine.pool.checkedin()
    try:
        use_sandbox("demo_a")
        assert collector_engine.pool.checkedin() == before, (
            "the collector pool must survive a scenario switch"
        )
    finally:
        use_sandbox(None)


def test_the_two_engines_are_distinct_pools_on_one_database():
    """One database, two pools - not two databases."""
    assert engine is not collector_engine
    assert engine.url == collector_engine.url
