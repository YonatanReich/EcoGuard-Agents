# EcoGuard API + collection scheduler.
#
# One image, one process: uvicorn serves the API and, in its lifespan, starts
# the APScheduler that owns every collector and the detection tick.
#
# RUN EXACTLY ONE INSTANCE OF THIS. The scheduler is created at import time in
# ecoguard/scheduler.py, so every replica gets its own full set of timers. The
# collectors and the coordinator take advisory locks and survive that, but
# classify_new_text() does not — it runs before the coordinator's lock, so a
# second replica is a second set of model calls for the same messages.
# Scale by making the box bigger, not by adding replicas.

FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# rasterio's wheel bundles GDAL but links libexpat from the system, and the
# slim image does not ship it: without this the API dies at import with
# "libexpat.so.1: cannot open shared object file".
RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

# Requirements first so a code change does not reinstall scipy.
#
# No build toolchain here on purpose: numpy, scipy, scikit-learn, rasterio and
# psycopg[binary] all publish manylinux wheels. If a future pin has no wheel,
# add build-essential to this layer rather than to the final image.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY ecoguard/ ./ecoguard/
COPY alembic.ini .

# Railway/Render/Fly inject PORT. The default matches the vite dev proxy, so a
# container run locally is reachable the same way the laptop process was.
ENV PORT=8000
EXPOSE 8000

# Shell form so $PORT expands. One worker: see the replica warning above.
CMD uvicorn ecoguard.api.main:app --host 0.0.0.0 --port ${PORT} --workers 1
