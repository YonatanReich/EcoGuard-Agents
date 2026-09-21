from datetime import datetime, timedelta, timezone

import pytest

from ecoguard.database.models import Observation
from ecoguard.database.repositories.telegram_observations import (
    telegram_observation_statement,
)


WHEN = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def test_query_is_bounded_by_source_and_message_time():
    statement = telegram_observation_statement(
        observed_since=WHEN - timedelta(hours=3),
        observed_through=WHEN,
        limit=50,
    )
    assert statement.whereclause is not None
    rendered = str(statement)
    assert "observations.source" in rendered
    assert "observations.observed_at >=" in rendered
    assert "observations.observed_at <=" in rendered
    assert "payload" in statement.selected_columns.keys()


def test_query_rejects_unbounded_or_invalid_inputs():
    with pytest.raises(ValueError):
        telegram_observation_statement(
            observed_since=WHEN,
            observed_through=WHEN - timedelta(seconds=1),
        )
    with pytest.raises(ValueError):
        telegram_observation_statement(
            observed_since=WHEN.replace(tzinfo=None),
            observed_through=WHEN,
        )
