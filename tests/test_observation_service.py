from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.models.tenant import Tenant
from app.models.patient import Patient
from app.models.device import Device
from app.models.observation import Observation
from app.schemas.observation import HeartRateInput
from app.services.observation_service import save_heart_rate, find_existing_observation, is_identical_heart_rate, is_identical_observation, process_heart_rate
from app.schemas.observation import BodyTempInput
from app.services.observation_service import save_observation

import pytest
from sqlalchemy.exc import IntegrityError


def test_save_heart_rate(db_session):
    tenant = Tenant(id=uuid4(), name="Test Hospital")
    db_session.add(tenant)
    db_session.flush()

    patient = Patient(
        id=uuid4(),
        tenant_id=tenant.id,
        external_id="patient-001",
    )
    db_session.add(patient)
    db_session.flush()

    device = Device(
        id=uuid4(),
        tenant_id=tenant.id,
        patient_id=patient.id,
    )
    db_session.add(device)
    db_session.flush()

    observation = HeartRateInput(
        client_obs_id="obs-001",
        type="heart_rate",
        effective_at=datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc),
        value=Decimal("80"),
        unit="/min",
    )

    saved = save_heart_rate(
        db=db_session,
        observation=observation,
        tenant_id=tenant.id,
        patient_id=patient.id,
        device_id=device.id,
    )

    stored = db_session.execute(
        select(Observation).where(Observation.id == saved.id)
    ).scalar_one()

    assert stored.value == Decimal("80")
    assert stored.client_obs_id == "obs-001"
    assert stored.patient_id == patient.id
    assert stored.device_id == device.id
    assert stored.received_at is not None

    existing = find_existing_observation(
        db_session,
        device.id,
        "obs-001",
    )

    assert existing is not None
    assert existing.id == saved.id

    missing = find_existing_observation(
        db_session,
        device.id,
        "obs-999",
    )

    assert missing is None

    assert is_identical_heart_rate(saved, observation) is True

    changed = observation.model_copy(
        update={"value": Decimal("95")}
    )

    assert is_identical_heart_rate(saved, changed) is False

    assert is_identical_observation(saved, observation) is True

    changed = observation.model_copy(
        update={"value": Decimal("95")}
    )

    assert is_identical_observation(saved, changed) is False

    same_value_different_format = observation.model_copy(
        update={"value": Decimal("80.0")}
    )

    assert is_identical_observation(
        saved,
        same_value_different_format,
    ) is True


def test_duplicate_observation_is_rejected(db_session):
    tenant = Tenant(id=uuid4(), name="Duplicate Test Hospital")
    db_session.add(tenant)
    db_session.flush()

    patient = Patient(
        id=uuid4(),
        tenant_id=tenant.id,
        external_id="patient-duplicate",
    )
    db_session.add(patient)
    db_session.flush()

    device = Device(
        id=uuid4(),
        tenant_id=tenant.id,
        patient_id=patient.id,
    )
    db_session.add(device)
    db_session.flush()

    observation = HeartRateInput(
        client_obs_id="obs-duplicate",
        type="heart_rate",
        effective_at=datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc),
        value=Decimal("80"),
        unit="/min",
    )

    save_heart_rate(
        db_session, observation, tenant.id, patient.id, device.id
    )

    with pytest.raises(IntegrityError):
        save_heart_rate(
            db_session, observation, tenant.id, patient.id, device.id
        )


def test_savepoint_recovers_from_duplicate(db_session):
    tenant = Tenant(id=uuid4(), name="Savepoint Test Hospital")
    db_session.add(tenant)
    db_session.flush()

    patient = Patient(
        id=uuid4(),
        tenant_id=tenant.id,
        external_id="patient-savepoint",
    )
    db_session.add(patient)
    db_session.flush()

    device = Device(
        id=uuid4(),
        tenant_id=tenant.id,
        patient_id=patient.id,
    )
    db_session.add(device)
    db_session.flush()

    first = HeartRateInput(
        client_obs_id="obs-001",
        type="heart_rate",
        effective_at=datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc),
        value=Decimal("80"),
        unit="/min",
    )

    duplicate = first.model_copy()

    third = first.model_copy(
        update={"client_obs_id": "obs-003", "value": Decimal("90")}
    )

    with db_session.begin_nested():
        save_heart_rate(
            db_session, first, tenant.id, patient.id, device.id
        )

    try:
        with db_session.begin_nested():
            save_heart_rate(
                db_session, duplicate, tenant.id, patient.id, device.id
            )
    except IntegrityError:
        pass

    with db_session.begin_nested():
        save_heart_rate(
            db_session, third, tenant.id, patient.id, device.id
        )

    stored = db_session.execute(
        select(Observation).where(Observation.device_id == device.id)
    ).scalars().all()

    assert len(stored) == 2


def test_process_heart_rate_duplicate(db_session):
    tenant = Tenant(id=uuid4(), name="Process Test Hospital")
    db_session.add(tenant)
    db_session.flush()

    patient = Patient(
        id=uuid4(),
        tenant_id=tenant.id,
        external_id="patient-process",
    )
    db_session.add(patient)
    db_session.flush()

    device = Device(
        id=uuid4(),
        tenant_id=tenant.id,
        patient_id=patient.id,
    )
    db_session.add(device)
    db_session.flush()

    observation = HeartRateInput(
        client_obs_id="obs-001",
        type="heart_rate",
        effective_at=datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc),
        value=Decimal("80"),
        unit="/min",
    )

    first = process_heart_rate(
        db_session, observation, tenant.id, patient.id, device.id
    )

    second = process_heart_rate(
        db_session, observation, tenant.id, patient.id, device.id
    )

    changed = observation.model_copy(
        update={"value": Decimal("95")}
    )

    third = process_heart_rate(
        db_session, changed, tenant.id, patient.id, device.id
    )

    assert first == "accepted"
    assert second == "duplicate"
    assert third == "conflicting_duplicate"

    stored = db_session.execute(
        select(Observation).where(Observation.device_id == device.id)
    ).scalars().all()

    assert len(stored) == 1
    assert stored[0].value == Decimal("80")


def test_save_temperature(db_session):
    tenant = Tenant(id=uuid4(), name="Temperature Test Hospital")
    db_session.add(tenant)
    db_session.flush()

    patient = Patient(
        id=uuid4(),
        tenant_id=tenant.id,
        external_id="patient-temp",
    )
    db_session.add(patient)
    db_session.flush()

    device = Device(
        id=uuid4(),
        tenant_id=tenant.id,
        patient_id=patient.id,
    )
    db_session.add(device)
    db_session.flush()

    observation = BodyTempInput(
        client_obs_id="temp-001",
        type="body_temp",
        effective_at=datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc),
        value=Decimal("98.6"),
        unit="[degF]",
    )

    saved = save_observation(
        db_session,
        observation,
        tenant.id,
        patient.id,
        device.id,
    )

    assert saved.value == Decimal("37.0")
    assert saved.unit == "Cel"
    assert saved.original_value == Decimal("98.6")
    assert saved.original_unit == "[degF]"