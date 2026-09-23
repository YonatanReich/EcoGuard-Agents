from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ecoguard.collectors.shared.telegram.collector import message_record
from ecoguard.collectors.shared.telegram.policy import (
    CHANNEL_POLICIES,
    TelegramChannelIdentityError,
    TelegramChannelPolicy,
    public_message_url,
)


POLICY = TelegramChannelPolicy(
    "Israel_Police_100",
    "official_supporting_source",
    "official_supporting",
    "TEST_TELEGRAM_PEER_ID",
)
POSTED = datetime(2026, 9, 19, 8, 30, tzinfo=timezone.utc)


def test_channel_policy_is_the_explicit_ea_374_allowlist():
    assert {
        policy.username: (policy.role, policy.pinned_peer_id)
        for policy in CHANNEL_POLICIES
    } == {
        "Israel_Police_100": ("official_supporting_source", -1002843129862),
        "Atanpolice": ("official_supporting_source", -1001581748447),
        "mdaisrael": ("official_supporting_source", -1001177174722),
        "fireisrael7777": ("unofficial_aggregator", -1001411503185),
    }


def test_verified_policy_rejects_conflicting_environment_override(monkeypatch):
    policy = CHANNEL_POLICIES[0]
    monkeypatch.setenv(policy.peer_id_environment, "-100999")

    with pytest.raises(TelegramChannelIdentityError, match="conflicts with verified"):
        _ = policy.pinned_peer_id


def test_source_url_is_only_built_for_safe_public_usernames():
    assert public_message_url("Israel_Police_100", 42) == (
        "https://t.me/Israel_Police_100/42"
    )
    assert public_message_url("unsafe/name", 42) is None


def _message(**changes):
    values = {
        "id": 42,
        "date": POSTED,
        "edit_date": None,
        "raw_text": "שריפה בחיפה",
        "fwd_from": None,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_record_has_stable_identity_and_complete_public_provenance(monkeypatch):
    monkeypatch.setenv("TEST_TELEGRAM_PEER_ID", "-100123")

    first = message_record(
        policy=POLICY,
        peer_id=-100123,
        resolved_username="Israel_Police_100",
        channel_title="Israel Police",
        message=_message(),
    )
    second = message_record(
        policy=POLICY,
        peer_id=-100123,
        resolved_username="Israel_Police_100",
        channel_title="Israel Police",
        message=_message(),
    )

    assert first == second
    assert first["cell_id"] == "telegram:-100123:42"
    assert first["observed_at"] == POSTED
    assert first["payload"]["source_url"] == (
        "https://t.me/Israel_Police_100/42"
    )
    assert first["payload"]["raw_text"] == "שריפה בחיפה"
    assert first["payload"]["source_verification"] == {
        "tier": "official_supporting",
        "role": "official_supporting_source",
        "peer_id_pinned": True,
        "peer_id_verified": True,
        "event_verified": False,
    }


def test_forwarded_provenance_and_edit_time_are_preserved(monkeypatch):
    monkeypatch.setenv("TEST_TELEGRAM_PEER_ID", "-100123")
    forward = SimpleNamespace(
        from_id=SimpleNamespace(channel_id=777),
        from_name="Origin",
        channel_post=9,
        date=POSTED,
        post_author="Dispatcher",
    )
    edited = POSTED.replace(minute=35)
    record = message_record(
        policy=POLICY,
        peer_id=-100123,
        resolved_username="Israel_Police_100",
        channel_title="Israel Police",
        message=_message(edit_date=edited, fwd_from=forward),
    )

    assert record["payload"]["edited_at"] == edited.isoformat()
    assert record["payload"]["forwarded_provenance"]["origin_peer_id"] == 777
    assert record["payload"]["forwarded_provenance"]["origin_message_id"] == 9


def test_changed_peer_mapping_is_rejected(monkeypatch):
    monkeypatch.setenv("TEST_TELEGRAM_PEER_ID", "-100123")
    with pytest.raises(TelegramChannelIdentityError):
        message_record(
            policy=POLICY,
            peer_id=-100999,
            resolved_username="Israel_Police_100",
            channel_title="Impostor",
            message=_message(),
        )


def test_unpinned_source_is_collected_but_not_claimed_verified(monkeypatch):
    monkeypatch.delenv("TEST_TELEGRAM_PEER_ID", raising=False)
    record = message_record(
        policy=POLICY,
        peer_id=-100123,
        resolved_username="Israel_Police_100",
        channel_title="Israel Police",
        message=_message(),
    )
    assert record["payload"]["source_verification"]["tier"] == "unverified"
    assert record["payload"]["source_verification"]["peer_id_verified"] is False
