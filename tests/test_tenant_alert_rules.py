"""Focused tenant configuration tests (database tests use existing fixtures)."""
from datetime import timedelta
from sqlalchemy import select
from app.models.alert import Alert
from app.services.alert_rules import Reading, detect_episodes, DEFAULT_RULES
from app.services.alert_engine import evaluate_patient_alerts
from app.services.no_data_alerts import evaluate_no_data_alerts
from tests.test_alert_engine import T, setup_patient, add_reading


def test_multiple_configured_rules_without_code_changes():
    """
    Three 94% SpO2 readings at minutes 0, 5 and 10 are evaluated against two configured low-
    SpO2 rules. The rule with threshold 95 ('clinic_spo2') must trigger, while the stricter
    threshold 93 ('strict_spo2') must not, showing rule IDs and thresholds come from
    configuration.
    """
    rows=[Reading(T+timedelta(minutes=i), 'spo2', __import__('decimal').Decimal('94')) for i in (0,5,10)]
    rules=[dict(DEFAULT_RULES[0], id='clinic_spo2', value=95), dict(DEFAULT_RULES[0],id='strict_spo2',value=93)]
    assert [e.rule for e in detect_episodes(rows,rules)] == ['clinic_spo2']


def test_two_tenants_use_distinct_thresholds(db_session):
    """
    Both tenants receive identical 94% SpO2 readings at minutes 0, 5 and 10. Tenant A's
    threshold 92 produces no alert, while tenant B's threshold 95 produces one. The same
    input must not be evaluated using a global threshold.
    """
    a, pa, da=setup_patient(db_session)
    b, pb, db=setup_patient(db_session)
    a.alert_rules=[dict(DEFAULT_RULES[0], value=92)]
    b.alert_rules=[dict(DEFAULT_RULES[0], value=95)]
    for minute in (0,5,10):
        add_reading(db_session,a,pa,da,minute,'spo2',94)
        add_reading(db_session,b,pb,db,minute,'spo2',94)
    db_session.flush()
    assert evaluate_patient_alerts(db_session,a.id,pa.id,T+timedelta(minutes=11)) == 0
    assert evaluate_patient_alerts(db_session,b.id,pb.id,T+timedelta(minutes=11)) == 1


def test_tenant_specific_no_data_window(db_session):
    """
    A patient reports SpO2 98% at T and belongs to a tenant whose missing-data window is 12
    hours. At 11 hours no alert is due; at 12 hours exactly one alert must be created.
    """
    a,pa,da=setup_patient(db_session)
    pa.monitoring_started_at = T
    a.alert_rules=[dict(DEFAULT_RULES[2], window_hours=12)]
    add_reading(db_session,a,pa,da,0,'spo2',98)
    db_session.flush()
    assert evaluate_no_data_alerts(db_session,T+timedelta(hours=11)) == 0
    assert evaluate_no_data_alerts(db_session,T+timedelta(hours=12)) == 1


def test_device_runtime_uses_tenant_threshold(db_session):
    """
    The device is authenticated under the restricted database runtime. Its tenant's SpO2
    threshold is 95, so three readings of 94% at minutes 0, 5 and 10 must produce one
    low_spo2 alert. A privileged read after resetting the role confirms persistence.
    """
    from sqlalchemy import text
    from app.services.device_auth import hash_device_token
    tenant, patient, device = setup_patient(db_session)
    tenant.alert_rules = [dict(DEFAULT_RULES[0], value=95)]
    device.token_hash = hash_device_token('tenant-rule-device-token')
    for minute in (0, 5, 10):
        add_reading(db_session, tenant, patient, device, minute, 'spo2', 94)
    db_session.flush()
    db_session.execute(text('SET LOCAL ROLE patient_monitoring_runtime'))
    db_session.execute(text('SELECT public.app_authorize_device(:id,:digest)'),
        {'id': device.id, 'digest': hash_device_token('tenant-rule-device-token')})
    assert evaluate_patient_alerts(db_session, tenant.id, patient.id,
                                   T+timedelta(minutes=11), device_context=True) == 1
    db_session.execute(text('RESET ROLE'))
    assert db_session.scalar(select(Alert).where(Alert.patient_id == patient.id)).rule == 'low_spo2'
