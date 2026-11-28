import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Boolean,
    Integer,
    func
)

from decimal import Decimal
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Observation(Base):
    __tablename__ = "observations"

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "patient_id", "device_id"],
            ["devices.tenant_id", "devices.patient_id", "devices.id"],
            name="fk_observation_device_patient_tenant",
        ),
        UniqueConstraint(
            "device_id",
            "client_obs_id",
            name="uq_observation_device_client_id",
        ),
        Index(
            "ix_observation_tenant_patient_time",
            "tenant_id",
            "patient_id",
            "effective_at",
        ),
        Index("ix_observation_patient_metric_time_id", "tenant_id", "patient_id", "type", "effective_at", "id"),
        CheckConstraint(
            "type IN ("
            "'heart_rate', "
            "'spo2', "
            "'blood_pressure', "
            "'body_temp', "
            "'symptom_score', "
            "'medication_taken'"
            ")",
            name="ck_observation_valid_type",
        ),
        CheckConstraint(
            "type != 'spo2' OR (value IS NOT NULL AND value BETWEEN 0 AND 100)",
            name="ck_observation_spo2_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    client_obs_id: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    value: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    systolic: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    diastolic: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    medication_ref: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    unit: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    original_value: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    original_unit: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    original_effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Database clock, independent of TEST_MODE and device-supplied timestamps.
    inserted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
    )

    clock_skew_flagged: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    clock_skew_seconds: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    original_payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )