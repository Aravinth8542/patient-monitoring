import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKeyConstraint, Index, CheckConstraint, text
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class PendingAlertEvaluation(Base):
    __tablename__ = "pending_alert_evaluations"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "patient_id"], ["patients.tenant_id", "patients.id"]),
        CheckConstraint("cardinality(observation_ids) > 0", name="ck_pending_nonempty"),
        Index("ix_pending_created", "created_at", "id"),
        Index("ix_pending_patient", "tenant_id", "patient_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    observation_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)))
    evaluation_now: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("clock_timestamp()"))
