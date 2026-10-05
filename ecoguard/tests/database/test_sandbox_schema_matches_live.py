"""A sandbox table must carry the live table's constraints, not last month's.

Sandbox tables were created on first use and then only truncated, so each one
froze at whatever `public` looked like that day. `demo_b.resource_allocations`
kept a rule requiring an earthquake allocation to have no risk score while
`public` had been changed to require one; every earthquake station the
allocator picked was rejected on insert, both Demo B earthquakes dispatched
nobody, and it read as an allocator bug until the row's rejection was read.
"""

import inspect

from ecoguard.demo import sandbox


def test_sandbox_tables_are_rebuilt_rather_than_reused():
    """The drift is only prevented if the table is recreated every run."""
    source = inspect.getsource(sandbox.ensure_schema)

    assert "DROP TABLE IF EXISTS" in source, (
        "a sandbox table kept across runs freezes at an old migration"
    )
    assert "LIKE public." in source, "and is rebuilt from the live definition"
    # The old shape: skip the table when it already exists.
    assert "if exists:" not in source


def test_every_mutable_pipeline_table_is_sandboxed():
    """A table the pipeline writes but the sandbox lacks would write to public."""
    for table in ("observations", "incidents", "event_projections",
                  "resource_allocations", "collector_runs"):
        assert table in sandbox.SANDBOXED_TABLES
