"""Authenticate staff through a narrowly granted PostgreSQL SECURITY DEFINER function."""
import hashlib
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_runtime_db


@dataclass(frozen=True)
class StaffIdentity:
    id: UUID
    tenant_id: UUID
    role: str


def require_staff_context(
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_runtime_db),
) -> StaffIdentity:
    scheme, sep, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not sep or not token or " " in token or len(token) > 512:
        raise HTTPException(status_code=401, detail="invalid_staff_credentials")
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    row = db.execute(
        text("SELECT staff_id, tenant_id, staff_role FROM public.app_authorize_staff(:digest)"),
        {"digest": digest},
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=401, detail="invalid_staff_credentials")
    return StaffIdentity(id=row.staff_id, tenant_id=row.tenant_id, role=row.staff_role)
