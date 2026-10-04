# Tests

What stops a change breaking something quietly.

The layout mirrors the code, so tests for the flood analyzer sit in
`analyzers/flood/`. Most run entirely offline: no database, no network, no
model. Where a test needs a model it uses a stand-in that returns a fixed
answer, so the test checks our handling rather than the model's mood.

## Worth knowing before running them

Some tests under `coordinator/` and `database/` write to a real database, and
`test_coordinator.py` deletes every incident it finds — on setup and again on
teardown.

You no longer have to remember that. `conftest.py` refuses to hand those tests a
database that is neither local nor explicitly named as a scratch one, so
`pytest ecoguard/tests` against a deployed `DATABASE_URL` skips them with the
reason rather than emptying it. This used to be a paragraph asking you to pass
`--ignore` twice, which is the kind of instruction that works until the once it
does not.

To actually run them, point them at a throwaway database:

    set ECOGUARD_TEST_DATABASE_URL=postgresql+psycopg://ecoguard:ecoguard@localhost:5432/ecoguard
    pytest ecoguard/tests/coordinator

They need PostGIS and a migrated schema, and skip with the reason when either is
missing. With Docker running, a scratch one is one command:

    docker run --rm -d -p 5432:5432 -e POSTGRES_USER=ecoguard \
      -e POSTGRES_PASSWORD=ecoguard -e POSTGRES_DB=ecoguard postgis/postgis:16-3.4

then `alembic upgrade head` against that URL before the first run.

A handful of tests need trained model files that are not in version control.
They skip when the file is absent rather than failing.

## The ones that earn their keep

`coordinator/test_fire_pipeline_smoke.py` drives a fire from detection all the
way to the dashboard feed without a database or a model call.

`coordinator/test_dispatch_retry_backoff.py` replays a real incident that once
produced 108 model calls in a day, and proves it now produces six.

`detectors/text/test_uncorroborated_lane.py` covers the whole unconfirmed
report path, including the cases the system must refuse.
