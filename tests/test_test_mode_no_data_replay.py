"""Guardrails for HTTP-triggered no-data evaluation in TEST_MODE."""
from datetime import datetime, timezone
from uuid import uuid4
from app.config import settings
from app.services import test_mode_no_data


def test_replay_evaluation_requires_test_mode_and_header(monkeypatch):
    """
    Replace the evaluator and session with spies. With TEST_MODE disabled, even a supplied
    header must do nothing; with TEST_MODE enabled but no header it must also do nothing.
    Only when both conditions hold should the evaluator receive the specified clock, tenant
    and patient filters and commit once.
    """
    calls = []
    monkeypatch.setattr(test_mode_no_data, 'evaluate_no_data_alerts', lambda db, now, **filters: calls.append((now, filters)))

    class FakeSession:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def commit(self):
            calls.append('committed')

    monkeypatch.setattr(test_mode_no_data, 'SessionLocal', FakeSession)
    now = datetime(2026, 11, 21, 10, tzinfo=timezone.utc)
    tenant_id, patient_id = uuid4(), uuid4()
    monkeypatch.setattr(settings, 'test_mode', False)
    test_mode_no_data.evaluate_replay_no_data(now, True, tenant_id, patient_id)
    monkeypatch.setattr(settings, 'test_mode', True)
    test_mode_no_data.evaluate_replay_no_data(now, False, tenant_id, patient_id)
    assert calls == []
    test_mode_no_data.evaluate_replay_no_data(now, True, tenant_id, patient_id)
    assert calls == [(now, {'tenant_id': tenant_id, 'patient_id': patient_id}), 'committed']


def test_scoped_replay_does_not_create_alerts_for_other_patients(db_session):
    """
    Two patients in separate tenants are both overdue at hour 24. Running replay scoped to
    patient A must create one alert for A and none for B; repeating A must create zero
    duplicates. Explicitly evaluating B afterward must then create its own alert.
    """
    from datetime import timedelta
    from sqlalchemy import select
    from app.models.alert import Alert
    from app.services.no_data_alerts import evaluate_no_data_alerts
    from tests.test_alert_engine import T, setup_patient

    tenant_a, patient_a, _ = setup_patient(db_session)
    tenant_b, patient_b, _ = setup_patient(db_session)
    patient_a.monitoring_started_at = T
    patient_b.monitoring_started_at = T
    db_session.flush()
    now = T + timedelta(hours=24)
    assert evaluate_no_data_alerts(db_session, now, tenant_id=tenant_a.id, patient_id=patient_a.id) == 1
    assert len(db_session.scalars(select(Alert).where(Alert.patient_id == patient_a.id)).all()) == 1
    assert db_session.scalars(select(Alert).where(Alert.patient_id == patient_b.id)).all() == []
    assert evaluate_no_data_alerts(db_session, now, tenant_id=tenant_a.id, patient_id=patient_a.id) == 0
    assert evaluate_no_data_alerts(db_session, now, tenant_id=tenant_b.id, patient_id=patient_b.id) == 1
