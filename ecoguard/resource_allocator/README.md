# resource_allocator/

Decides which actual units answer: nearest appropriate stations, radii scaled
by severity, fallbacks when nothing suitable is in range, and — once road data
exists — optimal routes from station to incident.

Distinct from `response_planner/`, which says *what kind* of unit is needed.
This says *which one*, and how it gets there.

Currently `allocation_agent.py` only, and nothing in the live pipeline calls it
yet.
