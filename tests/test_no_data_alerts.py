"""Database-backed tests for scheduled no-data evaluation."""
from datetime import timedelta
from sqlalchemy import select
from app.models.alert import Alert
from app.services.no_data_alerts import evaluate_no_data_alerts
from tests.test_alert_engine import T, setup_patient, add_reading


def test_no_data_at_24h_once_and_after_new_reading(db_session):
    tenant, patient, device = setup_patient(db_session)
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


def test_no_data_skips_revoked_and_never_observed(db_session):
    tenant, patient, device = setup_patient(db_session)
    assert evaluate_no_data_alerts(db_session, T + timedelta(days=3)) == 0
    add_reading(db_session, tenant, patient, device, 0, 'spo2', 97)
    patient.consent_active = False
    db_session.flush()
    assert evaluate_no_data_alerts(db_session, T + timedelta(days=3)) == 0
