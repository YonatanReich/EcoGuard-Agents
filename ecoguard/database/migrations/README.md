# Schema history

Every change the database has ever been through, in order. Applied with
`alembic upgrade head`.

A migration is never edited once it has run somewhere - the next change gets a
new one. `env.py` wires alembic to the project's connection settings;
`versions/` holds the steps themselves.
