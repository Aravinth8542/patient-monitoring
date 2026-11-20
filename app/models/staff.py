"""Staff identities and explicit patient-care-team membership."""
import uuid
from sqlalchemy import ForeignKey, ForeignKeyConstraint, String, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class StaffUser(Base):
    __tablename__ = "staff_users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_staff_tenant_id"),
        CheckConstraint("role IN ('clinician', 'auditor')", name="ck_staff_role"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

class CareTeamMembership(Base):
    __tablename__ = "care_team_memberships"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "staff_id"], ["staff_users.tenant_id", "staff_users.id"], name="fk_care_staff_tenant"),
        ForeignKeyConstraint(["tenant_id", "patient_id"], ["patients.tenant_id", "patients.id"], name="fk_care_patient_tenant"),
        UniqueConstraint("staff_id", "patient_id", name="uq_care_staff_patient"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    staff_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
