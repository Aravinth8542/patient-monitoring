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
    """
    After an SpO2 reading at monitoring start, 23h59m of silence is not overdue; 24h creates
    one low-severity alert; 25h creates no duplicate. A reading at hour 25 resolves the
    first episode. At hour 48 the new 24-hour gap is not yet complete; at hour 49 a second
    alert opens. The database must contain one resolved and one open episode.
    """
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
    """
    A patient's monitoring start is four days after the baseline. Evaluating at day three
    must not create an alert because monitoring has not begun. Even after adding an old
    reading, revoking consent must keep missing-data evaluation from alerting.
    """
    tenant, patient, device = setup_patient(db_session)
    patient.monitoring_started_at = T + timedelta(days=4)
    db_session.flush()
    assert evaluate_no_data_alerts(db_session, T + timedelta(days=3)) == 0
    add_reading(db_session, tenant, patient, device, 0, 'spo2', 97)
    patient.consent_active = False
    db_session.flush()
    assert evaluate_no_data_alerts(db_session, T + timedelta(days=3)) == 0


def test_never_observed_patient_becomes_due(db_session):
    """
    The patient is enrolled at T but has never sent a reading. Missing-data detection must
    use enrollment as the silence start: nothing at 23h59m, one open alert at 24h, and no
    duplicate at 25h. The alert's episode_start must be T.
    """
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
    """
    With no readings, an alert opens exactly 24 hours after monitoring starts. When a
    reading effective at hour 25 arrives, ingestion reconciliation must resolve the alert at
    hour 25. Re-running missing-data detection at the same time must not open another alert.
    """
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
    """
    The tenant configures a 12-hour missing-data rule and the patient has no observations.
    Evaluation at hour 11 must produce nothing, while hour 12 must produce one alert; the
    default 24-hour rule must not override tenant configuration.
    """
    from app.services.alert_rules import DEFAULT_RULES
    tenant, patient, device = setup_patient(db_session)
    tenant.alert_rules = [dict(DEFAULT_RULES[2], window_hours=12)]
    patient.monitoring_started_at = T
    db_session.flush()
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=11)) == 0
    assert evaluate_no_data_alerts(db_session, T + timedelta(hours=12)) == 1


def test_old_late_reading_does_not_clear_overdue_alert(db_session):
    """
    An alert opens after silence from T to hour 24. At hour 48, a late reading timestamped
    hour 1 arrives. That backfill invalidates the old episode start and retracts the old
    alert, but the patient has still been silent for 47 hours since hour 1, so a new open
    alert must be created. A repeat evaluation must create no duplicate.
    """
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
    """
    A never-observed patient receives an alert at hour 24. At hour 25, a late reading
    effective at hour 23 proves the original 24-hour silence did not occur, so the alert
    must be retracted with reason late_observation_correction. At hour 47, 24 hours have
    elapsed since the backfilled reading and a new alert becomes due.
    """
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
    """
    A missing-data alert opens at hour 24. A reading at hour 25 arrives and resolves it;
    afterward, an older reading effective at hour 23 arrives at hour 26. Although the latest
    effective timestamp remains hour 25, the older reading disproves the original missing-
    data episode, so the previously resolved alert must be retracted.
    """
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
    """
    A tenant's missing-data window is 12 hours, so an alert opens at hour 12. At hour 13,
    ingestion backfills a reading effective at hour 11. This means the patient was not
    actually silent for 12 hours at the alert time; reconciliation must retract the alert
    using the tenant-specific window.
    """
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
