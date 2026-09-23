# Remove the National Fire-Risk Scan

## Objective

Remove the national fire-risk scan completely while preserving the point-in-time
fire-risk API:

```http
POST /api/fire-risk
```

After this change, the application must no longer:

- expose `GET /api/fire-risk/national-scan`;
- calculate national risk snapshots at API startup or on a timer;
- persist national scan or refresh-status JSON files;
- poll for a national scan from the dashboard;
- display national high-risk alerts, clusters, or national risk cells on the map;
- expose a command-line entry point for creating a national snapshot.

The point-risk endpoint must continue to build the same 44-feature payload for
one coordinate and return the same `FireRiskResponse` contract.

## 1. Remove national-scan wiring from the FastAPI application

Update `ecoguard/api/main.py`.

Remove these imports:

```python
from ecoguard.analyzers.fire.refresh_orchestrator import CurrentRiskRefreshOrchestrator
from ecoguard.analyzers.fire.national_scan import NationalCurrentRiskScanService
```

Remove `NationalRiskScanResponse` from the import from
`ecoguard.api.fire_risk_schemas`.

Remove the national service and refresh-orchestrator instances:

```python
national_risk_scan_service = NationalCurrentRiskScanService()
current_risk_refresh = CurrentRiskRefreshOrchestrator(
    scan_service=national_risk_scan_service,
)
```

Remove the refresh lifecycle calls from `lifespan`:

```python
current_risk_refresh.start()
current_risk_refresh.stop()
```

Remove the complete endpoint:

```python
@app.get("/api/fire-risk/national-scan", response_model=NationalRiskScanResponse)
def national_fire_risk_scan(...):
    ...
```

Do not change the construction of these point-risk dependencies:

```python
current_risk_feature_builder = CurrentRiskFeatureBuilder()
fire_risk_prediction_agent = FireRiskPredictionAgent()
```

Do not change `assess_fire_risk` or its route:

```python
@app.post("/api/fire-risk", response_model=FireRiskResponse)
```

## 2. Remove national response schemas

Update `ecoguard/api/fire_risk_schemas.py`.

Delete these national-only models:

- `NationalRiskCell`
- `NationalUnavailableCell`
- `NationalRiskScanSummary`
- `NationalRiskScanResponse`

Keep these point-risk models unchanged:

- `FireRiskRequest`
- `CurrentRiskResponse`
- `FireRiskResponse`

## 3. Delete the national backend implementation

Delete these files:

- `ecoguard/analyzers/fire/national_scan.py`
- `ecoguard/analyzers/fire/refresh_orchestrator.py`
- `ecoguard/scripts/run_national_current_risk_scan.py`

This removes:

- enumeration of every active grid cell;
- service-area filtering for national scans;
- bulk feature construction for all cells;
- parallel national predictions;
- snapshot and refresh-status persistence;
- periodic background refreshes;
- overlap protection for national refreshes;
- the standalone national-scan command.

## 4. Preserve the point-risk implementation

The following backend code is still required by `POST /api/fire-risk` and must
not be deleted:

- `ecoguard/analyzers/fire/feature_builder.py`
- `ecoguard/analyzers/fire/risk_prediction_agent.py`
- `ecoguard/analyzers/fire/static_feature_store.py`
- `ecoguard/database/repositories/weather_history.py`
- the generated static grid database, normally `fire_risk_grid.sqlite`;
- the trained model artifact;
- the fire-risk thresholds and calibration metadata;
- historical FIRMS inputs used to build prior-fire features.

`CurrentRiskFeatureBuilder.build(latitude, longitude)` still needs the static
grid to map a coordinate to a cell. It also needs `hourly_for_cell` to read the
preceding weather window from PostgreSQL.

### Optional internal cleanup

`StoredWeatherFeatures.window` exists to preload weather for many cells during a
national scan. After removing the national scan, this context manager is no
longer used and may be removed.

`hourly_for_cells` is also national-scan-oriented, but `hourly_for_cell`
currently delegates to it:

```python
return hourly_for_cells([cell_id], start, end)[cell_id]
```

Therefore, do not delete `hourly_for_cells` unless `hourly_for_cell` is first
rewritten as a correct single-cell query. Keeping the bulk helper is safe and
does not cause background work by itself.

Comments and docstrings in `feature_builder.py` and `weather_history.py` that
describe national-scan bulk loading should be updated if the corresponding
bulk interfaces are removed or generalized.

## 5. Remove national-scan behavior from the dashboard

Update `ecoguard/frontend/src/pages/Dashboard.tsx`.

Remove these imports:

```typescript
import FireRiskLayer from '../components/layers/FireRiskLayer'
import FireRiskAlert from '../components/FireRiskAlert'
import { clusterHighRiskCells, type FireRiskCluster } from '../components/fireRiskClusters'
import { normalizeNationalRiskScanResponse, type NationalRiskScan } from '../components/fireRiskScan'
```

Remove the national-risk state:

- `nationalRiskScan`
- `nationalRiskError`
- `focusedFireRiskCluster`
- `dismissedFireRiskSnapshot`

Remove the effect that calls `/api/fire-risk/national-scan` at mount time and
every five minutes. This includes its `AbortController`, interval, request
guard, response normalization, and error handling.

Remove:

- the `highRiskClusters` memo;
- `viewHighRiskOnMap`;
- the `<FireRiskAlert>` render block;
- the `<FireRiskLayer>` render block.

Leaving the polling effect in place after deleting the endpoint would produce
an immediate `404` and another failed request every five minutes.

## 6. Delete national-only frontend modules

After removing all imports from `Dashboard.tsx`, delete:

- `ecoguard/frontend/src/components/fireRiskScan.ts`
- `ecoguard/frontend/src/components/fireRiskClusters.ts`
- `ecoguard/frontend/src/components/FireRiskAlert.tsx`
- `ecoguard/frontend/src/components/layers/FireRiskLayer.tsx`
- `ecoguard/frontend/src/components/layers/fireRiskClipping.ts`

Before deletion, confirm with a repository-wide search that none of these
modules has gained another consumer.

The incident-specific fire spread layer is unrelated and must remain:

- `ecoguard/frontend/src/components/layers/FireSpreadLayer.tsx`

Likewise, do not remove fire incident cards, detected-fire analysis, or resource
allocation UI. Those features do not depend on the national scan.

## 7. Update the system description shown in the frontend

Update the `analyzer.fire` entry in
`ecoguard/frontend/src/pages/systemActors.ts`.

Remove statements that say the fire analyzer:

- scores national fire risk;
- keeps the national fire-risk picture current;
- scores every map cell;
- runs a national refresh on its own timer.

Keep its detected-fire responsibilities, such as spread analysis, affected
settlements, protocol-grounded assessment, and response planning.

Also correct or remove the stale `wiredTo` value that points to the refresh
orchestrator being deleted.

## 8. Remove national-scan tests

Delete these test modules because their production targets will no longer
exist:

- `ecoguard/tests/analyzers/test_national_scan.py`
- `ecoguard/tests/analyzers/test_refresh_orchestrator.py`

Do not remove tests for:

- `FireRiskPredictionAgent`;
- point feature construction;
- calibration and thresholds;
- `POST /api/fire-risk` if endpoint-level tests exist or are added.

Add or retain a focused API regression test that verifies:

1. `POST /api/fire-risk` still accepts latitude and longitude.
2. A valid feature payload still returns `available` with a score and level.
3. Missing runtime inputs still return the structured `unavailable` result.
4. `GET /api/fire-risk/national-scan` now returns `404`.
5. `/openapi.json` no longer advertises the national route but still advertises
   `POST /api/fire-risk`.

## 9. Update documentation

Update `ecoguard/docs/fire_risk_backend_api.md`:

- remove the entire **National Current Risk scan** section;
- remove the **Periodic refresh** section;
- remove snapshot, national-cell, unavailable-cell, refresh cadence, and
  freshness metadata descriptions;
- retain and review the **Point Current Risk** section.

Update `ecoguard/analyzers/fire/README.md`:

- remove `national_scan.py` and `refresh_orchestrator.py` from the component
  list;
- replace “scores conditions nationwide on the 5 km grid” with wording that
  describes point current-risk evaluation;
- preserve the distinction between predicted current risk and operational risk
  for a detected fire.

Run a repository-wide search for the following terms and update any remaining
user-facing references:

```text
/api/fire-risk/national-scan
NationalRiskScanResponse
NationalCurrentRiskScanService
CurrentRiskRefreshOrchestrator
national current risk
national fire risk
national scan
current_risk_refresh
```

Comments that explain the retained static grid or point-risk features should
not be removed merely because they mention grid cells.

## 10. Remove generated national snapshot artifacts

If present locally or in deployment persistence, remove the generated files:

- `national_current_risk_scan.json`
- `national_current_risk_scan.json.tmp`
- `fire_risk_refresh_status.json`
- `fire_risk_refresh_status.json.tmp`

These are runtime artifacts, not database records. Their removal requires no
database migration.

Do not delete `fire_risk_grid.sqlite`; the point-risk endpoint still uses it.

## 11. Configuration cleanup

Remove `FIRE_RISK_REFRESH_INTERVAL_MINUTES` from environment examples,
deployment settings, and secrets/configuration management if it is configured
outside the repository.

No Python or frontend dependency appears to exist solely for the national scan:
the ML, SQLite, React, and map libraries remain in use elsewhere. Dependency
removal should therefore be based on a full usage check, not on this feature
removal alone.

## 12. Database impact

No PostgreSQL migration is required.

The national scan reads weather observations but does not own their schema.
Those observations are still used by point risk and other application paths.
Do not remove or truncate observation data.

The national scan writes JSON snapshots to the filesystem, not national-scan
rows to PostgreSQL.

## 13. Verification checklist

Run the following checks after implementation.

### Static reference check

Confirm there are no remaining runtime references to the removed feature:

```powershell
rg -n "national-scan|NationalRiskScan|NationalCurrentRiskScanService|CurrentRiskRefreshOrchestrator|current_risk_refresh" ecoguard
```

Any remaining match should be intentional documentation of the removal, not an
import or executable path.

### Backend tests

Run the point-risk and related fire-risk tests, then the full backend suite:

```powershell
.\venv\Scripts\python.exe -m pytest ecoguard\tests\analyzers\test_risk_prediction_agent.py -q
.\venv\Scripts\python.exe -m pytest -q
```

If there is a dedicated point-risk API test module, include it in the targeted
run.

### Frontend checks

From `ecoguard/frontend`, run the configured validation commands, normally:

```powershell
npm run lint
npm run build
```

Confirm that there are no unused imports, missing modules, or type errors.

### API behavior

With the backend running, verify:

```text
POST /api/fire-risk                 remains available
GET  /api/fire-risk/national-scan   returns 404
```

Also verify that the OpenAPI documentation contains the point endpoint and no
longer contains the national endpoint.

### Runtime behavior

Confirm that:

- API startup no longer creates a `current-risk-refresh` thread;
- startup no longer triggers a national model pass;
- no national snapshot or refresh-status file is recreated;
- the dashboard makes no request to `/api/fire-risk/national-scan`;
- the dashboard shows no national high-risk banner or national risk-cell map;
- detected-fire analysis and `POST /api/fire-risk` still work normally.

## Definition of done

The removal is complete when all of the following are true:

- `GET /api/fire-risk/national-scan` is absent from FastAPI and OpenAPI;
- no national refresh thread starts;
- no national scan can be launched through the application or the deleted CLI;
- national snapshot artifacts are no longer produced;
- the frontend no longer polls, renders, or describes national fire risk;
- national-only schemas, modules, tests, and documentation are removed;
- no database migration or observation deletion was performed;
- `POST /api/fire-risk` retains its request and response contract and passes its
  regression tests.
