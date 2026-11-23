"""Database-backed tests for scheduled detection and ingestion reconciliation."""
from datetime import timedelta
from sqlalchemy import select, text
from app.models.alert import Alert
from app.models.observation import Observation
from app.services.device_auth import hash_device_token
from app.services.no_data_alerts import evaluate_no_data_alerts
from tests.test_alert_engine import T, setup_patient, add_reading


def reconcile_arrival(db, tenant, patient, device, effective_minute, received_at):
    """Simulate an accepted upload and its ingestion-time reconciliation."""
    device.token_hash = hash_device_token('no-data-test-token')
    add_reading(db, tenant, patient, device, effective_minute, 'spo2', 98)
    db.flush()
    reading = db.scalar(select(Observation).where(
        Observation.device_id == device.id,
        Observation.effective_at == T + timedelta(minutes=effective_minute),
    ))
    reading.received_at = received_at
    db.flush()
    db.execute(text('SELECT public.app_authorize_device(:id,:digest)'), {
        'id': device.id, 'digest': hash_device_token('no-data-test-token')})
    return db.execute(text('SELECT public.app_reconcile_device_no_data(:tenant,:patient,:now)'), {
        'tenant': tenant.id, 'patient': patient.id, 'now': received_at}).scalar_one()


def test_no_data_at_24h_once_and_after_new_reading(db_session):
    tenant, patient, device = setup_patient(db_session)
    patient.monitoring_started_at = T
    add_reading(db_session, tenant, patient, device, 0, 'spo2', 97)
    db_session.flush()
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=23, minutes=59)) == 0
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=24)) == 1
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=25)) == 0
    assert reconcile_arrival(db_session, tenant, patient, device, 25 * 60, T + timedelta(hours=25)) == 1
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=48)) == 0
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=49)) == 1
    alerts = db_session.scalars(select(Alert).where(Alert.patient_id == patient.id,
                                                    Alert.rule == 'no_data')).all()
    assert len(alerts) == 2
    assert all(a.severity == 'low' for a in alerts)
    assert sorted(a.status for a in alerts) == ['open', 'resolved']


def test_no_data_skips_revoked_and_not_yet_enrolled(db_session):
    tenant, patient, device = setup_patient(db_session)
    patient.monitoring_started_at = T + timedelta(days=4)
    db_session.flush()
    assert evaluate_no_data_alerts(db_session, T + timedelta(days=3)) == 0
    add_reading(db_session, tenant, patient, device, 0, 'spo2', 97)
    patient.consent_active = False
    db_session.flush()
    assert evaluate_no_data_alerts(db_session, T + timedelta(days=3)) == 0


def test_never_observed_patient_becomes_due(db_session):
    tenant, patient, device = setup_patient(db_session)
    patient.monitoring_started_at = T
    db_session.flush()
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=23, minutes=59)) == 0
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=24)) == 1
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=25)) == 0
    alert = db_session.scalar(select(Alert).where(Alert.patient_id == patient.id, Alert.rule == 'no_data'))
    assert alert.episode_start == T
    assert alert.status == 'open'


def test_reporting_resumes_resolves_missing_data_alert(db_session):
    tenant, patient, device = setup_patient(db_session)
    patient.monitoring_started_at = T
    db_session.flush()
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=24)) == 1
    assert reconcile_arrival(db_session, tenant, patient, device, 25 * 60, T + timedelta(hours=25)) == 1
    alert = db_session.scalar(select(Alert).where(Alert.patient_id == patient.id, Alert.rule == 'no_data'))
    db_session.refresh(alert)
    assert alert.status == 'resolved'
    assert alert.resolved_at == T + timedelta(hours=25)
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=25)) == 0


def test_no_data_never_observed_uses_tenant_window(db_session):
    from app.services.alert_rules import DEFAULT_RULES
    tenant, patient, device = setup_patient(db_session)
    tenant.alert_rules = [dict(DEFAULT_RULES[2], window_hours=12)]
    patient.monitoring_started_at = T
    db_session.flush()
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=11)) == 0
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=12)) == 1


def test_old_late_reading_does_not_clear_overdue_alert(db_session):
    tenant, patient, device = setup_patient(db_session)
    patient.monitoring_started_at = T
    add_reading(db_session, tenant, patient, device, 0, 'spo2', 97)
    db_session.flush()
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=24)) == 1
    assert reconcile_arrival(db_session, tenant, patient, device, 60, T + timedelta(hours=48)) == 1
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=48)) == 1
    alerts = db_session.scalars(select(Alert).where(
        Alert.patient_id == patient.id, Alert.rule == 'no_data')).all()
    assert sorted(a.status for a in alerts) == ['open', 'retracted']
    assert next(a for a in alerts if a.status == 'open').episode_start == T + timedelta(hours=1)
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=48)) == 0


def test_backfill_invalidates_alert_before_it_was_due(db_session):
    tenant, patient, device = setup_patient(db_session)
    patient.monitoring_started_at = T
    db_session.flush()
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=24)) == 1
    assert reconcile_arrival(db_session, tenant, patient, device, 23 * 60, T + timedelta(hours=25)) == 1
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=25)) == 0
    alert = db_session.scalar(select(Alert).where(
        Alert.patient_id == patient.id, Alert.rule == 'no_data'))
    db_session.refresh(alert)
    assert alert.status == 'retracted'
    assert alert.retraction_reason == 'late_observation_correction'
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=47)) == 1


def test_out_of_order_backfill_retracts_even_if_latest_effective_unchanged(db_session):
    tenant, patient, device = setup_patient(db_session)
    patient.monitoring_started_at = T
    db_session.flush()
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=24)) == 1
    # A recovery is received first; an older effective-time reading arrives later.
    assert reconcile_arrival(db_session, tenant, patient, device, 25 * 60, T + timedelta(hours=25)) == 1
    # The older measurement invalidates the earlier alert even after resolution.
    assert reconcile_arrival(db_session, tenant, patient, device, 23 * 60, T + timedelta(hours=26)) == 1
    alert = db_session.scalar(select(Alert).where(Alert.patient_id == patient.id, Alert.rule == "no_data"))
    db_session.refresh(alert)
    assert alert.status == "retracted"


def test_ingestion_reconciliation_uses_tenant_window(db_session):
    from app.services.alert_rules import DEFAULT_RULES
    tenant, patient, device = setup_patient(db_session)
    tenant.alert_rules = [dict(DEFAULT_RULES[2], window_hours=12)]
    patient.monitoring_started_at = T
    db_session.flush()
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=12)) == 1
    # 11-hour backfill invalidates the 12-hour missing-data alert.
    assert reconcile_arrival(db_session, tenant, patient, device, 11 * 60,
                             T + timedelta(hours=13)) == 1
    alert = db_session.scalar(select(Alert).where(Alert.patient_id == patient.id,
                                                  Alert.rule == 'no_data'))
    db_session.refresh(alert)
    assert alert.status == 'retracted'
