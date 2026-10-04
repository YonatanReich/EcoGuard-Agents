import time
from types import SimpleNamespace

import pytest
from sqlalchemy import exc

from ecoguard.database.engine import IDLE_PING_SECONDS, _ping_if_idle


class Connection:
    def __init__(self, dead=False):
        self.dead = dead
        self.pings = 0

    def cursor(self):
        connection = self

        class Cursor:
            def execute(self, _sql):
                connection.pings += 1
                if connection.dead:
                    raise OSError("server closed the connection")

            def close(self):
                pass

        return Cursor()


def _record(idle_seconds):
    returned = None if idle_seconds is None else time.monotonic() - idle_seconds
    return SimpleNamespace(info={} if returned is None else {"returned_at": returned})


def test_a_connection_reused_within_a_wave_is_not_pinged():
    connection = Connection()
    _ping_if_idle(connection, _record(1.0), None)
    _ping_if_idle(connection, _record(None), None)  # brand new
    assert connection.pings == 0


def test_an_idle_connection_is_pinged_and_a_dead_one_is_replaced():
    alive = Connection()
    _ping_if_idle(alive, _record(IDLE_PING_SECONDS + 1), None)
    assert alive.pings == 1
    with pytest.raises(exc.DisconnectionError):
        _ping_if_idle(Connection(dead=True), _record(IDLE_PING_SECONDS + 1), None)
