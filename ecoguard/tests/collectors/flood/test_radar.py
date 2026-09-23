"""Numeric ODIM PPI parsing and cell aggregation."""

from datetime import datetime, timezone
from io import BytesIO

import h5py
import numpy as np
import pytest
import requests
from requests_ntlm import HttpNtlmAuth

from ecoguard.collectors.flood.radar import (
    RadarAuthenticationError,
    RadarCellMapping,
    RadarPPICollector,
    ppi_links,
    ppi_links_since,
    read_radar_frame,
    records_from_frame,
)


def _hdf5_bytes():
    target = BytesIO()
    with h5py.File(target, "w") as output:
        output.attrs["Conventions"] = "ODIM_H5/V2_2"
        where = output.create_group("where")
        where.attrs["projdef"] = "+proj=aeqd +a=6378137 +lat_0=32.007 +lon_0=34.81456 +rf=298.257224"
        where.attrs["xscale"] = 600.0
        where.attrs["yscale"] = 600.0
        dataset = output.create_group("dataset1")
        product = dataset.create_group("what")
        product.attrs["product"] = "PPI"
        product.attrs["startdate"] = "20260916"
        product.attrs["starttime"] = "080503"
        data_group = dataset.create_group("data1")
        data_what = data_group.create_group("what")
        data_what.attrs["quantity"] = "RATE"
        data_what.attrs["gain"] = 0.5
        data_what.attrs["offset"] = 0.0
        data_what.attrs["nodata"] = 65535.0
        data_what.attrs["undetect"] = 0.0
        data_group.create_dataset(
            "data",
            data=np.array([[0, 2], [4, 65535]], dtype=np.float32),
        )
    return target.getvalue()


def test_reads_scaled_numeric_rate_and_nodata_from_hdf5():
    frame = read_radar_frame(_hdf5_bytes(), source_name="sample.PPI.1.h5")

    assert frame.observed_at == datetime(2026, 9, 16, 8, 5, 3, tzinfo=timezone.utc)
    assert frame.data_mm_h[0, 1] == 1.0
    assert frame.data_mm_h[1, 0] == 2.0
    assert np.isnan(frame.data_mm_h[1, 1])


def test_aggregates_a_cell_as_numeric_rain_not_image_colour():
    frame = read_radar_frame(_hdf5_bytes(), source_name="sample.PPI.1.h5")
    mapping = RadarCellMapping("cell-a", 32.0, 34.8, 0, 2, 0, 2)

    record = records_from_frame(frame, [mapping])[0]

    assert record["payload"]["rain_rate_max_mm_h"] == 2.0
    assert record["payload"]["rain_rate_mean_mm_h"] == 1.0
    assert record["payload"]["rainfall_mm"] == 0.08333
    assert isinstance(record["payload"]["peak_latitude"], float)
    assert isinstance(record["payload"]["peak_longitude"], float)


def test_keeps_a_dry_heartbeat_only_for_an_active_rain_event():
    frame = read_radar_frame(_hdf5_bytes(), source_name="sample.PPI.1.h5")
    frame.data_mm_h[:] = 0.0
    active = RadarCellMapping("cell-active", 32.0, 34.8, 0, 2, 0, 2)
    inactive = RadarCellMapping("cell-inactive", 32.1, 34.9, 0, 2, 0, 2)

    records = records_from_frame(
        frame,
        [active, inactive],
        include_dry_cells={"cell-active"},
    )

    assert [record["cell_id"] for record in records] == ["cell-active"]
    assert records[0]["payload"]["rainfall_mm"] == 0.0


def test_index_parser_returns_only_latest_unique_ppi_files():
    page = """
      <a href="iltlv.20260916080003.PPI.1.h5">a</a>
      <a href="iltlv.20260916080503.PPI.2.h5">b</a>
      <a href="iltlv.20260916080503.PPI.2.h5">b again</a>
      <a href="iltlv.20260916T081003Z.PVOL.h5">not PPI</a>
    """

    assert ppi_links(page, limit=1) == ["iltlv.20260916080503.PPI.2.h5"]


def test_cold_start_keeps_a_small_initial_radar_window():
    page = "".join(
        f'<a href="iltlv.2026091608{minute:02d}03.PPI.{minute}.h5">frame</a>'
        for minute in range(0, 25, 5)
    )

    assert ppi_links_since(page, None, initial_frames=2) == [
        "iltlv.20260916081503.PPI.15.h5",
        "iltlv.20260916082003.PPI.20.h5",
    ]


def test_radar_catch_up_returns_every_new_frame_plus_overlap():
    page = "".join(
        f'<a href="iltlv.2026091608{minute:02d}03.PPI.{minute}.h5">frame</a>'
        for minute in range(0, 25, 5)
    )
    latest_cached = datetime(2026, 9, 16, 8, 10, 3, tzinfo=timezone.utc)

    links = ppi_links_since(page, latest_cached, overlap_frames=2)

    assert links == [
        "iltlv.20260916080503.PPI.5.h5",
        "iltlv.20260916081003.PPI.10.h5",
        "iltlv.20260916081503.PPI.15.h5",
        "iltlv.20260916082003.PPI.20.h5",
    ]


def test_radar_catch_up_fetches_only_overlap_when_nothing_is_new():
    page = "".join(
        f'<a href="iltlv.2026091608{minute:02d}03.PPI.{minute}.h5">frame</a>'
        for minute in range(0, 25, 5)
    )
    latest_cached = datetime(2026, 9, 16, 8, 30, 3, tzinfo=timezone.utc)

    assert ppi_links_since(page, latest_cached, overlap_frames=2) == [
        "iltlv.20260916081503.PPI.15.h5",
        "iltlv.20260916082003.PPI.20.h5",
    ]


def test_collector_reads_cookie_from_environment(monkeypatch):
    monkeypatch.setenv("IMS_RADAR_COOKIE", "session=secret-value")

    collector = RadarPPICollector()

    assert collector.http.headers["Cookie"] == "session=secret-value"


def test_collector_accepts_a_complete_cookie_header(monkeypatch):
    monkeypatch.delenv("IMS_RADAR_COOKIE", raising=False)

    collector = RadarPPICollector(cookie="Cookie: session=secret-value")

    assert collector.http.headers["Cookie"] == "session=secret-value"


def test_authentication_error_does_not_include_cookie_value(monkeypatch):
    monkeypatch.setenv("IMS_RADAR_COOKIE", "session=do-not-log-this")
    collector = RadarPPICollector()
    response = requests.Response()
    response.status_code = 401

    with pytest.raises(RadarAuthenticationError) as error:
        collector._require_success(response)

    assert "do-not-log-this" not in str(error.value)


def test_collector_configures_ntlm_credentials_from_environment(monkeypatch):
    monkeypatch.setenv("IMS_RADAR_USERNAME", "DOMAIN\\radar-user")
    monkeypatch.setenv("IMS_RADAR_PASSWORD", "secret-password")

    collector = RadarPPICollector()

    assert isinstance(collector.http.auth, HttpNtlmAuth)


def test_collector_rejects_partial_ntlm_configuration(monkeypatch):
    monkeypatch.setenv("IMS_RADAR_USERNAME", "radar-user")
    monkeypatch.delenv("IMS_RADAR_PASSWORD", raising=False)

    with pytest.raises(ValueError, match="must be set together"):
        RadarPPICollector()
