"""The text triage migration stays small, additive, and correctly chained."""

from importlib import import_module


migration = import_module(
    "ecoguard.database.migrations.versions.0029_text_candidate_triage"
)


def test_text_candidate_triage_is_the_successor_to_weak_events():
    assert migration.revision == "text_candidate_triage"
    assert migration.down_revision == "weak_events"


def test_upgrade_adds_only_the_nullable_marker_and_pending_partial_index(monkeypatch):
    statements = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.upgrade()

    assert statements == [
        "ALTER TABLE text_candidates ADD COLUMN triaged_at timestamptz",
        (
            "CREATE INDEX text_candidates_pending_triage "
            "ON text_candidates (observed_at, id) WHERE triaged_at IS NULL"
        ),
    ]


def test_downgrade_targets_only_the_added_index_and_column(monkeypatch):
    statements = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.downgrade()

    assert statements == [
        "DROP INDEX IF EXISTS text_candidates_pending_triage",
        "ALTER TABLE text_candidates DROP COLUMN triaged_at",
    ]
