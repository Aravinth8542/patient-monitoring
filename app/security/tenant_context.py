"""Device authentication establishes RLS context before reading protected rows."""
import hashlib
from uuid import UUID
from fastapi import Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.database import get_runtime_db

def require_device_context(
    device_id: UUID,
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_runtime_db),
) -> UUID:
    scheme, sep, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not sep or not token or " " in token or len(token) > 512:
        raise HTTPException(401, detail="invalid_device_credentials")
    digest = hashlib.sha256(token.encode()).hexdigest()
    tenant = db.execute(text("SELECT public.app_authorize_device(:device_id, :digest)"),
        {"device_id": device_id, "digest": digest}).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(401, detail="invalid_device_credentials")
    return tenant
