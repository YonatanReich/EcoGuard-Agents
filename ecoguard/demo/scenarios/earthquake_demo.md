# Earthquake Demo: Jezreel Valley, August 24, 1984

This demo replays one real earthquake from the Geological Survey of Israel (GSI) event catalogue. It runs the existing detection, coordination, impact analysis, response planning, resource allocation and routing pipeline over historical evidence stored in the dedicated `earthquake_demo` schema. No incident, response plan or allocation is pre-generated.

## What happened

On August 24, 1984, GSI recorded an earthquake at 06:02:25.358 UTC. In the catalogue record used here, the epicentre is on land in the Jezreel Valley, near Kfar Barooch, rather than in Lake Kinneret. GSI reports a magnitude of approximately 5.35 and a depth of 12 km.

These statements describe the selected catalogue solution. The input record does not contain reports of casualties, damaged buildings or road closures, and the demo makes no claims about those historical outcomes. Values from differently located or revised solutions in other catalogues are not mixed into this event.

## Evidence used in the demo

The input values come from the single FDSN text record returned by the [GSI event service](https://seis.gsi.gov.il/fdsnws/event/1/query?format=text&eventid=gsi198408240602), retrieved on October 4, 2026. They are embedded directly in `HISTORICAL_EVENT` in [`earthquake_demo.py`](earthquake_demo.py), rather than loaded from a separate data file.

| Field | Original catalogue value |
|---|---|
| Provider | GSI |
| Provider event ID | `gsi198408240602` |
| Origin time | `1984-08-24T06:02:25.358Z` |
| Latitude | `32.65079498` |
| Longitude | `35.19147491` |
| Depth | `12.0 km` |
| Magnitude | `5.347415924` |
| Magnitude type | `Md` |
| Event type | `earthquake` |

The seeder builds an observation from these embedded values in the production collector's payload structure and uses the operational grid lookup. The resulting cell is `risk-05000m-r0071-c0018`. The observation includes the epicentre as a geographic point and the normal `gsi_earthquake` source, and is inserted into the dedicated demo schema. Playback requires neither an external earthquake data file nor a live GSI request.

## Detection logic

The earthquake detector reads newly ingested GSI observations and emits a dashboard signal when magnitude is at least **3.5**. This event comfortably crosses that threshold. The signal retains the provider's coordinates, magnitude, depth and identifier; the coordinator and earthquake handler then process it normally.

This tests recognition of a published catalogue event. It does not replay station waveforms, measure how quickly GSI originally published the event, or demonstrate an alert before seismic waves arrived.

## Modelled shaking and why this location works

The current analyzer uses magnitude, depth and distance in its implementation of the Allen, Wald and Worden (2012) intensity relation. For this catalogue record it produces these approximate epicentral radii:

| Modelled intensity | Description | Radius from epicentre |
|---|---|---:|
| MMI VI | Strong shaking | 7.13 km |
| MMI V | Moderate shaking | 26.27 km |
| MMI IV | Light shaking | 58.49 km |

The modelled maximum intensity at the epicentre is approximately 6.2. These are screening estimates, not measured 1984 intensity contours or a historical damage survey. The model treats the source as a point and does not account for local soil amplification or building vulnerability. The magnitude type remains `Md`; the demo applies the production model as it currently handles GSI magnitudes, without a separate magnitude conversion.

Kfar Barooch and nearby settlements such as Ramat David, Gvat, Sarid, Ifat and Nahalal have reference centroids within roughly 0.6–4.4 km of this epicentre. This places populated land near the strongest modelled shaking. Actual settlement exposure in the run comes from the normal polygon intersection query, rather than from this illustrative centroid list.

The analyzer's **outer 58.49 km extent** includes light shaking; it is not a boundary within which every building is expected to be damaged. Population calculated for this area is geographic exposure, not a casualty estimate. The analyzer also estimates population at damaging intensity for the planner's risk context. This demo uses the existing earthquake interface without adding a map layer or changing its presentation.

## How the system could have helped

After receiving an official earthquake report, the system can assemble the location and modelled extent, identify settlements and population needing assessment, retrieve response protocols, propose actions and allocate nearby emergency service stations. Routing then requests travel routes to the response location.

This could support rapid assessment and response after the earthquake. The demo does not establish historical warning time, prove that particular actions would have prevented damage, or reproduce which responders were available in 1984.

## Historical time and schema isolation

At each start, the historical origin time is rebased to **five minutes before the demo start**, and ingestion time is set to the demo start. Both the observation timestamp and the payload's `observed_at` use that same rebased time. The original UTC timestamp, source URL and retrieval date remain in `payload.raw.demo_replay`. The embedded historical record is preserved when building each replay observation.

This lets the existing detector's ingestion window work without changing production freshness rules. All observation inserts explicitly target `earthquake_demo.observations`, and the seeder rejects any other schema, including `public`.

The demo sandbox also holds its own detector bookmarks, incidents, event projections, text candidates, allocations and weak events. While the API demo is active, live collectors are paused. Shared town, population, station and protocol reference data are still read normally. These references describe the currently available dataset, not a reconstruction of 1984. Ending a demo waits for any active wave to finish, restores live operation and keeps the sandbox data for inspection. Starting a fresh run replaces the previous sandbox run.

## Running the demo

With the backend and frontend running, open **Demo scenarios**, select **Earthquake Demo**, review the event and start it. A background detection wave begins immediately. On the dashboard, select the earthquake card to inspect the normal earthquake details and any response plan or allocated stations produced by the pipeline. Use **End Earthquake Demo** to return to live operation and request the score. Wait for the active wave to finish before ending the demo so the existing interface grades a completed run.

Alternatively, from the repository root with the project environment activated:

```powershell
python -m ecoguard.demo.run_once earthquake_demo --waves 2
```

The second wave lets you inspect whether previously ingested evidence is emitted again. To grade the saved output without running another wave:

```powershell
python -m ecoguard.demo.grade earthquake_demo
```

The CLI restores its live search path after the run. Use the API start flow to keep the dashboard in an active scenario. Avoid concurrently starting the same schema from the CLI and API.

## Prerequisites and expected results

The database must have the normal migrations, PostGIS and shared reference data. The seeder needs permission to create the demo schema and tables. Planning and routing use the project's normal configured model, protocol retrieval, station catalogue and routing services. They are not replaced by canned answers.

The scenario uses the existing grader without modifications. Its authored expectations specify an earthquake incident within 0.1 km of the GSI epicentre, an emergency route and at least one signal. The grader also applies its existing projection and planner checks. Extra incidents appear as unexplained results. There are no additional checks of catalogue fields, exact signal counts, allocation or routing completion in this scenario.

A missing external service can yield a **PARTIAL** result even when earthquake detection succeeds. The report lists the failed expectation instead of presenting an unfinished response as a full pass. Station identities and generated plan wording can vary with the current reference data and service output.

### Local verification, October 5, 2026

A real two-wave run persisted one observation, produced one earthquake incident and one event projection, and preserved a signal count of one. The second wave returned no new processing results. A separate query confirmed that no observation bearing this demo's replay metadata was present in `public.observations`.

Detection and impact analysis succeeded. With `ANTHROPIC_API_KEY` absent in the local configuration, the planner reported `missing_credentials`. The normal planning-failure policy nevertheless allocated Migdal HaEmek police station. Mapbox returned a driving route, but its destination was approximately 127.46 metres from the catalogue epicentre, beyond the configured 100-metre road-access tolerance. The route was correctly marked `partial_offroad`, with an unverified final access segment, rather than `complete`.

The existing grader reports the failed planner as a **PARTIAL** result; routing status remains available in the pipeline output. Configuring the normal planning credentials is necessary to demonstrate generated response actions. The off-road access condition is a property of this exact catalogue location. These observations describe the actual verification run; the demo adds no grading rules or changes to the normal routing behavior.

## Sources

- [GSI FDSN event record](https://seis.gsi.gov.il/fdsnws/event/1/query?format=text&eventid=gsi198408240602): the sole source for the historical event parameters.
- [`earthquake_demo.py`](earthquake_demo.py): replay and authored expectations.
- [`intensity.py`](../../analyzers/earthquake/intensity.py) and [`impact.py`](../../analyzers/earthquake/impact.py): the production shaking and exposure calculations used in this demo.
