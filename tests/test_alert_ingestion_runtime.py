"""Verify alert insertion under the restricted device database role."""
from datetime import timedelta
from sqlalchemy import text, select
from app.models.alert import Alert
from app.services.alert_engine import evaluate_patient_alerts
from app.services.device_auth import hash_device_token
from tests.test_alert_engine import T, setup_patient, add_reading


def test_device_runtime_can_create_alert_without_reading_alert_history(db_session):
    tenant, patient, device = setup_patient(db_session)
    device.token_hash = hash_device_token('alert-test-token')
    for minute in (0, 5, 10):
        add_reading(db_session, tenant, patient, device, minute, 'spo2', 90)
    db_session.flush()
    db_session.execute(text('SET LOCAL ROLE patient_monitoring_runtime'))
    db_session.execute(text('SELECT public.app_authorize_device(:id,:digest)'),
        {'id': device.id, 'digest': hash_device_token('alert-test-token')})
    now = T + timedelta(minutes=11)
    assert evaluate_patient_alerts(db_session, tenant.id, patient.id, now, device_context=True) == 1
    assert evaluate_patient_alerts(db_session, tenant.id, patient.id, now, device_context=True) == 0
    assert db_session.execute(text('SELECT count(*) FROM alerts')).scalar_one() == 0
    db_session.execute(text('RESET ROLE'))
    assert len(db_session.scalars(select(Alert).where(Alert.patient_id == patient.id)).all()) == 1


def test_device_runtime_retracts_invalidated_spo2_episode(db_session):
    tenant, patient, device = setup_patient(db_session)
    device.token_hash = hash_device_token('retract-test-token')
    for minute in (0, 5, 10):
        add_reading(db_session, tenant, patient, device, minute, 'spo2', 91)
    db_session.flush()
    assert evaluate_patient_alerts(db_session, tenant.id, patient.id, T + timedelta(minutes=11)) == 1
    add_reading(db_session, tenant, patient, device, 7, 'spo2', 96)
    db_session.flush()
    db_session.execute(text('SET LOCAL ROLE patient_monitoring_runtime'))
    db_session.execute(text('SELECT public.app_authorize_device(:id,:digest)'),
        {'id': device.id, 'digest': hash_device_token('retract-test-token')})
    assert evaluate_patient_alerts(db_session, tenant.id, patient.id,
        T + timedelta(minutes=12), device_context=True) == 0
    assert db_session.execute(text('SELECT count(*) FROM alerts')).scalar_one() == 0
    db_session.execute(text('RESET ROLE'))
    alert = db_session.scalars(select(Alert).where(Alert.patient_id == patient.id)).one()
    assert alert.status == 'retracted'
    assert alert.retracted_at == T + timedelta(minutes=12)
    assert alert.retraction_reason == 'late_observation_correction'
