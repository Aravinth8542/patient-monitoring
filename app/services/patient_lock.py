"""Shared transaction-scoped patient lock for ingestion and alert processing."""
import hashlib
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def lock_patient(db: Session, tenant_id: UUID, patient_id: UUID) -> None:
    """Serialize work for one tenant/patient until commit or rollback."""
    digest = hashlib.sha256(f"patient:{tenant_id}:{patient_id}".encode()).digest()
    lock_id = int.from_bytes(digest[:8], "big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id})
