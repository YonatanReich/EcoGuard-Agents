# Historical Air Pollution Scenario — 11 May 2024

## Purpose

This scenario demonstrates how EcoGuard would process a real historical air-pollution episode using the same production detection, qualification, analysis, publication, and response-planning pipeline used for live data.

The scenario does not insert a prepared incident or event. It replays historical source inputs in an isolated PostgreSQL schema and lets EcoGuard generate the result.

## Historical event

On 11 May 2024, Israel experienced a widespread particulate-pollution episode associated with transported dust from North Africa. EcoGuard represents the event through measured particulate matter, specifically PM10, rather than through a separate pollutant called “dust.”

The replay uses two authentic five-minute Ministry measurements from the Haifa area at 10:45 local time:

| Station | Identity | PM10 measurement | Current May/hour p95 |
|---|---|---:|---:|
| Neve Shaanan | station 86, channel 15 | 816.2 µg/m³ | 72.5 µg/m³ |
| Nesher | station 87, channel 15 | 773.4 µg/m³ | 77.805 µg/m³ |

Both stations are in the same EcoGuard service-grid cell. Each reading independently exceeds its active historical p95 baseline.

## What EcoGuard demonstrated

The normal pipeline:

1. read and validated both historical Ministry observations;
2. retrieved the current active station/channel baselines;
3. detected two independent PM10 anomalies using the unchanged `value > p95` rule;
4. correlated the signals and qualified the event through production Path A using two distinct stations;
5. applied the normal official-classification and publication policy;
6. analyzed historical wind, possible transport direction, nearby towns, and population context;
7. retrieved reviewed Air Pollution protocols; and
8. produced grounded public-health and monitoring recommendations with verified citations.

The completed run created one Air Pollution advisory in `/api/events` and the Dashboard. It remained a non-emergency advisory and created no emergency-resource allocation.

## Historical evidence and limitations

The original 2024 Ministry `indexFastSrv` response is no longer available from the provider. The scenario therefore uses clearly labelled reconstructed official-index evidence derived from 288 original Ministry five-minute PM10 measurements. The existing parser, exact station/channel/pollutant matcher, averaging-window validation, classification, and publication policy still run normally.

Historical wind comes from the measured LLHA/Haifa Airport METAR at 07:50 UTC. Because this reading is 55 minutes before the PM10 observations, the scenario declares a documented 60-minute historical-wind freshness window; the production corridor, town, and population algorithms remain unchanged.

PM10 trend prediction is reported as unavailable because the current production model manifest has no accepted PM10 trend model. This limitation does not block detection, qualification, publication, spatial analysis, or planning.

The event is evaluated retrospectively against EcoGuard’s current active 2021–2025 baselines. The scenario therefore demonstrates how the current EcoGuard pipeline evaluates the historical observations, not which baseline version was deployed in May 2024.

## Supervisor summary

EcoGuard replayed authentic historical PM10 observations inside an isolated demo schema without seeding a final event or weakening detection thresholds. The real production pipeline detected and corroborated the episode, published an advisory, added spatial and population context, disclosed unavailable or reconstructed evidence, and produced protocol-grounded recommendations.
