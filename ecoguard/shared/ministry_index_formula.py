"""The Ministry of Environmental Protection's air-quality index, computed from readings.

Transcribed from the Ministry's own method document, "חישוב מדד איכות האוויר"
(air.sviva.gov.il, updated 28/02/2022): index = 100 - AQI, where AQI is a
linear interpolation between the breakpoints of its table 3. Particulates use
the rolling 24-hour average. Used only where the provider no longer serves the
index it published - it purges `indexFastSrv` after some months while keeping
the raw readings - and every value computed here is labelled as reconstructed.
"""

from __future__ import annotations

# (concentration low, concentration high, AQI low, AQI high), table 3.
BREAKPOINTS: dict[str, tuple[tuple[float, float, float, float], ...]] = {
    "PM10": (
        (0, 65, 0, 49), (66, 129, 50, 100), (130, 215, 101, 200),
        (216, 300, 201, 300), (301, 355, 301, 400), (356, 430, 401, 500),
    ),
    "PM2.5": (
        (0, 18.5, 0, 49), (18.6, 37, 50, 100), (37.5, 84, 101, 200),
        (84.5, 130, 201, 300), (130.5, 165, 301, 400), (165.5, 200, 401, 500),
    ),
}

# Table 2: particulates are judged on the rolling 24-hour mean.
AVERAGING_MINUTES = {"PM10": 1440, "PM2.5": 1440}


def aqi(pollutant: str, concentration: float) -> float:
    """Formula [2]. Gaps between bands go to the next band; above the table caps at 500."""
    bands = BREAKPOINTS[pollutant]
    for low, high, aqi_low, aqi_high in bands:
        if concentration <= high:
            concentration = max(concentration, low)
            return (aqi_high - aqi_low) * (concentration - low) / (high - low) + aqi_low
    return 500.0


def index(pollutant: str, concentration: float) -> float:
    """Formula [1]: the published index, +100 (clean) down to -400.

    Whole numbers, as the Ministry publishes them. Checked against its
    published index for four stations on 4 Oct 2026: the 24-hour means match
    exactly and the index to within one point (its rounding is not stated).
    """
    return float(round(100.0 - aqi(pollutant, concentration)))
