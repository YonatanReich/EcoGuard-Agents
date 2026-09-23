"""IMS places RATE scaling metadata on dataset1/what."""

from io import BytesIO

import h5py
import numpy as np

from ecoguard.collectors.flood.radar import read_radar_frame


def test_accepts_the_ims_metadata_layout():
    target = BytesIO()
    with h5py.File(target, "w") as output:
        output.attrs["Conventions"] = "ODIM_H5/V2_2"
        where = output.create_group("where")
        where.attrs["projdef"] = "+proj=aeqd +lat_0=32 +lon_0=34.8"
        where.attrs["xscale"] = 600.0
        where.attrs["yscale"] = 600.0
        dataset = output.create_group("dataset1")
        metadata = dataset.create_group("what")
        metadata.attrs["product"] = "PPI"
        metadata.attrs["quantity"] = "RATE"
        metadata.attrs["gain"] = 1.0
        metadata.attrs["offset"] = 0.0
        metadata.attrs["nodata"] = 65535.0
        metadata.attrs["undetect"] = 0.0
        metadata.attrs["startdate"] = "20260916"
        metadata.attrs["starttime"] = "080503"
        data_group = dataset.create_group("data1")
        data_group.create_dataset("data", data=np.ones((2, 2), dtype=np.float32))

    assert read_radar_frame(target.getvalue()).data_mm_h.tolist() == [
        [1.0, 1.0],
        [1.0, 1.0],
    ]
