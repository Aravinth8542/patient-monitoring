"""Database integration tests for explicit, idempotent alert evaluation."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from sqlalchemy import select
from app.models.tenant import Tenant
from app.models.patient import Patient
from app.models.device import Device
from app.models.observation import Observation
from app.models.alert import Alert
from app.services.alert_engine import evaluate_patient_alerts

T = datetime(2026, 11, 20, 10, tzinfo=timezone.utc)


def setup_patient(db):
    tenant = Tenant(id=uuid4(), name='alert-test-' + uuid4().hex)
    db.add(tenant)
    db.flush()
    patient = Patient(id=uuid4(), tenant_id=tenant.id, external_id=uuid4().hex,
                      timezone='UTC', consent_active=True)
    db.add(patient)
    db.flush()
    device = Device(id=uuid4(), tenant_id=tenant.id, patient_id=patient.id)
    db.add(device)
    db.flush()
    return tenant, patient, device


def add_reading(db, tenant, patient, device, minute, kind, value):
    at = T + timedelta(minutes=minute)
    db.add(Observation(
        id=uuid4(), tenant_id=tenant.id, patient_id=patient.id, device_id=device.id,
        client_obs_id=uuid4().hex, type=kind, value=Decimal(str(value)),
        unit='%' if kind == 'spo2' else '/min',
        original_effective_at=at, effective_at=at, received_at=at,
        original_payload={}, clock_skew_flagged=False,
    ))


def test_persist_low_spo2_episode_once(db_session):
    tenant, patient, device = setup_patient(db_session)
    for minute, value in [(0, 91), (5, 90), (10, 91)]:
        add_reading(db_session, tenant, patient, device, minute, 'spo2', value)
    db_session.flush()
    assert evaluate_patient_alerts(db_session, tenant.id, patient.id, T + timedelta(minutes=11)) == 1
    assert evaluate_patient_alerts(db_session, tenant.id, patient.id, T + timedelta(minutes=12)) == 0
    alerts = db_session.scalars(select(Alert).where(Alert.patient_id == patient.id)).all()
    assert len(alerts) == 1
    assert (alerts[0].rule, alerts[0].status, alerts[0].episode_start) == ('low_spo2', 'open', T)


def test_persist_distinct_episodes_and_heart_rate(db_session):
    tenant, patient, device = setup_patient(db_session)
    for minute, value in [(0, 91), (5, 91), (10, 91), (11, 96),
                          (20, 91), (25, 91), (30, 91)]:
        add_reading(db_session, tenant, patient, device, minute, 'spo2', value)
    add_reading(db_session, tenant, patient, device, 0, 'heart_rate', 70)
    add_reading(db_session, tenant, patient, device, 10, 'heart_rate', 105)
    db_session.flush()
    assert evaluate_patient_alerts(db_session, tenant.id, patient.id, T + timedelta(minutes=31)) == 3
    assert evaluate_patient_alerts(db_session, tenant.id, patient.id, T + timedelta(minutes=31)) == 0


def test_no_alert_when_consent_revoked(db_session):
    tenant, patient, device = setup_patient(db_session)
    for minute in (0, 5, 10):
        add_reading(db_session, tenant, patient, device, minute, 'spo2', 90)
    patient.consent_active = False
    db_session.flush()
    assert evaluate_patient_alerts(db_session, tenant.id, patient.id, T + timedelta(minutes=11)) == 0


def test_late_normal_reading_breaks_spo2_episode(db_session):
    tenant, patient, device = setup_patient(db_session)
    for minute in (0, 5, 10):
        add_reading(db_session, tenant, patient, device, minute, 'spo2', 91)
    db_session.flush()
    assert evaluate_patient_alerts(db_session, tenant.id, patient.id, T + timedelta(minutes=11)) == 1
    add_reading(db_session, tenant, patient, device, 7, 'spo2', 96)
    db_session.flush()
    assert evaluate_patient_alerts(db_session, tenant.id, patient.id, T + timedelta(minutes=12)) == 0
    alert = db_session.scalars(select(Alert).where(Alert.patient_id == patient.id)).one()
    assert alert.status == 'retracted'
