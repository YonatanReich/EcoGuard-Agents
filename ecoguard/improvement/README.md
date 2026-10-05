# Improvement

How the system learns whether it is any good.

When an operator finishes with an incident they mark it **handled** on the
dashboard. That closes the incident and freezes a snapshot of everything they
saw (the evidence, the event details, the response plan) into
`operator_feedback`, together with their answers to a short survey: was it
real, how accurate were the plan and the details, and what was missing.
Skipping the survey still writes the row. The dashboard's **Feedback** button
writes free text about the system as a whole into the same table
(`kind = 'general'`, no incident, no snapshot).

Once a day the **improvement agent** reads the feedback nobody has reported on
yet, investigates it with read-only tools (the snapshots, counted trends, the
source code, git history and its own earlier reports), and writes a report for
the developers into `improvement_reports`. The System page shows the latest
report, and it can be saved as a PDF from there.

## What is here

| File | What it does |
|---|---|
| `feedback.py` | The survey's shape, and which commit the backend is running |
| `agent.py` | When a report is due, the agent loop, and the report's shape |
| `tools.py` | The agent's tools, confined to read-only access |

Storage is in `database/repositories/operator_feedback.py`; the handled
endpoint is `POST /api/events/{id}/handled`, general feedback is
`POST /api/improvement/feedback`, and the report is
`GET /api/improvement/reports/latest`.

## Things worth knowing

The agent never changes anything. It reports; developers decide.

Set `ECOGUARD_CODE_VERSION` to the deployed commit on hosts without a `.git`
directory (the container image has none). Without it feedback rows carry no
commit, and the agent cannot tie a change in the numbers to a change in the
code. `git_log` is likewise unavailable there.

It respects the pipeline switch: a paused pipeline makes no model calls, and
that includes this one.
