# tests/

Subdivided to mirror the source tree, so a test sits where the code it covers
sits:

`collection/` `database/` `detectors/` `analyzers/` `response_planner/`
`resource_allocator/` `shared/` `api/` `scripts/`

`conftest.py` holds the only repo-wide fixture — `database`, which TCP-probes
the configured Postgres and skips rather than hanging when nothing answers.
`fixtures/` holds the one recorded provider response.

`ecoguard/research/tests/` is a **separate, uncollected** root — `pytest.ini`
pins `testpaths = ecoguard/tests`, so research tests are run explicitly.
