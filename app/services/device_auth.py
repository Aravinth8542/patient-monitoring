"""Device-scoped bearer token authentication (not a clinician token)."""
import hashlib
import hmac
import secrets
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.models.device import Device


def generate_device_token() -> str:
    """Issue once through a trusted provisioning process; show plaintext only once."""
    return secrets.token_urlsafe(32)


def hash_device_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def authenticate_device(db: Session, device: Device | None, authorization: str | None) -> Device:
    # A generic 401 avoids disclosing whether a particular device UUID exists.
    if device is None or not authorization:
        raise HTTPException(status_code=401, detail="invalid_device_credentials", headers={"WWW-Authenticate": "Bearer"})
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token or " " in token:
        raise HTTPException(status_code=401, detail="invalid_device_credentials", headers={"WWW-Authenticate": "Bearer"})
    actual = hash_device_token(token)
    if device.token_hash is None or not hmac.compare_digest(device.token_hash, actual):
        raise HTTPException(status_code=401, detail="invalid_device_credentials", headers={"WWW-Authenticate": "Bearer"})
    return device
