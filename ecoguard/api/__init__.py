"""
Backend package.

Marks the backend directory as an importable Python package so the app can
be referenced as "ecoguard.api.main:app" by uvicorn and by the tests. Intentionally
empty otherwise — the FastAPI application lives in ecoguard/api/main.py.
"""
