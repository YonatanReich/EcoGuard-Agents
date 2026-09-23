# Queries

One module per table or subject. Every query the system makes lives in here,
and nothing outside this folder writes SQL.

That is the point: a query that is wrong is wrong in one place, and a caller
that wants data asks for what it wants rather than how to get it.

Files are named for what they answer - `towns.py`, `weather_history.py`,
`responsible_services.py` - and each one's own documentation says what makes it
worth a file of its own.
