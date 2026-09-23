# Database

Everything that talks to PostgreSQL.

## What is here

| Folder or file | What it does |
|---|---|
| `engine.py` | The connection pool, and the switch that points a demo run at an isolated schema |
| `repositories/` | One module per table or subject: the only place SQL is written |
| `migrations/` | Ordered, versioned schema changes applied with Alembic |
| `locks.py` | Stops two processes doing the same job at the same time |

## Things worth knowing

Nothing outside `repositories/` writes SQL. That is what makes it possible to
point the whole system at a sandbox schema without touching a single query.

The locks are scoped per sandbox, so a demo run and the live pipeline cannot
block each other even though they share a database.
