import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FeatureRun(Base):
    __tablename__ = "feature_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), index=True, nullable=False
    )
    feature_key: Mapped[str] = mapped_column(ForeignKey("features.key"), nullable=False)
    credits_spent: Mapped[int] = mapped_column(Integer, nullable=False)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
