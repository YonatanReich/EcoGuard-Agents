Annotation 1 I recommend testing through two complementary tracks:

1. **Live smoke tests** — use real data providers to validate collection, connectivity, persistence, and current real-world behavior.
2. **Controlled scenarios** — inject known test data that forces an event through the entire pipeline and into the frontend.

A quiet day without a fire, flood, or earthquake can verify that collection works, but it cannot validate analysis, planning, allocation, event projection, or frontend presentation.

## Common test-case format

| Field | What to record |
|---|---|
| Test ID | For example, `FLOOD-E2E-01` |
| Mode | Live / Controlled / Failure |
| Scenario | A short description of the event |
| Preconditions | Required keys, baselines, reference tables, and stored data |
| Input/trigger | Collector invoked and data injected |
| Collection | Whether valid observations were created |
| Detection | Whether a signal was emitted and why |
| Coordination | Whether an incident was created, merged, updated, or rejected |
| Analysis | Severity, risk, affected area, and population |
| Planning | Actions, units, citations, and limitations |
| Allocation | Stations, routes, shortages, and partial status |
| Projection/API | Correct appearance in `/api/events` or a dedicated endpoint |
| Frontend | Card, marker, layers, labels, colors, and interactions |
| Expected result | Predetermined values or ranges |
| Actual result | What the run produced |
| Status | Pass / Fail / Blocked / Not applicable |
| Evidence | JSON response, screenshot, incident ID, and timestamp |

Each hazard should include:

- **Happy path** — all services are available.
- **No-event path** — collection succeeds, but no event qualifies.
- **Degraded path** — a secondary provider, model, or routing service is unavailable.
- **Boundary test** — input immediately below, at, and above the activation threshold.
- **Deduplication test** — replaying the same observation does not create a duplicate incident.

## Five-hazard test matrix

| Hazard | Primary controlled scenario | Critical transition | Expected frontend result |
|---|---|---|---|
| Flood | Two consecutive readings above Q10, no more than 30 minutes apart | First reading does not alert; second creates a signal; later readings update the same incident | Return-period severity, risk, station and stream, road targets, allocated resources, and routes |
| Fire | FIRMS hotspot near a populated area with adverse weather, vegetation, and terrain | Hotspot detected; satellite duplicates merged; detection remains separate from risk assessment | Spread, exposure, risk score, response plan, protocol citations, stations, and routes |
| Earthquake | Shallow M4.6 earthquake near a settlement | Below M3.5 is hidden; M3.5 or higher is emitted; quarry explosions are excluded | Impact area, intensity rings, affected towns and population, risk, plan, and allocation |
| Air pollution | Abnormal reading at a station with an active baseline, supporting station, and wind data | Baseline resolved; anomaly qualified; official classification matched | Advisory, pollutant, value, station, trend, wind corridor, screened population, and recommendations |
| Kinneret level | Thirty-day series ending below the lower red line | Collection and persistence; band and trend calculation; no incident coordination | Current level, operating band, trend, threshold distances, and recommended action |

## Flood

Recommended boundary scenarios:

- One reading above Q10 → **no incident**.
- Two readings above Q10 within 30 minutes → incident created.
- Two readings more than 30 minutes apart → no incident.
- Transition from Q10 to Q20 or Q50 → the same incident is updated and escalated.
- Station containing `999` sentinel thresholds → ineligible for detection.
- Three hours without another qualifying reading → incident closes.

The expected behavior is documented in [the Flood detector README](C:/Users/danmo/Desktop/study/project/w/EcoGuard-Agents/ecoguard/detectors/flood/README.md).

## Fire

Use at least two controlled scenarios:

- A hotspot in an unpopulated area of the Negev.
- A comparable hotspot in the Carmel wildland–urban interface, with strong wind, burnable vegetation, and steep terrain.

This verifies that the system does more than detect a hotspot: it should produce materially different risk and response results based on exposure and environmental conditions.

Check that:

- Observations from multiple satellites are merged.
- Replaying the same hotspot does not create another incident.
- “No hotspots found” is distinguishable from a FIRMS provider failure.
- Analysis and planning contain verified protocol citations.
- Claude or Mapbox failure results in an honest partial status.
- Failed analysis produces `null` risk values rather than incorrectly reporting `low`.

## Earthquake

Important threshold tests:

- M3.4 → not shown on the dashboard.
- M3.5 → shown on the dashboard.
- M4.5 and M5.5 → larger impact radii and higher risk bands.
- M5 near a city versus M5 in an unpopulated area → different operational risk.
- Event marked as `explosion` → filtered out.
- Population grid unavailable → event remains visible, but population is explicitly unavailable.

The frontend visibility threshold is defined in [observation_processing.py](C:/Users/danmo/Desktop/study/project/w/EcoGuard-Agents/ecoguard/detectors/earthquake/observation_processing.py:13).

## Air pollution

Before testing, verify that the correct baseline family is active. Missing baseline data should produce an explicit “cannot assess” result, not a clean-air conclusion.

Test that:

- Normal reading → no advisory.
- Significant deviation from the baseline → candidate created.
- A nearby supporting station provides spatial corroboration.
- Fresh wind above the minimum speed → transport corridor and screened population are calculated.
- Old or weak wind → no corridor, with an explicit reason.
- The event remains an `advisory` and does not allocate police, MDA, or fire-service resources.
- Recommendations and citations appear only when planning succeeds.
- IMS failure does not erase the pollution anomaly; it only marks wind-dependent components unavailable.

## Kinneret level

This is different from the other four hazards. It does not pass through Detector → Coordinator → Incident. It is collected and converted directly into an advisory served by `/api/water-levels`.

Boundary tests:

- `-208.80 m` or higher → above the upper red line.
- Between `-208.80 m` and `-213.00 m` → normal operating range.
- Below `-213.00 m` → below the lower red line.
- `-214.87 m` or lower → below the black line.
- Only one reading → trend is not assessed.
- Several falling readings → annualized trend and estimated days to the black line.
- No stored readings → `status: unavailable`.
- Implausible value such as `-250 m` → collector fails and does not persist it.

The thresholds and actions are defined in [advisory.py](C:/Users/danmo/Desktop/study/project/w/EcoGuard-Agents/ecoguard/analyzers/water_level/advisory.py:28).

## Recommended manual execution order

In development only, enable `ECOGUARD_DEV_ENDPOINTS=1`, restart the backend, and invoke the collectors:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/dev/run/firms
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/dev/run/water_authority_hydrometric_observations
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/dev/run/gsi_earthquake
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/dev/run/air_pollution
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/dev/run/kinneret_level
```

For the four event-based hazards, run the detection cycle immediately instead of waiting for the scheduled interval:

```powershell
python -c "from ecoguard.scheduler import detect_and_coordinate; print(detect_and_coordinate())"
```

Then inspect the projected results:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/events
Invoke-RestMethod http://127.0.0.1:8000/api/water-levels
```

Finally, open the dashboard and verify that the same events appear correctly in the frontend.

For reliable end-to-end frontend testing, controlled scenarios should inject data at the **collection/observation boundary**, then run the real detector, coordinator, analyzer, planner, allocator, and projector. Mocking the final `/api/events` response may test the UI, but it does not test the complete pipeline.