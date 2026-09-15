# analyzers/non_emergency/

Advisory hazards include air pollution, low Kinneret water level, and
extreme-heat days: conditions people should know about but that dispatch
nobody. Air Pollution analysis lives in `air_pollution/`.

The distinction from `emergency/` is the response, not the severity. These
analyzers produce advisory evidence rather than emergency incident assessments
and never allocate emergency resources. Air Pollution has a protocol-grounded
non-emergency recommendation planner, but no `resource_allocator/` counterpart.
