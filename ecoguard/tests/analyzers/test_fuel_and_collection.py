"""Fuel blending, forecast identity, and multi-satellite merging.

Three places where a plausible-looking wrong answer is easy to produce.

Fuel blending over a mixed cell: renormalising onto the burnable part turns a
fifth of a cell of grass into a full field of it, and the model then runs a
desert fire at grassland speed.

Forecast identity: every row of one run has to share an issued_at, or "the
newest forecast" stops being a well-defined set of rows and a read gets hours
from two different runs stitched together.

Satellite merging: two instruments over one cell in one minute are one fire.
Grouped wrongly they either collide on the unique constraint and lose data, or
double-count and report twice the hotspots.
"""

from datetime import datetime, timedelta, timezone

import pytest

from ecoguard.collectors.fire.firms.collector import group_hotspots
from ecoguard.collectors.shared.open_meteo.forecast import WeatherForecastCollector, forecast_cells
from ecoguard.analyzers.fire.fuel_models import FUEL_MODELS, NON_BURNABLE, blend


# --- fuel models -----------------------------------------------------------

def test_a_pure_grass_cell_is_the_grass_model():
    fuel = blend({"grassland": 1.0})

    assert fuel["fuel_model_code"] == "FM1"
    assert fuel["load_kg_m2"] == pytest.approx(FUEL_MODELS["grassland"].load_kg_m2)
    assert fuel["burnable_fraction"] == pytest.approx(1.0)


def test_sparse_fuel_over_rock_carries_proportionally_less():
    # The failure this guards: renormalising onto the burnable fifth would
    # report a full grass load and race a fire across bare desert.
    sparse = blend({"grassland": 0.2, "bare_sparse_vegetation": 0.8})
    full = blend({"grassland": 1.0})

    assert sparse["load_kg_m2"] == pytest.approx(full["load_kg_m2"] * 0.2)
    assert sparse["burnable_fraction"] == pytest.approx(0.2)
    # Still grass — the class present is grass, there is just less of it.
    assert sparse["fuel_model_code"] == "FM1"


def test_a_cell_with_nothing_to_burn_reports_no_model():
    fuel = blend({"permanent_water": 0.6, "built_up": 0.4})

    assert fuel["dominant_fuel_model"] is None
    assert fuel["load_kg_m2"] == 0.0
    assert fuel["burnable_fraction"] == 0.0
    assert fuel["spread_adjustment"] == 0.0


def test_built_up_is_never_treated_as_wildland_fuel():
    assert FUEL_MODELS["built_up"] is NON_BURNABLE

    interface = blend({"shrubland": 0.5, "built_up": 0.5})
    wildland = blend({"shrubland": 0.5, "bare_sparse_vegetation": 0.5})

    # Houses contribute exactly as much wildland fuel as bare rock does: none.
    assert interface["load_kg_m2"] == pytest.approx(wildland["load_kg_m2"])


def test_the_dominant_model_ignores_non_burnable_majorities():
    # Mostly rock, but what burns is brush. The model has to describe the fuel
    # that exists, not the rock that does not carry fire.
    fuel = blend({"bare_sparse_vegetation": 0.8, "shrubland": 0.15, "grassland": 0.05})

    assert fuel["fuel_model_code"] == "FM5"


def test_forest_spreads_faster_than_its_surface_load_implies():
    # The crown-fire adjustment: FM9's litter is a slow surface fuel, and a
    # pine stand is not slow. Dropping this makes Carmel-type fires look tame.
    assert blend({"tree_cover": 1.0})["spread_adjustment"] > 1.0
    assert blend({"grassland": 1.0})["spread_adjustment"] == pytest.approx(1.0)


def test_unknown_classes_are_ignored_rather_than_guessed():
    assert blend({"grassland": 1.0, "moon_dust": 5.0})["burnable_fraction"] == pytest.approx(1.0)


def test_every_cover_column_has_a_fuel_model():
    from ecoguard.database.repositories.surface import COVER_COLUMNS

    # A cover class with no entry would silently vanish from every blend.
    assert set(COVER_COLUMNS) <= set(FUEL_MODELS)


# --- forecast --------------------------------------------------------------

class _StubClient:
    batch_size = 50

    def __init__(self, hours):
        self.hours = hours
        self.calls = []

    def fetch_range(self, coordinates, start, end):
        self.calls.append((tuple(coordinates), start, end))
        stamps = [(start + timedelta(hours=n)).isoformat() for n in range(self.hours)]
        return [
            {
                "status": "success",
                "hourly": {
                    "time": stamps,
                    "temperature_2m": [20.0 + n for n in range(self.hours)],
                    "relative_humidity_2m": [40.0] * self.hours,
                    "wind_speed_10m": [12.0] * self.hours,
                },
            }
            for _ in coordinates
        ]


def test_every_row_of_one_run_shares_its_issued_at():
    collector = WeatherForecastCollector(_StubClient(6), horizon_hours=6)

    records = collector.fetch()

    assert records
    assert len({record["issued_at"] for record in records}) == 1


def test_a_forecast_row_is_stamped_with_the_hour_it_describes():
    collector = WeatherForecastCollector(_StubClient(6), horizon_hours=6)

    record = collector.fetch()[0]

    # observed_at is the hour being forecast, so it lines up with the
    # observation of that same hour once the hour arrives.
    assert record["observed_at"] > record["issued_at"]
    assert record["payload"]["lead_hours"] == round(
        (record["observed_at"] - record["issued_at"]).total_seconds() / 3600
    )


def test_the_forecast_grid_is_a_strided_subset_of_the_service_area():
    from ecoguard.collectors.base import service_area_cells

    coarse = forecast_cells(3)

    assert 0 < len(coarse) < len(service_area_cells())
    assert all(cell.grid_row % 3 == 0 and cell.grid_col % 3 == 0 for cell in coarse)
    # Striding on grid position, not list position: rows differ in length, so
    # every third list element would walk diagonally and leave bare bands.
    assert len({cell.grid_row for cell in coarse}) > 1


def test_an_hour_the_provider_could_not_fill_is_skipped():
    class _Empty(_StubClient):
        def fetch_range(self, coordinates, start, end):
            responses = super().fetch_range(coordinates, start, end)
            for response in responses:
                response["hourly"]["temperature_2m"] = [None] * self.hours
                response["hourly"]["relative_humidity_2m"] = [None] * self.hours
                response["hourly"]["wind_speed_10m"] = [None] * self.hours
            return responses

    assert WeatherForecastCollector(_Empty(6), horizon_hours=6).fetch() == []


# --- FIRMS merging ---------------------------------------------------------

def _hotspot(latitude, longitude, date, time, source, frp=5.0):
    return {
        "latitude": latitude, "longitude": longitude,
        "acquisition_date": date, "acquisition_time": time,
        "frp": frp, "firms_source": source,
    }


def test_two_satellites_over_one_cell_at_one_time_are_one_observation():
    # Not a collision to work around — one fire seen twice is one fire.
    grouped = group_hotspots([
        _hotspot(32.0, 35.0, "2026-09-01", "1030", "VIIRS_NOAA20_NRT"),
        _hotspot(32.0, 35.0, "2026-09-01", "1030", "VIIRS_SNPP_NRT"),
    ])

    assert len(grouped) == 1
    assert grouped[0]["payload"]["hotspot_count"] == 2
    assert grouped[0]["payload"]["satellite_sources"] == [
        "VIIRS_NOAA20_NRT", "VIIRS_SNPP_NRT",
    ]


def test_separate_overpasses_stay_separate_observations():
    grouped = group_hotspots([
        _hotspot(32.0, 35.0, "2026-09-01", "1030", "VIIRS_NOAA20_NRT"),
        _hotspot(32.0, 35.0, "2026-09-01", "2210", "VIIRS_NOAA20_NRT"),
    ])

    assert len(grouped) == 2


def test_the_strongest_pixel_survives_grouping():
    grouped = group_hotspots([
        _hotspot(32.0, 35.0, "2026-09-01", "1030", "MODIS_NRT", frp=3.0),
        _hotspot(32.0, 35.0, "2026-09-01", "1030", "VIIRS_NOAA20_NRT", frp=91.0),
    ])

    # Radiative power is how big the fire is; an average would hide the peak.
    assert grouped[0]["payload"]["peak_frp_mw"] == 91.0


def test_hotspots_outside_the_service_area_are_dropped():
    assert group_hotspots([_hotspot(48.0, 2.0, "2026-09-01", "1030", "MODIS_NRT")]) == []
