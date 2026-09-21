# response_planner/fire/

The Israeli-grounded planner and the deterministic blocks it reasons over.

- `israeli_planner.py` — incident report in, grounded response plan out. Four
  fixed filtered retrievals, then one model call. Every citation is verified
  against the text actually retrieved; a plan whose citations do not verify is
  discarded rather than served.
- `israeli_plan_schemas.py` — what the model may write, and the Israeli
  resource vocabulary it must write it in. Holds no station names and no
  grade: those are computed, and they travel beside the plan on
  `PlannerResult` rather than inside it.
- `escalation.py` — the national-event criteria of הוראה 201 / 201.02.003
  §2.1, in code, citing the clause. Thresholds are not a retrieval problem.
- `dispatch.py` — which stations are responsible and for how many teams, plus
  the police and MDA answering for each threatened locality. Jurisdiction, not
  routing: the resource allocator holds the road times and claims actual units.
- `dispatch_policy.py` — the grade table and team counts, as configuration.
  A reconstruction from published thresholds, not the authority's own dispatch
  table, which lives in שלהבת and is not available to us.
- `planning_agent.py` — the older path, serving the legacy point-query
  endpoint. Refuses to plan without a successful risk assessment.

## On grading plans

`plan_judge.py` was removed. It graded plans against the four-document English
corpus that preceded the Israeli one, using retrieval that returns nothing on
Hebrew, so its scores described a planner that no longer exists. A judge that
is out of date is worse than no judge: it produces a number, and a number gets
quoted.

Any replacement has to grade against the corpus the planner actually retrieves
from, with its own independent retrieval so the planner cannot mark its own
homework.
