import uuid

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Device(Base):
    __tablename__ = "devices"

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patients.tenant_id", "patients.id"],
            name="fk_device_patient_tenant",
        ),
        UniqueConstraint(
            "tenant_id",
            "patient_id",
            "id",
            name="uq_device_tenant_patient_id",
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
    # SHA-256 digest of a high-entropy random device bearer token. Never store plaintext.
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
