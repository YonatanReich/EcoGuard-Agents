# api/

The FastAPI application. Transport only: CORS, request validation, status
codes, error masking. No domain logic — every endpoint delegates to a stage
folder and shapes the result for the wire.

`fire_danger_surface.py` renders the FWI point samples into a PNG for one
endpoint and is used nowhere else, which is why it sits here rather than in a
stage.

Run: `uvicorn ecoguard.api.main:app --reload`
