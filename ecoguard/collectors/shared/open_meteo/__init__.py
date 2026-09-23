"""Everything that talks to Open-Meteo.

One provider, one client, one rate limiter. `observations` writes closed past
hours and `forecast` writes hours that have not happened yet, but they share
the same endpoint, the same eleven variables and the same pacing state — so
they share a package, and a change to the provider's API is one edit here
rather than three across the tree.
"""
