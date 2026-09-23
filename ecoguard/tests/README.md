# Tests

What stops a change breaking something quietly.

The layout mirrors the code, so tests for the flood analyzer sit in
`analyzers/flood/`. Most run entirely offline: no database, no network, no
model. Where a test needs a model it uses a stand-in that returns a fixed
answer, so the test checks our handling rather than the model's mood.

## Worth knowing before running them

Some tests under `coordinator/` and `database/` write to a real database, and
`test_coordinator.py` deletes every incident it finds. If your connection
points at a database you care about, exclude those two folders:

    pytest ecoguard/tests --ignore=ecoguard/tests/coordinator --ignore=ecoguard/tests/database

A handful of tests need trained model files that are not in version control.
They skip when the file is absent rather than failing.

## The ones that earn their keep

`coordinator/test_fire_pipeline_smoke.py` drives a fire from detection all the
way to the dashboard feed without a database or a model call.

`coordinator/test_dispatch_retry_backoff.py` replays a real incident that once
produced 108 model calls in a day, and proves it now produces six.

`detectors/text/test_uncorroborated_lane.py` covers the whole unconfirmed
report path, including the cases the system must refuse.
