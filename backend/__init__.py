"""
Backend package.

Marks the backend directory as an importable Python package so the app can
be referenced as "backend.main:app" by uvicorn and by the tests. Intentionally
empty otherwise — the FastAPI application lives in backend/main.py.
"""
