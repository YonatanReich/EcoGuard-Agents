"""Unified command behaviour for the separate static hydrology collectors."""

from ecoguard.scripts import load_hydrology_static_data


def test_main_invokes_collectors_and_materializes_context(monkeypatch, capsys):
    calls = []

    def load_layers():
        calls.append("layers")
        return {"drainage_basins": 139, "streams": 0, "road_km_markers": 0}

    def load_stations():
        calls.append("stations")
        return {"owners": 27, "stations": 126, "rain_links": 133}

    def refresh_context():
        calls.append("context")
        return {
            "cells": 1200,
            "hydrometric_stations": 126,
            "rain_stations": 80,
            "station_topologies": 126,
        }

    monkeypatch.setattr(
        load_hydrology_static_data,
        "load_static_hydrology_layers",
        load_layers,
    )
    monkeypatch.setattr(
        load_hydrology_static_data,
        "load_hydrometric_station_catalog",
        load_stations,
    )
    monkeypatch.setattr(
        load_hydrology_static_data,
        "refresh_flood_static_context",
        refresh_context,
    )

    load_hydrology_static_data.main()

    assert calls == ["layers", "stations", "context"]
    output = capsys.readouterr().out
    assert "drainage_basins: loaded 139 features" in output
    assert "streams: unchanged" in output
    assert "27 owners, 126 stations, 133 rain-station links" in output
    assert "1,200 cells" in output
    assert "126 station routes" in output
