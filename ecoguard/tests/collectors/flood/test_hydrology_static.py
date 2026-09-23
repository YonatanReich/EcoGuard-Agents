"""Parsing and request behaviour for Water Authority static map layers."""

from __future__ import annotations

import json
import sys
from types import ModuleType
from datetime import datetime, timezone

import pytest

from ecoguard.collectors.flood.hydrology_static import (
    LAYERS,
    StaticHydrologyLayerError,
    download_layers,
    parse_layer,
    persist_layers,
)


NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def _content(feature: dict, *, name: str | None = None) -> bytes:
    document = {"type": "FeatureCollection", "features": [feature]}
    if name:
        document["name"] = name
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


def test_parses_a_drainage_basin_and_keeps_the_original_properties():
    feature = {
        "type": "Feature",
        "properties": {
            "area_id": 2302,
            "basin_id": 17,
            "b_n_eng": "Beit HaEmek",
            "b_n_heb": "בית העמק",
            "area_c": 1,
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[35.0, 32.0], [35.1, 32.0], [35.0, 32.1], [35.0, 32.0]]],
        },
    }

    layer = parse_layer(LAYERS[0], _content(feature, name="basins_v12.1"), imported_at=NOW)

    assert layer.source_version == "basins_v12.1"
    assert layer.rows[0]["basin_id"] == 17
    assert layer.rows[0]["name_he"] == "בית העמק"
    assert json.loads(layer.rows[0]["properties"])["area_id"] == 2302


def test_parses_a_stream_and_normalises_selected_fields():
    feature = {
        "type": "Feature",
        "id": 1,
        "properties": {
            "OBJECTID": 1,
            "NAME": "גרר",
            "STREAM_NAME_H": "גרר",
            "WATER_SOURCE_ID": 199851,
            "MAIN_CATCH_CD": "23",
            "MAIN_CAT_1": "בשור",
            "DRAINING_WATER_ID": 199776,
            "DRAIN_WATER_NAME": "בשור",
        },
        "geometry": {
            "type": "LineString",
            "coordinates": [[34.8, 31.2], [34.9, 31.3]],
        },
    }

    row = parse_layer(LAYERS[1], _content(feature), imported_at=NOW).rows[0]

    assert row["object_id"] == 1
    assert row["name_he"] == "גרר"
    assert row["main_catchment_name"] == "בשור"


def test_road_file_is_parsed_as_kilometre_points_not_as_road_lines():
    feature = {
        "type": "Feature",
        "id": 2,
        "properties": {
            "OBJECTID": 2,
            "ROADNUM": "1",
            "KM": 15,
            "X": 191558,
            "Y": 653522,
            "TYPE_ROAD": "ROAD",
        },
        "geometry": {"type": "Point", "coordinates": [34.909, 31.974]},
    }

    row = parse_layer(LAYERS[2], _content(feature), imported_at=NOW).rows[0]

    assert row["road_number"] == "1"
    assert row["kilometer"] == 15.0
    assert json.loads(row["geometry"])["type"] == "Point"


def test_rejects_an_unexpected_geometry_before_touching_the_database():
    feature = {
        "type": "Feature",
        "properties": {"basin_id": 17},
        "geometry": {"type": "Point", "coordinates": [35.0, 32.0]},
    }

    with pytest.raises(StaticHydrologyLayerError, match="unsupported geometry"):
        parse_layer(LAYERS[0], _content(feature), imported_at=NOW)


def test_rejects_duplicate_source_ids():
    feature = {
        "type": "Feature",
        "properties": {"OBJECTID": 1, "STREAM_NAME_H": "א"},
        "geometry": {"type": "LineString", "coordinates": [[35.0, 32.0], [35.1, 32.1]]},
    }
    document = {"type": "FeatureCollection", "features": [feature, feature]}

    with pytest.raises(StaticHydrologyLayerError, match="duplicate source identity 1"):
        parse_layer(
            LAYERS[1],
            json.dumps(document, ensure_ascii=False).encode("utf-8"),
            imported_at=NOW,
        )


class _Response:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self) -> None:
        pass


class _HttpSession:
    def __init__(self, contents: list[bytes]):
        self.contents = iter(contents)
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return _Response(next(self.contents))


def test_downloads_each_static_layer_once_with_a_timeout():
    basin = _content({
        "type": "Feature",
        "properties": {"basin_id": 1},
        "geometry": {"type": "Polygon", "coordinates": []},
    })
    stream = _content({
        "type": "Feature",
        "properties": {"OBJECTID": 1},
        "geometry": {"type": "LineString", "coordinates": []},
    })
    road = _content({
        "type": "Feature",
        "properties": {"OBJECTID": 1, "ROADNUM": "1", "KM": 0},
        "geometry": {"type": "Point", "coordinates": [35.0, 32.0]},
    })
    http = _HttpSession([basin, stream, road])

    layers = download_layers(http)

    assert [layer.spec.name for layer in layers] == [
        "drainage_basins",
        "streams",
        "road_km_markers",
    ]
    assert len(http.calls) == 3
    assert all(call[1]["timeout"] == 60 for call in http.calls)
    assert all("EcoGuard-Agents/1.0" in call[1]["headers"]["User-Agent"] for call in http.calls)
    assert all("page=hydro_obs" in call[1]["headers"]["Referer"] for call in http.calls)


class _ScalarResult:
    def __init__(self, value=None):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _RecordingSession:
    def __init__(self, *, layer_checksum, network_checksum):
        self.layer_checksum = layer_checksum
        self.network_checksum = network_checksum
        self.calls = []
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.calls.append((sql, parameters))
        if "FROM static_layer_imports" in sql:
            return _ScalarResult(self.layer_checksum)
        if "FROM stream_network_metadata" in sql:
            return _ScalarResult(self.network_checksum)
        return _ScalarResult()

    def commit(self):
        self.committed = True


def _stream_layer():
    feature = {
        "type": "Feature",
        "properties": {
            "OBJECTID": 1,
            "STREAM_NAME_H": "גרר",
            "WATER_SOURCE_ID": 199851,
            "DRAINING_WATER_ID": 199776,
        },
        "geometry": {
            "type": "LineString",
            "coordinates": [[34.8, 31.2], [34.9, 31.3]],
        },
    }
    return parse_layer(LAYERS[1], _content(feature), imported_at=NOW)


def _use_session(monkeypatch, session):
    engine_module = ModuleType("ecoguard.database.engine")
    engine_module.Session = lambda: session
    monkeypatch.setitem(sys.modules, "ecoguard.database.engine", engine_module)


def test_rebuilds_missing_topology_without_rewriting_unchanged_streams(
    monkeypatch,
):
    layer = _stream_layer()
    session = _RecordingSession(
        layer_checksum=layer.checksum,
        network_checksum=None,
    )
    _use_session(monkeypatch, session)

    result = persist_layers([layer])

    sql = [call[0] for call in session.calls]
    assert result == {"streams": 0}
    assert "DELETE FROM streams" not in sql
    assert "DELETE FROM stream_network_nodes" in sql
    assert any("INSERT INTO stream_network_nodes" in item for item in sql)
    assert any("INSERT INTO stream_network_edges" in item for item in sql)
    assert any("INSERT INTO stream_network_metadata" in item for item in sql)
    assert session.committed is True


def test_skips_topology_rebuild_when_its_checksum_is_current(monkeypatch):
    layer = _stream_layer()
    session = _RecordingSession(
        layer_checksum=layer.checksum,
        network_checksum=layer.checksum,
    )
    _use_session(monkeypatch, session)

    persist_layers([layer])

    sql = [call[0] for call in session.calls]
    assert "DELETE FROM stream_network_nodes" not in sql
    assert not any("INSERT INTO stream_network_nodes" in item for item in sql)
    assert session.committed is True
