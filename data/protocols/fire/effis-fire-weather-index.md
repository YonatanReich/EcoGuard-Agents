# Fire Weather Index (FWI) System and Fire Danger Classification

Source: Copernicus Emergency Management Service, European Forest Fire Information
System (EFFIS), Technical Background — Fire Danger Forecast.
Status: Copernicus open licence; free use with attribution.

This is the classification authority for the fire danger data this system already
collects. `FireDangerAgent` reads its `danger_level` and FWI bands from GWIS/EFFIS, so
the thresholds below are the same ones present in the detected-event evidence.

## What the Fire Weather Index Measures

The Fire Weather Index is the top-level output of the Canadian Forest Fire Weather Index
System, which EFFIS adopted in 2007 as the method to assess fire danger in a harmonised
way throughout Europe.

The FWI describes **fire weather conditions** — the meteorological potential for fire
ignition, spread, and difficulty of control. It is a measure of the environment's
receptiveness to fire, not a measure of whether a fire exists, how large it is, or what
is at stake. A high FWI with no ignition means dangerous conditions and no fire. A
detected fire under a low FWI is still a fire.

**The FWI must remain conceptually separate from the operational risk score.** Fire
weather severity is one input to operational risk, alongside satellite detection
evidence, fire intensity, and exposure of people and infrastructure.

## The Six Fire Danger Classes

The Fire Weather Index is mapped into six classes of danger:

| Danger class | FWI range |
| --- | --- |
| Low | below 11.2 |
| Moderate | 11.2 to 21.3 |
| High | 21.3 to 38.0 |
| Very high | 38.0 to 50.0 |
| Extreme | 50.0 to 70.0 |
| Very extreme | above 70.0 |

A finer split is sometimes used at the bottom of the scale: very low danger is FWI below
5.2, and low danger is FWI between 5.2 and 11.2.

The "Very Extreme" fire danger class was introduced in June 2021 to provide
discrimination about the level of fire danger in extensive areas that were initially
classified at "Extreme" fire danger in the Mediterranean region during the summer
months. The Very Extreme class includes areas with FWI values above 70.

## Interpreting the Classes Operationally

The classes are ordinal and the intervals are not equal in operational consequence. The
step from High to Very high, and again from Extreme to Very extreme, each represent
substantially greater difficulty of control rather than a proportional increase.

- **Low and Moderate.** Fire is possible but spread rates and intensity are generally
  within the capability of initial-attack resources.
- **High.** Conditions support rapid spread. Initial attack may fail. Fires escaping
  initial attack should be expected.
- **Very high and Extreme.** Conditions support fire behaviour that can exceed direct
  suppression capability. Direct attack on the head of the fire is frequently not
  viable. Priority shifts toward flank containment, point protection, and life safety.
- **Very extreme.** Reserved for the most severe observed conditions. Assume control
  efforts at the fire head will fail and plan around evacuation and defensible point
  protection.

## Components of the FWI System

The FWI System is built from sub-indices, each describing a different part of the fuel
and spread problem:

- **FFMC** — Fine Fuel Moisture Code. Moisture content of litter and other cured fine
  fuels. Governs ease of ignition and initial spread.
- **DMC** — Duff Moisture Code. Moisture content of loosely compacted organic layers of
  moderate depth.
- **DC** — Drought Code. Moisture content of deep, compact organic layers. A long-term
  drying indicator.
- **ISI** — Initial Spread Index. Combines wind and FFMC to express expected rate of
  spread.
- **BUI** — Buildup Index. Combines DMC and DC to express total fuel available for
  combustion.
- **FWI** — Fire Weather Index. Combines ISI and BUI into a single measure of fire
  intensity and general fire danger.

Wind enters the system principally through the ISI, which is why increasing wind speed
raises expected rate of spread even when fuel dryness is unchanged.

## Forecast Production

Fire danger forecasts use numerical weather forecasts from two deterministic models: the
ECMWF model at approximately 8 km resolution, and the MeteoFrance model. The ECMWF model
provides forecasts from 1 to 9 days ahead; MeteoFrance extends to 3 days ahead.

Two derived indicators provide local context:

- **Ranking**, which provides percentiles of occurrence of the values.
- **Anomaly**, computed as a standard deviation from the 40-year historical mean values.

An FWI value that is unremarkable in absolute terms may still represent a significant
local anomaly, and vice versa. Where ranking or anomaly data is unavailable, the
absolute class should be used and the absence noted.

## Attribution

Copernicus Emergency Management Service, European Forest Fire Information System
(EFFIS), "Fire Danger Forecast", Technical Background.
https://forest-fire.emergency.copernicus.eu/about-effis/technical-background/fire-danger-forecast

Contains modified Copernicus Emergency Management Service information. Neither the
European Commission nor ECMWF is responsible for any use of this information.
