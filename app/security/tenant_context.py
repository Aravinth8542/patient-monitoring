"""Device authentication establishes RLS context before reading protected rows."""
import hashlib
from uuid import UUID
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.database import get_runtime_db

device_bearer_scheme = HTTPBearer(auto_error=False, scheme_name="DeviceBearer")

def require_device_context(
    device_id: UUID,
    credentials: HTTPAuthorizationCredentials | None = Depends(device_bearer_scheme),
    db: Session = Depends(get_runtime_db),
) -> UUID:
    if credentials is None:
        raise HTTPException(401, detail="invalid_device_credentials")
    token = credentials.credentials
    if credentials.scheme.lower() != "bearer" or not token or " " in token or len(token) > 512:
        raise HTTPException(401, detail="invalid_device_credentials")
    digest = hashlib.sha256(token.encode()).hexdigest()
    tenant = db.execute(text("SELECT public.app_authorize_device(:device_id, :digest)"),
        {"device_id": device_id, "digest": digest}).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(401, detail="invalid_device_credentials")
    return tenant
