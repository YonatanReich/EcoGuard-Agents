"""The Canadian Fire Weather Index system, computed rather than fetched.

`index` is the pure Van Wagner & Pickett arithmetic; `collector` walks it
forward one day at a time over stored weather.

The only collector here with no provider. Its three moisture codes are
accumulators — each day is computed from the day before — which is why its rows
are never pruned and why a missed day is a broken chain rather than a gap.
"""
