"""One raw reading from one source, exactly as it arrived."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import BigInteger, DateTime, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ecoguard.database.models import Base


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (
        # Makes a re-fetch of an overlapping window a no-op rather than a
        # duplicate row. Every collector therefore needs a cell_id that is
        # stable for the same underlying reading.
        UniqueConstraint("source", "cell_id", "observed_at", name="observations_identity"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    cell_id: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[Any | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326), nullable=True
    )
    # observed_at is when the reading was taken; ingested_at is the server
    # clock when we wrote it. They differ by hours for FIRMS, and detection
    # cursors compare on ingested_at because only that one is monotonic.
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
