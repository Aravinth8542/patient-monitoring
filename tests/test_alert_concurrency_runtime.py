"""Reproduce a missed alert across independent authenticated ingestion transactions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import settings
from app.main import app
from app.models.alert import Alert
from app.models.observation import Observation
from app.routers import ingestion
from app.services.device_auth import hash_device_token
from tests.test_alert_engine import setup_patient


def test_concurrent_cross_midnight_uploads_create_one_alert(monkeypatch):
    """Concurrent uploads contend for the patient lock; together readings qualify."""
    for url in (settings.database_url, settings.test_database_url,
                settings.runtime_database_url):
        assert url and make_url(url).database == 'patient_monitoring_test'
    assert make_url(settings.runtime_database_url).username == 'patient_monitoring_runtime'
    assert not app.dependency_overrides

    owner = create_engine(settings.test_database_url, pool_pre_ping=True)
    token = uuid4().hex
    now = datetime(2026, 11, 28, 0, 1, tzinfo=timezone.utc)
    start = now - timedelta(minutes=11)
    barrier = Barrier(2, timeout=15)
    original = ingestion.lock_patient
    monkeypatch.setattr(settings, 'test_mode', True)

    def synchronized_lock(db, tenant_id, patient_id):
        assert db.execute(text('SELECT current_user')).scalar_one() == 'patient_monitoring_runtime'
        # Both requests reach the lock before either is allowed to acquire it.
        barrier.wait()
        return original(db, tenant_id, patient_id)

    monkeypatch.setattr(ingestion, 'lock_patient', synchronized_lock)
    tenant_id = patient_id = device_id = None
    try:
        with Session(owner) as db:
            tenant, patient, device = setup_patient(db)
            device.token_hash = hash_device_token(token)
            patient.monitoring_started_at = start - timedelta(hours=1)
            tenant_id, patient_id, device_id = tenant.id, patient.id, device.id
            db.commit()

        def upload(key, minutes):
            payload = {
                'batch_id': key,
                'sent_at_device': now.isoformat(),
                'observations': [
                    {'client_obs_id': f'{key}-{minute}', 'type': 'spo2',
                     'effective_at': (start + timedelta(minutes=minute)).isoformat(),
                     'value': 90, 'unit': '%'} for minute in minutes
                ],
            }
            with TestClient(app) as client:
                response = client.post(
                    f'/v1/devices/{device_id}/observations:batch',
                    json=payload,
                    headers={'Authorization': f'Bearer {token}',
                             'Idempotency-Key': key, 'X-Test-Now': now.isoformat()},
                )
            assert response.status_code == 200, response.text
            assert [r['status'] for r in response.json()['results']] == ['accepted'] * len(minutes)

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(upload, 'batch-a', [0, 5])
            b = pool.submit(upload, 'batch-b', [10])
            a.result()
            b.result()

        with Session(owner) as db:
            observations = db.scalars(select(Observation).where(
                Observation.patient_id == patient_id)).all()
            assert sorted(o.effective_at for o in observations) == [
                start + timedelta(minutes=m) for m in (0, 5, 10)]
            alerts = db.scalars(select(Alert).where(
                Alert.patient_id == patient_id, Alert.rule == 'low_spo2')).all()
            assert len(alerts) == 1, f'Expected one low_spo2 alert, found {len(alerts)}'
            assert alerts[0].episode_start == start
            assert alerts[0].status == 'open'
    finally:
        try:
            if tenant_id is not None:
                with owner.begin() as conn:
                    conn.execute(text('DELETE FROM ingestion_requests WHERE device_id=:id'), {'id': device_id})
                    for table in ('alerts', 'observation_hourly_aggregates',
                                  'observation_daily_aggregates', 'observations', 'devices', 'patients'):
                        conn.execute(text(f'DELETE FROM {table} WHERE tenant_id=:id'), {'id': tenant_id})
                    conn.execute(text('DELETE FROM tenants WHERE id=:id'), {'id': tenant_id})
        finally:
            owner.dispose()
