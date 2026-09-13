# response_planner/fire/

- `planning_agent.py` — assessment in, concrete plan out. Refuses to plan
  without a successful risk assessment rather than planning against nothing.
- `plan_judge.py` — grades a plan against the corpus using its own independent
  retrieval, so the planner cannot mark its own homework.
