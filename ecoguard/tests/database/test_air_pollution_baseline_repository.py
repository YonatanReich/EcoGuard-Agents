"""Set-based repository tests with scripted results; no database connection."""

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from ecoguard.database.repositories import air_pollution_baselines as repository

IDENTITY = {"provider": "provider", "station_id": "1", "channel_id": "4",
            "pollutant": "NO2", "canonical_unit": "µg/m³",
            "baseline_family": "completed_hour"}
NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)


def version(digest="b" * 64, parent=None):
    return {"profile_identity": IDENTITY, "content_sha256": digest,
            "parent_content_sha256": parent, "schema_version": "v2",
            "method_version": None, "source_name": "source", "source_version": None,
            "training_start": NOW.date(), "training_end": NOW.date(),
            "generated_at": None, "aggregation_policy_version": "agg-v1",
            "quality_policy_version": "quality-v1", "coverage_status": "FULL_BASELINE",
            "lifecycle_status": "draft", "source_metadata": {},
            "aggregation_metadata": {}, "quality_metadata": {}, "coverage_metadata": {}}


def bucket(digest="b" * 64, hour=0):
    return {"profile_identity": IDENTITY, "content_sha256": digest,
            "month": 1, "hour": hour, "status": "ok", "sample_count": 30,
            "distinct_days": 30, "distinct_years": 3, "years_present": [2021, 2023, 2025],
            "mean": -.1, "median": 0., "std": 1., "mad": .5,
            "p05": -2., "p25": -1., "p75": 1., "p95": 2.}


def plan():
    return {"plan_schema": "air-pollution-baseline-import-plan-v1", "dry_run": True,
            "station_catalog": [{"provider": "provider", "station_id": "1",
                                 "station_name": "Station", "availability": [],
                                 "artifact_sha256": "a" * 64}],
            "profiles": [IDENTITY], "versions": [version()], "buckets": [bucket()]}


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def mappings(self):
        return self

    def all(self):
        return self.rows


class ScriptedSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def execute(self, statement, parameters=None):
        self.calls.append((statement, parameters))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return Result(response)


def existing_station(name="Station"):
    return {"provider": "provider", "station_id": "1", "station_name": name,
            "availability": [], "artifact_sha256": "a" * 64}


def existing_profile():
    return {"id": 10, **IDENTITY}


def test_repository_identity_keeps_baseline_families_independent():
    completed = repository._identity(IDENTITY)
    immediate = repository._identity({
        **IDENTITY, "baseline_family": "five_minute_observation",
    })
    assert completed != immediate


def test_clean_import_uses_bulk_returning_and_progress():
    session = ScriptedSession([
        [], [{"provider": "provider", "station_id": "1"}],
        [], [{"id": 10, **IDENTITY}],
        [], [{"id": 20, "profile_id": 10, "content_sha256": "b" * 64}],
        [],
    ])
    progress = []
    result = repository.persist_import_plan(session, plan(), imported_at=NOW, progress=progress.append)
    assert result == {"stations_inserted": 1, "profiles_inserted": 1,
                      "versions_inserted": 1, "buckets_inserted": 1, "versions_existing": 0}
    assert len(session.calls) == 7
    assert session.calls[1][1][0]["imported_at"] == NOW
    assert session.calls[3][1] == [IDENTITY]
    assert session.calls[5][1][0]["profile_id"] == 10
    assert session.calls[6][1][0]["baseline_version_id"] == 20
    assert progress == ["station catalog", "profiles", "versions", "buckets 0 / 1", "buckets 1 / 1"]


def test_idempotent_rerun_is_four_set_based_reads_and_no_writes():
    session = ScriptedSession([
        [existing_station()], [existing_profile()],
        [{"id": 20, "profile_id": 10, "content_sha256": "b" * 64}],
        [{"baseline_version_id": 20, "bucket_count": 1}],
    ])
    result = repository.persist_import_plan(session, plan(), imported_at=NOW)
    assert result == {"stations_inserted": 0, "profiles_inserted": 0,
                      "versions_inserted": 0, "buckets_inserted": 0, "versions_existing": 1}
    assert len(session.calls) == 4
    assert all(parameters is None for _, parameters in session.calls)


def test_conflict_detection_stops_before_any_insert():
    session = ScriptedSession([[existing_station("Different")]])
    with pytest.raises(ValueError, match="station catalog conflict"):
        repository.persist_import_plan(session, plan(), imported_at=NOW)
    assert len(session.calls) == 1


def test_incomplete_existing_version_detection_is_set_based():
    session = ScriptedSession([
        [existing_station()], [existing_profile()],
        [{"id": 20, "profile_id": 10, "content_sha256": "b" * 64}], [],
    ])
    with pytest.raises(ValueError, match="existing baseline version is incomplete"):
        repository.persist_import_plan(session, plan(), imported_at=NOW)
    assert len(session.calls) == 4


def test_parent_version_already_exists():
    child_hash, parent_hash = "c" * 64, "p" * 64
    proposed = plan()
    proposed["versions"] = [version(child_hash, parent_hash)]
    proposed["buckets"] = [bucket(child_hash)]
    session = ScriptedSession([
        [existing_station()], [existing_profile()],
        [{"id": 19, "profile_id": 10, "content_sha256": parent_hash}],
        [{"id": 20, "profile_id": 10, "content_sha256": child_hash}], [],
    ])
    repository.persist_import_plan(session, proposed, imported_at=NOW)
    assert session.calls[3][1][0]["parent_version_id"] == 19


def test_parent_in_same_plan_is_inserted_in_dependency_order():
    parent_hash, child_hash = "p" * 64, "c" * 64
    proposed = plan()
    proposed["versions"] = [version(child_hash, parent_hash), version(parent_hash)]
    proposed["buckets"] = [bucket(child_hash), bucket(parent_hash, hour=1)]
    session = ScriptedSession([
        [existing_station()], [existing_profile()], [],
        [{"id": 19, "profile_id": 10, "content_sha256": parent_hash}],
        [{"id": 20, "profile_id": 10, "content_sha256": child_hash}], [],
    ])
    result = repository.persist_import_plan(session, proposed, imported_at=NOW)
    assert result["versions_inserted"] == 2
    assert session.calls[3][1][0]["parent_version_id"] is None
    assert session.calls[4][1][0]["parent_version_id"] == 19
    assert {row["baseline_version_id"] for row in session.calls[5][1]} == {19, 20}


def test_missing_parent_fails_before_version_or_bucket_insert():
    proposed = plan()
    proposed["versions"] = [version("c" * 64, "missing")]
    proposed["buckets"] = [bucket("c" * 64)]
    session = ScriptedSession([[existing_station()], [existing_profile()], []])
    with pytest.raises(ValueError, match="missing or cyclic parent"):
        repository.persist_import_plan(session, proposed, imported_at=NOW)
    assert len(session.calls) == 3


class Transaction:
    def __init__(self, session):
        self.session = session
        self.committed = self.rolled_back = False

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, *_):
        self.committed = exc_type is None
        self.rolled_back = exc_type is not None


class SessionFactory:
    def __init__(self, transaction):
        self.transaction = transaction

    def begin(self):
        return self.transaction


def test_failure_rolls_back_whole_transaction_and_never_reports_commit(monkeypatch):
    session = ScriptedSession([[], [{"provider": "provider", "station_id": "1"}], RuntimeError("profile failure")])
    transaction = Transaction(session)
    monkeypatch.setattr(repository, "Session", SessionFactory(transaction))
    progress = []
    with pytest.raises(RuntimeError, match="profile failure"):
        repository.import_baseline_plan(plan(), progress=progress.append)
    assert transaction.rolled_back and not transaction.committed
    assert "commit complete" not in progress


def test_success_reports_commit_only_after_transaction_exit(monkeypatch):
    session = ScriptedSession([
        [existing_station()], [existing_profile()],
        [{"id": 20, "profile_id": 10, "content_sha256": "b" * 64}],
        [{"baseline_version_id": 20, "bucket_count": 1}],
    ])
    transaction = Transaction(session)
    monkeypatch.setattr(repository, "Session", SessionFactory(transaction))
    progress = []
    repository.import_baseline_plan(plan(), progress=progress.append)
    assert transaction.committed and not transaction.rolled_back
    assert progress[-1] == "commit complete"


def test_plan_guardrails_remain():
    with pytest.raises(ValueError, match="UTC offset"):
        repository.persist_import_plan(ScriptedSession([]), plan(), imported_at=datetime(2026, 1, 1))
    bad = deepcopy(plan())
    bad["dry_run"] = False
    with pytest.raises(ValueError, match="validated dry-run"):
        repository.persist_import_plan(ScriptedSession([]), bad, imported_at=NOW)


def test_bucket_chunks_are_bounded_and_progress_is_concise(monkeypatch):
    proposed = plan()
    proposed["buckets"] = [bucket(hour=hour) for hour in range(3)]
    monkeypatch.setattr(repository, "BUCKET_CHUNK_SIZE", 2)
    session = ScriptedSession([
        [existing_station()], [existing_profile()], [],
        [{"id": 20, "profile_id": 10, "content_sha256": "b" * 64}], [], [],
    ])
    progress = []
    result = repository.persist_import_plan(session, proposed, imported_at=NOW, progress=progress.append)
    assert result["buckets_inserted"] == 3
    assert [len(parameters) for _, parameters in session.calls[-2:]] == [2, 1]
    assert progress[-2:] == ["buckets 0 / 3", "buckets 3 / 3"]
