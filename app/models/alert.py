import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKeyConstraint, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class Alert(Base):
    __tablename__ = 'alerts'
    __table_args__ = (
        ForeignKeyConstraint(['tenant_id','patient_id'], ['patients.tenant_id','patients.id']),
        UniqueConstraint('tenant_id','patient_id','rule','episode_start', name='uq_alert_episode'),
        UniqueConstraint('tenant_id','patient_id','id', name='uq_alert_patient_id'),
        ForeignKeyConstraint(['tenant_id','patient_id','superseded_by_id'], ['alerts.tenant_id','alerts.patient_id','alerts.id'], name='fk_alert_superseded'),
        Index('ix_alert_patient_rule', 'tenant_id','patient_id','rule'),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    rule: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='open')
    episode_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    retracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retraction_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)

    episode_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    qualified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_retrospective: Mapped[bool | None] = mapped_column(Boolean)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
