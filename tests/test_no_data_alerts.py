"""Database-backed tests for scheduled no-data evaluation."""
from datetime import timedelta
from sqlalchemy import select
from app.models.alert import Alert
from app.services.no_data_alerts import evaluate_no_data_alerts
from tests.test_alert_engine import T, setup_patient, add_reading


def test_no_data_at_24h_once_and_after_new_reading(db_session):
    tenant, patient, device = setup_patient(db_session)
    patient.monitoring_started_at = T
    add_reading(db_session, tenant, patient, device, 0, 'spo2', 97)
    db_session.flush()
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=23, minutes=59)) == 0
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=24)) == 1
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=25)) == 0
    add_reading(db_session, tenant, patient, device, 25 * 60, 'spo2', 98)
    db_session.flush()
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=48)) == 0
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=49)) == 1
    alerts = db_session.scalars(select(Alert).where(Alert.patient_id == patient.id,
                                                    Alert.rule == 'no_data')).all()
    assert len(alerts) == 2
    assert all(a.severity == 'low' for a in alerts)
    assert sorted(a.status for a in alerts) == ['open', 'resolved']


def test_no_data_skips_revoked_and_not_yet_enrolled(db_session):
    tenant, patient, device = setup_patient(db_session)
    # Newly enrolled patients are not due before their monitoring start.
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
    add_reading(db_session, tenant, patient, device, 25 * 60, 'spo2', 98)
    db_session.flush()
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=25)) == 0
    alert = db_session.scalar(select(Alert).where(Alert.patient_id == patient.id, Alert.rule == 'no_data'))
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
    # Arrives on day two, but was actually measured only one hour after start.
    add_reading(db_session, tenant, patient, device, 60, 'spo2', 98)
    db_session.flush()
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
    # A 23-hour reading arrived after the original alert was created.
    add_reading(db_session, tenant, patient, device, 23 * 60, 'spo2', 98)
    db_session.flush()
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=25)) == 0
    alert = db_session.scalar(select(Alert).where(
        Alert.patient_id == patient.id, Alert.rule == 'no_data'))
    assert alert.status == 'retracted'
    assert alert.retraction_reason == 'late_observation_correction'
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=47)) == 1
