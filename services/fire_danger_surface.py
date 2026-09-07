"""Turn the FWI point samples into a smooth, georeferenced image.

The dashboard needs a continuous surface; the data is 620 samples on a 5 km
grid. Every attempt to bridge that gap in the browser fails for the same
reason — Mapbox has no interpolating layer type, so heatmaps, circles and fills
all render one mark per sample and the grid shows through.

Interpolating here instead is both smoother and more honest: a Gaussian-weighted
average is a stated method with a stated bandwidth, rather than a rendering
artefact that happens to look continuous.
"""

from __future__ import annotations

import io
from typing import Any

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter

# Working grid, in degrees per pixel. Finer than this only smooths noise that
# 5 km samples never contained.
RESOLUTION_DEGREES = 0.01

# Smoothing bandwidth in kilometres. Roughly one cell spacing: enough that
# neighbouring samples merge into a surface, small enough that a genuinely hot
# valley does not get averaged away by its neighbours.
BANDWIDTH_KM = 5.0
KM_PER_DEGREE = 111.0

# Alpha is driven by how much real data is near a pixel, so the Negev — where
# Copernicus publishes nothing — fades out instead of being invented.
COVERAGE_FLOOR = 0.12

# The GWIS/EFFIS legend, as (FWI value, RGB). Interpolating between these keeps
# the surface reading against the same legend the sidebar shows.
FWI_COLOR_STOPS: list[tuple[float, tuple[int, int, int]]] = [
    (0.0, (156, 255, 192)),
    (11.2, (205, 226, 78)),
    (21.3, (230, 172, 0)),
    (38.0, (217, 112, 16)),
    (50.0, (173, 6, 14)),
    (70.0, (88, 0, 21)),
]


def _color_ramp(values: np.ndarray) -> np.ndarray:
    """Map FWI values onto the legend ramp, one RGB triple per pixel."""
    stops = np.array([stop for stop, _ in FWI_COLOR_STOPS], dtype=float)
    colors = np.array([color for _, color in FWI_COLOR_STOPS], dtype=float)
    return np.stack(
        [np.interp(values, stops, colors[:, channel]) for channel in range(3)],
        axis=-1,
    )


def build_surface(
    features: list[dict[str, Any]],
    bounds: tuple[float, float, float, float],
    *,
    upscale: int = 3,
) -> bytes:
    """Render GeoJSON FWI points into a smoothed RGBA PNG covering `bounds`.

    Args:
        features: GeoJSON Point features carrying an `fwi` property.
        bounds: west, south, east, north of the output image.
        upscale: bicubic enlargement applied after smoothing, which costs
            almost nothing and spares the browser a visibly pixelated source.

    Returns:
        bytes: PNG data, fully transparent wherever no sample is close enough.
    """
    west, south, east, north = bounds
    width = max(1, int(round((east - west) / RESOLUTION_DEGREES)))
    height = max(1, int(round((north - south) / RESOLUTION_DEGREES)))

    # Two accumulators: the sum of values and the count of samples. Smoothing
    # both and dividing is what makes this a weighted average rather than a
    # blur — without it, edge pixels would be dragged toward zero simply
    # because they have fewer neighbours.
    totals = np.zeros((height, width), dtype=float)
    counts = np.zeros((height, width), dtype=float)

    for feature in features:
        longitude, latitude = feature["geometry"]["coordinates"]
        column = int((longitude - west) / RESOLUTION_DEGREES)
        # Image rows run north to south, hence the inversion.
        row = int((north - latitude) / RESOLUTION_DEGREES)
        if 0 <= row < height and 0 <= column < width:
            totals[row, column] += float(feature["properties"]["fwi"])
            counts[row, column] += 1.0

    sigma = BANDWIDTH_KM / KM_PER_DEGREE / RESOLUTION_DEGREES
    smooth_totals = gaussian_filter(totals, sigma=sigma, mode="constant")
    smooth_counts = gaussian_filter(counts, sigma=sigma, mode="constant")

    with np.errstate(invalid="ignore", divide="ignore"):
        values = np.where(smooth_counts > 0, smooth_totals / smooth_counts, 0.0)

    rgb = _color_ramp(values)

    # Coverage normalised against a fully surrounded pixel, so alpha falls off
    # only at the true edge of the data.
    coverage = smooth_counts / max(smooth_counts.max(), 1e-9)
    alpha = np.clip((coverage - COVERAGE_FLOOR) / (1.0 - COVERAGE_FLOOR), 0.0, 1.0)

    rgba = np.dstack([rgb, alpha * 255.0]).astype(np.uint8)
    image = Image.fromarray(rgba, mode="RGBA")

    if upscale > 1:
        image = image.resize(
            (width * upscale, height * upscale), Image.BICUBIC
        )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
