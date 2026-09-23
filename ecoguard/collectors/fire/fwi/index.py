"""The fire-weather index itself: moisture, spread and intensity.

Standard published formulas, kept separate from the collector so they can be
checked against worked examples without touching the database."""

from __future__ import annotations

import math
from dataclasses import dataclass

# Effective day length by month, used by DMC. Northern hemisphere.
DAY_LENGTH = (6.5, 7.5, 9.0, 12.8, 13.9, 13.9, 12.4, 10.9, 9.4, 8.0, 7.0, 6.0)

# Day-length adjustment by month, used by DC. Northern hemisphere.
DAY_LENGTH_ADJUSTMENT = (-1.6, -1.6, -1.6, 0.9, 3.8, 5.8, 6.4, 5.0, 2.4, 0.4, -1.6, -1.6)

# Where the codes start when there is no previous day to carry forward. These
# are the standard spring startup values: moist fine fuels, and little
# accumulated drought. They are wrong on day one by construction — FFMC
# converges within a few days, DMC within weeks, DC not for months, which is
# why the first season of DC should be read as warming up rather than as truth.
STARTUP_FFMC = 85.0
STARTUP_DMC = 6.0
STARTUP_DC = 15.0

# EFFIS/JRC danger classes, so our own FWI is directly comparable to the band
# the fire_weather collector stores from their raster. Upper bounds, ascending.
DANGER_CLASSES = (
    (5.2, "very_low"),
    (11.2, "low"),
    (21.3, "moderate"),
    (38.0, "high"),
    (50.0, "very_high"),
    (math.inf, "extreme"),
)


@dataclass(frozen=True)
class FireWeatherState:
    """One day's six numbers. The three codes are also the next day's input."""

    ffmc: float
    dmc: float
    dc: float
    isi: float
    bui: float
    fwi: float

    @property
    def danger_class(self) -> str:
        """The published danger band this index value falls in."""
        return next(name for bound, name in DANGER_CLASSES if self.fwi < bound)

    def as_payload(self) -> dict[str, float | str]:
        """The index and its parts, in the shape stored on an observation."""
        return {
            "ffmc": round(self.ffmc, 2),
            "dmc": round(self.dmc, 2),
            "dc": round(self.dc, 2),
            "isi": round(self.isi, 2),
            "bui": round(self.bui, 2),
            "fwi": round(self.fwi, 2),
            "danger_class": self.danger_class,
        }


def _fine_fuel_moisture(previous_ffmc: float, temperature: float, humidity: float,
                        wind: float, rain: float) -> float:
    """FFMC: the fine dead fuel moisture code, 0-101. Higher is drier."""
    moisture = 147.2 * (101.0 - previous_ffmc) / (59.5 + previous_ffmc)

    if rain > 0.5:
        effective = rain - 0.5
        moisture += (
            42.5 * effective
            * math.exp(-100.0 / (251.0 - moisture))
            * (1.0 - math.exp(-6.93 / effective))
        )
        if moisture > 150.0:
            moisture += 0.0015 * (moisture - 150.0) ** 2 * math.sqrt(effective)
        moisture = min(moisture, 250.0)

    equilibrium_dry = (
        0.942 * humidity ** 0.679
        + 11.0 * math.exp((humidity - 100.0) / 10.0)
        + 0.18 * (21.1 - temperature) * (1.0 - math.exp(-0.115 * humidity))
    )

    if moisture > equilibrium_dry:
        rate = (
            0.424 * (1.0 - (humidity / 100.0) ** 1.7)
            + 0.0694 * math.sqrt(wind) * (1.0 - (humidity / 100.0) ** 8)
        )
        moisture = equilibrium_dry + (moisture - equilibrium_dry) * 10.0 ** (
            -rate * 0.581 * math.exp(0.0365 * temperature)
        )
    else:
        equilibrium_wet = (
            0.618 * humidity ** 0.753
            + 10.0 * math.exp((humidity - 100.0) / 10.0)
            + 0.18 * (21.1 - temperature) * (1.0 - math.exp(-0.115 * humidity))
        )
        if moisture < equilibrium_wet:
            rate = (
                0.424 * (1.0 - ((100.0 - humidity) / 100.0) ** 1.7)
                + 0.0694 * math.sqrt(wind) * (1.0 - ((100.0 - humidity) / 100.0) ** 8)
            )
            moisture = equilibrium_wet - (equilibrium_wet - moisture) * 10.0 ** (
                -rate * 0.581 * math.exp(0.0365 * temperature)
            )

    return min(101.0, max(0.0, 59.5 * (250.0 - moisture) / (147.2 + moisture)))


def _duff_moisture(previous_dmc: float, temperature: float, humidity: float,
                   rain: float, month: int) -> float:
    """DMC: loosely compacted organic layer. Unbounded above; higher is drier."""
    temperature = max(temperature, -1.1)
    drying = (
        1.894 * (temperature + 1.1) * (100.0 - humidity)
        * DAY_LENGTH[month - 1] * 0.0001
    )

    if rain <= 1.5:
        return previous_dmc + drying

    effective = 0.92 * rain - 1.27
    moisture = 20.0 + 280.0 / math.exp(0.023 * previous_dmc)
    if previous_dmc <= 33.0:
        slope = 100.0 / (0.5 + 0.3 * previous_dmc)
    elif previous_dmc <= 65.0:
        slope = 14.0 - 1.3 * math.log(previous_dmc)
    else:
        slope = 6.2 * math.log(previous_dmc) - 17.2
    wetted = moisture + 1000.0 * effective / (48.77 + slope * effective)
    return max(0.0, 43.43 * (5.6348 - math.log(wetted - 20.0))) + drying


def _drought_code(previous_dc: float, temperature: float, rain: float, month: int) -> float:
    """DC: deep compact organic matter. The system's months-long memory."""
    temperature = max(temperature, -2.8)
    evaporation = max(0.0, (0.36 * (temperature + 2.8) + DAY_LENGTH_ADJUSTMENT[month - 1]) / 2.0)

    if rain <= 2.8:
        return previous_dc + evaporation

    effective = 0.83 * rain - 1.27
    moisture = 800.0 * math.exp(-previous_dc / 400.0)
    return max(0.0, previous_dc - 400.0 * math.log(1.0 + 3.937 * effective / moisture)) + evaporation


def _spread_index(ffmc: float, wind: float) -> float:
    """ISI: how fast fire would spread, from fine fuel moisture and wind."""
    moisture = 147.2 * (101.0 - ffmc) / (59.5 + ffmc)
    fine_fuel = 91.9 * math.exp(-0.1386 * moisture) * (1.0 + moisture ** 5.31 / 49_300_000.0)
    return 0.208 * math.exp(0.05039 * wind) * fine_fuel


def _buildup_index(dmc: float, dc: float) -> float:
    """BUI: total fuel available to the fire, from the two slower codes."""
    if dmc <= 0.0:
        return 0.0
    if dmc <= 0.4 * dc:
        return max(0.0, 0.8 * dmc * dc / (dmc + 0.4 * dc))
    return max(
        0.0,
        dmc - (1.0 - 0.8 * dc / (dmc + 0.4 * dc)) * (0.92 + (0.0114 * dmc) ** 1.7),
    )


def _fire_weather_index(isi: float, bui: float) -> float:
    """FWI: the headline number, and the only one EFFIS's band reflects."""
    if bui <= 80.0:
        severity = 0.1 * isi * (0.626 * bui ** 0.809 + 2.0)
    else:
        severity = 0.1 * isi * (1000.0 / (25.0 + 108.64 / math.exp(0.023 * bui)))
    if severity <= 1.0:
        return severity
    return math.exp(2.72 * (0.434 * math.log(severity)) ** 0.647)


def advance(
    previous: FireWeatherState | None,
    *,
    temperature_c: float,
    humidity_percent: float,
    wind_speed_kmh: float,
    rain_24h_mm: float,
    month: int,
) -> FireWeatherState:
    """Step the system forward one day.

    Args:
        previous: yesterday's state, or None to start from the standard spring
            values. Only the three moisture codes carry over; ISI, BUI and FWI
            are recomputed from scratch each day.
        temperature_c: noon local standard time temperature.
        humidity_percent: noon local standard time relative humidity, 0-100.
        wind_speed_kmh: noon local standard time wind at 10 m.
        rain_24h_mm: precipitation accumulated over the preceding 24 hours.
        month: calendar month, 1-12, selecting the day-length factors.

    Returns:
        FireWeatherState: today's six numbers, and tomorrow's input.
    """
    if not 1 <= month <= 12:
        raise ValueError("month must be 1-12")
    humidity = min(100.0, max(0.0, humidity_percent))
    wind = max(0.0, wind_speed_kmh)
    rain = max(0.0, rain_24h_mm)

    ffmc = _fine_fuel_moisture(
        previous.ffmc if previous else STARTUP_FFMC, temperature_c, humidity, wind, rain
    )
    dmc = _duff_moisture(
        previous.dmc if previous else STARTUP_DMC, temperature_c, humidity, rain, month
    )
    dc = _drought_code(previous.dc if previous else STARTUP_DC, temperature_c, rain, month)

    isi = _spread_index(ffmc, wind)
    bui = _buildup_index(dmc, dc)
    return FireWeatherState(ffmc=ffmc, dmc=dmc, dc=dc, isi=isi, bui=bui,
                            fwi=_fire_weather_index(isi, bui))
