# detectors/

Finds **candidates** — places where something may be happening — from what the
collection layer stored. A detector produces an event with evidence attached
and deliberately computes no risk score: deciding how bad it is belongs to
`analyzers/`, and mixing the two makes it impossible to tell a detection
failure from an assessment failure.

