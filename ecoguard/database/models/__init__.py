"""Declarative models for the collection layer.

Base is defined here rather than in a separate module so the two model files
below can import it without a fourth file; the imports sit at the bottom
because they depend on it.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from ecoguard.database.models.collector_run import CollectorRun  # noqa: E402
from ecoguard.database.models.observation import Observation  # noqa: E402
from ecoguard.database.models.air_pollution_baseline import (  # noqa: E402
    AirPollutionBaselineBucket,
    AirPollutionBaselineProfile,
    AirPollutionBaselineVersion,
    AirPollutionStationCatalog,
)

__all__ = [
    "Base", "CollectorRun", "Observation", "AirPollutionStationCatalog",
    "AirPollutionBaselineProfile", "AirPollutionBaselineVersion",
    "AirPollutionBaselineBucket",
]
