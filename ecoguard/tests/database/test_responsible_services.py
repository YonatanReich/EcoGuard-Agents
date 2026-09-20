"""Every district must have stations, and the alias is why one of them does.

`towns.fire_district` says `יו"ש`; `fire_stations.district` says
`יהודה ושומרון`. A direct join returns an empty list for 122 towns, which reads
identically to "no station is responsible here" — the worst shape for a bug in
a dispatch path, because nothing raises and the answer looks complete.
"""

import pytest

from ecoguard.database.repositories.responsible_services import (
    DISTRICT_ALIASES,
    district_for_stations,
    district_station_coverage,
    responsible_services,
)


def test_the_alias_maps_the_towns_spelling_to_the_stations_spelling():
    assert district_for_stations('יו"ש') == "יהודה ושומרון"


def test_a_district_that_needs_no_alias_passes_through():
    assert district_for_stations("צפון") == "צפון"


def test_no_district_is_aliased_onto_another_real_district():
    """An alias pointing at the wrong district would silently misroute."""
    assert set(DISTRICT_ALIASES).isdisjoint(set(DISTRICT_ALIASES.values()))


def test_a_town_with_no_district_resolves_to_nothing_rather_than_guessing():
    assert district_for_stations(None) is None
    assert district_for_stations("") is None


def test_every_district_with_towns_has_at_least_one_station(database):
    """The regression this module exists for.

    Before the alias, `יו"ש` reported 122 towns and zero stations.
    """
    coverage = district_station_coverage()
    assert coverage, "no districts found; the towns table is not loaded"

    empty = [row for row in coverage if row["towns"] and not row["stations"]]
    assert not empty, (
        "districts with towns but no responsible stations: "
        + ", ".join(f"{row['fire_district']} ({row['towns']} towns)" for row in empty)
    )


def test_an_unknown_town_is_reported_as_not_found(database):
    result = responsible_services("no-such-town-id")
    assert result["found"] is False


def test_a_resolved_town_carries_who_to_call(database):
    """The point of the lookup: a name is not actionable, a phone number is."""
    coverage = district_station_coverage()
    if not coverage:
        pytest.skip("towns not loaded")

    from sqlalchemy import text

    from ecoguard.database.engine import Session

    with Session() as session:
        town_id = session.execute(
            text(
                "SELECT town_id FROM towns "
                "WHERE authority_phone IS NOT NULL AND fire_district IS NOT NULL "
                "LIMIT 1"
            )
        ).scalar()
    if town_id is None:
        pytest.skip("no town with both a phone number and a district")

    result = responsible_services(town_id)
    assert result["found"] is True
    assert result["authority_phone"]
    assert result["fire_stations"], "a town in a district must reach its stations"
