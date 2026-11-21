
"""Provision isolated synthetic devices for ingestion load testing."""
import json
import os
import uuid
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models.tenant import Tenant
from app.models.patient import Patient
from app.models.device import Device
from app.services.device_auth import generate_device_token, hash_device_token


OUTPUT = Path("load-devices.json")


def main():
    from sqlalchemy.engine import make_url

    database = make_url(settings.database_url).database
    if database != "patient_monitoring":
        raise SystemExit("Refusing to provision outside patient_monitoring")

    if OUTPUT.exists():
        raise SystemExit(
            "load-devices.json already exists. "
            "Rename or delete the placeholder file first."
        )

    credentials = []

    with SessionLocal.begin() as db:
        for index in range(10):
            tenant_id = uuid.uuid4()
            patient_id = uuid.uuid4()
            device_id = uuid.uuid4()
            token = generate_device_token()

            db.add(Tenant(
                id=tenant_id,
                name=f"Load Test Hospital {index + 1}",
            ))
            db.flush()

            db.add(Patient(
                id=patient_id,
                tenant_id=tenant_id,
                external_id=f"LOAD-{uuid.uuid4().hex[:12]}",
                timezone="UTC",
                consent_active=True,
            ))
            db.flush()

            db.add(Device(
                id=device_id,
                tenant_id=tenant_id,
                patient_id=patient_id,
                token_hash=hash_device_token(token),
            ))

            credentials.append({
                "device_id": str(device_id),
                "token": token,
            })

    OUTPUT.write_text(
        json.dumps(credentials, indent=2),
        encoding="utf-8",
    )

    print(f"Provisioned {len(credentials)} synthetic devices.")
    print(f"Credentials saved to {OUTPUT}")
    print("Do not commit this file.")


if __name__ == "__main__":
    main()
