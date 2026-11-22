import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False
    )

    # None means the built-in default rules; [] deliberately disables all rules.
    alert_rules: Mapped[list | None] = mapped_column(JSONB, nullable=True)
