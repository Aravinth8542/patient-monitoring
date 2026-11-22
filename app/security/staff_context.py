"""Authenticate staff through a narrowly granted PostgreSQL SECURITY DEFINER function."""
import hashlib
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_runtime_db

bearer_scheme = HTTPBearer(auto_error=False, scheme_name="StaffBearer")


@dataclass(frozen=True)
class StaffIdentity:
    id: UUID
    tenant_id: UUID
    role: str


def require_staff_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_runtime_db),
) -> StaffIdentity:
    if credentials is None:
        raise HTTPException(status_code=401, detail="invalid_staff_credentials")

    token = credentials.credentials

    if (
        credentials.scheme.lower() != "bearer"
        or not token
        or " " in token
        or len(token) > 512
    ):
        raise HTTPException(status_code=401, detail="invalid_staff_credentials")

    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()

    row = db.execute(
        text(
            "SELECT staff_id, tenant_id, staff_role "
            "FROM public.app_authorize_staff(:digest)"
        ),
        {"digest": digest},
    ).one_or_none()

    if row is None:
        raise HTTPException(status_code=401, detail="invalid_staff_credentials")

    return StaffIdentity(
        id=row.staff_id,
        tenant_id=row.tenant_id,
        role=row.staff_role,
    )