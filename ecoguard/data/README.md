# data/

Content, not code.

- `reference/` — committed: the operational service-area polygon and the
  station rosters an alembic migration seeds from.
- `evaluation/` — committed hand-written planner cases. Inputs, not output,
  which is why they are not under `generated/`.
- `generated/` — gitignored. Rasters, SQLite caches, trained models, derived
  CSVs. Nothing here is a source of truth; everything is rebuildable by some
  script in `scripts/`.
- `israel_locations.json` — the predefined scan roster.

Never reference these by relative path. `ecoguard/paths.py` resolves them from
`__file__`, so code works regardless of the working directory.

The protocol corpus is deliberately *not* here — it lives next to the planner
that cites it, in `response_planner/protocols/`.
