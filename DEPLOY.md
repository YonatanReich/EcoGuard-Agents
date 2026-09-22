# Getting EcoGuard off localhost

Three services, none of them a machine you manage:

- **Neon** — the database. Already done; nothing to move.
- **Railway** — the API and the scheduler. One container, always on.
- **Vercel** — the frontend.

Backend first, so the frontend gets deployed once with a real API URL instead
of twice.

## Cost

Railway Hobby is **$5/month**, not a one-off — it is a server that runs
continuously, which is the thing your scheduler needs. Vercel and Neon you
already pay for.

---

## Phase 0 — Before deploying

1. **Kill the stale local instances.** Two uvicorn processes have been running
   since 17 September on pre-fix code, both writing to the same Neon database
   you are about to point Railway at.

       Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
         Where-Object { $_.CommandLine -match '--port 807' } |
         ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

2. **Commit everything.** Railway builds from git, so uncommitted means
   undeployed. That includes the two token fixes still sitting in the working
   tree: the classifier bookmark in `ecoguard/detectors/text/classifier.py` and
   the plan-freshness gate in `ecoguard/coordinator/dispatcher.py`.

---

## Phase 1 — Backend on Railway

1. New project → Deploy from GitHub repo. Railway finds the `Dockerfile` and
   uses it; no build configuration to write.
2. Paste these into Variables, same values as your local `.env`:

       DATABASE_URL            Neon connection string — the only hard requirement
       DEMO_DATABASE_URL       Neon, demo project
       ANTHROPIC_API_KEY
       ANTHROPIC_WORKSPACE_ID   optional; only workspace-scoped keys need it
       NASA_FIRMS_API_KEY
       NOMINATIM_BASE_URL
       NOMINATIM_USER_AGENT

   Do **not** set `ECOGUARD_DEV_ENDPOINTS` — it exposes
   `POST /api/dev/run/{source}`, which runs a collector on demand.

   Do **not** set `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` yet. The session path
   in `ecoguard/collection/shared/telegram/session.py` is built from
   `LOCALAPPDATA`, which only exists on Windows, and the authorised session
   lives on your laptop. With the credentials set, the collector is scheduled
   and fails every five minutes; without them it is simply not registered. Getting
   Telegram onto the server needs a string session passed in an environment
   variable instead of a file.

   `PORT` is injected by Railway; the `Dockerfile` already reads it.

3. Settings → Networking → **Generate Domain**. That gives you an HTTPS URL
   with a managed certificate. Keep it for Phase 2.

4. **Replicas: 1.** This is the one setting that matters. The scheduler is
   built at import time in `ecoguard/scheduler.py`, so every replica gets its
   own full set of fourteen timers — and its own model calls over the same
   messages, because `classify_new_text()` runs before the coordinator takes
   its advisory lock. Scale the instance, never the count.

No migration step: Neon is already at head. It is the same database your
laptop has been writing to.

---

## Phase 2 — Frontend on Vercel

1. New project from the same repo.
2. **Root Directory: `ecoguard/frontend`.** Everything else is inferred from
   `vercel.json`.
3. Environment variable: `VITE_MAPBOX_KEY`. A `pk.*` token is public by design
   and ships in the bundle.
4. Edit the rewrite destination in `ecoguard/frontend/vercel.json` to your
   Railway URL, commit, deploy.

The URL is hardcoded there on purpose: Vercel does not interpolate environment
variables into `vercel.json`, and a rewrite keeps the browser on one origin, so
the fourteen `fetch('/api/...')` calls in `src/` need no changes and CORS never
enters the picture.

---

## Phase 3 — Verify, then stop using localhost

1. The dashboard loads and populates from the Railway API.
2. Fresh rows are arriving — the scheduler is ticking:

       SELECT source, max(started_at) FROM collector_runs GROUP BY 1 ORDER BY 2 DESC;

3. **Exactly one scheduler.** Nothing on your laptop should still be writing to
   Neon.
4. Stop running uvicorn locally. For frontend work, point the vite dev proxy in
   `vite.config.ts` at the Railway URL instead of `127.0.0.1:8000`.

---

## Known gap, pre-existing

`/api/fire-risk` and the national risk scan already fail on localhost —
`fire_risk_refresh_status.json` reports `NationalRiskScanError`, because both
`fire_prediction_landcover_terrain_model.joblib` and `fire_risk_grid.sqlite`
are absent from disk and gitignored at `.gitignore:58`.

Hosting neither causes nor fixes this. Those endpoints will report unavailable
on Railway exactly as they do now. To fix it, build both artefacts and commit
them, or serve them from storage the container can reach.
