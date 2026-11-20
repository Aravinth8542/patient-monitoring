"""Staff bearer credentials are separate from device credentials."""
import hashlib
import hmac
import secrets
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.staff import StaffUser


def new_staff_token() -> str:
    return secrets.token_urlsafe(32)


def hash_staff_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def authenticate_staff(db: Session, authorization: str | None, role: str | None = None) -> StaffUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="invalid_staff_credentials")
    token = authorization[7:]
    if not token or len(token) > 512:
        raise HTTPException(status_code=401, detail="invalid_staff_credentials")
    digest = hash_staff_token(token)
    user = db.execute(select(StaffUser).where(StaffUser.token_hash == digest)).scalar_one_or_none()
    if user is None or not hmac.compare_digest(user.token_hash, digest):
        raise HTTPException(status_code=401, detail="invalid_staff_credentials")
    if role is not None and user.role != role:
        raise HTTPException(status_code=403, detail="staff_role_forbidden")
    return user
