"""Transaction and lifecycle tests with scripted SQL results; no real DB."""

import pytest

from ecoguard.database.repositories import air_pollution_baseline_activation as repository
from services.air_pollution_baseline_activation import (
    TARGET_BASELINE_FAMILY,
    BaselineActivationError,
)


class Result:
    def __init__(self, rows=(), rowcount=-1):
        self.rows = list(rows)
        self.rowcount = rowcount

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
        return response

    def connection(self, **kwargs):
        self.connection_options = kwargs
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def rollback(self):
        self.rolled_back = True


def profiles(count=2):
    return Result([
        {"id": profile_id, "baseline_family": TARGET_BASELINE_FAMILY}
        for profile_id in range(1, count + 1)
    ])


def versions(*, include_active=False):
    rows = [
        {"id": 11, "profile_id": 1, "lifecycle_status": "draft",
         "coverage_status": "FULL_BASELINE",
         "baseline_family": TARGET_BASELINE_FAMILY},
        {"id": 22, "profile_id": 2, "lifecycle_status": "draft",
         "coverage_status": "PARTIAL_BASELINE",
         "baseline_family": TARGET_BASELINE_FAMILY},
    ]
    if include_active:
        rows.insert(1, {
            "id": 10, "profile_id": 1, "lifecycle_status": "active",
            "coverage_status": "FULL_BASELINE",
            "baseline_family": TARGET_BASELINE_FAMILY,
        })
    return Result(rows)


def counts(second=288):
    return Result([
        {"baseline_version_id": 11, "bucket_count": 288},
        {"baseline_version_id": 22, "bucket_count": second},
    ])


def final_rows(*, old=False, duplicate_active=False):
    rows = [
        {"id": 11, "profile_id": 1, "lifecycle_status": "active"},
        {"id": 22, "profile_id": 2, "lifecycle_status": "active"},
    ]
    if old:
        rows.append({
            "id": 10, "profile_id": 1,
            "lifecycle_status": "active" if duplicate_active else "superseded",
        })
    return Result(rows)


def test_successful_cohort_activation():
    session = ScriptedSession([
        profiles(), versions(), counts(), Result(rowcount=2), final_rows(),
    ])

    result = repository.activate_baseline_family_in_session(
        session, family=TARGET_BASELINE_FAMILY, expected_profile_count=2,
    )

    assert result["after"] == {
        "profiles": 2, "versions": 2, "lifecycle": {"active": 2},
        "active": 2, "draft": 0,
        "superseded_in_transaction": 0,
    }
    assert result["activated_version_ids"] == [11, 22]
    assert result["activated_count"] == 2
    assert result["superseded_count"] == 0
    assert result["final_active_count"] == 2
    assert "active" in session.calls[3][0].compile().params.values()


def test_existing_active_is_superseded_before_draft_activation():
    session = ScriptedSession([
        profiles(), versions(include_active=True), counts(),
        Result(rowcount=1), Result(rowcount=2), final_rows(old=True),
    ])

    result = repository.activate_baseline_family_in_session(
        session, family=TARGET_BASELINE_FAMILY, expected_profile_count=2,
    )

    assert result["superseded_version_ids"] == [10]
    assert "superseded" in session.calls[3][0].compile().params.values()
    assert "active" in session.calls[4][0].compile().params.values()


def test_incomplete_draft_stops_before_any_update():
    session = ScriptedSession([profiles(), versions(), counts(second=287)])

    with pytest.raises(BaselineActivationError, match="incomplete_draft_version"):
        repository.activate_baseline_family_in_session(
            session, family=TARGET_BASELINE_FAMILY, expected_profile_count=2,
        )
    assert len(session.calls) == 3


def test_readiness_audit_is_explicitly_read_only(monkeypatch):
    session = ScriptedSession([
        Result(), profiles(), versions(), counts(),
    ])

    class ReadSessionFactory:
        def __call__(self):
            return session

    monkeypatch.setattr(repository, "Session", ReadSessionFactory())
    result = repository.audit_baseline_family_activation(
        family=TARGET_BASELINE_FAMILY, expected_profile_count=2,
    )

    assert result["ready"] is True
    assert str(session.calls[0][0]) == "SET TRANSACTION READ ONLY"
    assert all(call[0].is_select for call in session.calls[1:])
    assert session.rolled_back is True


def test_post_write_unique_active_check_fails_closed():
    session = ScriptedSession([
        profiles(), versions(include_active=True), counts(),
        Result(rowcount=1), Result(rowcount=2),
        final_rows(old=True, duplicate_active=True),
    ])

    with pytest.raises(BaselineActivationError, match="supersede_verification"):
        repository.activate_baseline_family_in_session(
            session, family=TARGET_BASELINE_FAMILY, expected_profile_count=2,
        )


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


def test_second_update_failure_rolls_back_prior_supersede(monkeypatch):
    session = ScriptedSession([
        profiles(), versions(include_active=True), counts(),
        Result(rowcount=1), Result(rowcount=0),
    ])
    transaction = Transaction(session)
    monkeypatch.setattr(repository, "Session", SessionFactory(transaction))

    with pytest.raises(BaselineActivationError, match="activation_count_mismatch"):
        repository.activate_baseline_family(
            family=TARGET_BASELINE_FAMILY, expected_profile_count=2,
        )
    assert transaction.rolled_back is True
    assert transaction.committed is False
