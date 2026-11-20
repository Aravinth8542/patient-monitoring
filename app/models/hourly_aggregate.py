"""Effective-time hourly patient observation summaries."""
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import DateTime, ForeignKeyConstraint, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class HourlyAggregate(Base):
    __tablename__ = "observation_hourly_aggregates"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "patient_id"], ["patients.tenant_id", "patients.id"]),
        UniqueConstraint("tenant_id", "patient_id", "type", "bucket_start", name="uq_hourly_aggregate_bucket"),
        Index("ix_hourly_aggregate_patient_time", "tenant_id", "patient_id", "bucket_start"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    value_sum: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    value_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    value_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    value_avg: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    systolic_sum: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    systolic_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    systolic_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    systolic_avg: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    diastolic_sum: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    diastolic_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    diastolic_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    diastolic_avg: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
