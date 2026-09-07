"""single_flight is what stops two developers' processes doing the same sweep."""

from ecoguard.database.locks import lock_key, single_flight


def test_a_held_lock_is_refused_rather_than_waited_for(database):
    with single_flight("test_worker") as first:
        assert first is True
        with single_flight("test_worker") as second:
            assert second is False


def test_the_lock_is_released_when_the_block_exits(database):
    with single_flight("test_worker") as acquired:
        assert acquired is True
    with single_flight("test_worker") as acquired:
        assert acquired is True


def test_different_workers_do_not_block_each_other(database):
    with single_flight("collect_firms") as firms:
        with single_flight("collect_weather") as weather:
            assert firms is True and weather is True


def test_lock_keys_fit_the_signed_64_bit_range_postgres_takes():
    for name in ("collect_firms", "collect_weather", "collect_fire_weather", "collect_telegram"):
        assert -(2 ** 63) <= lock_key(name) < 2 ** 63
