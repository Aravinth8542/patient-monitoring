"""FHIR HTTP integration coverage against the real PostgreSQL RLS role."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import get_runtime_db
from app.main import app
from app.models.device import Device
from app.models.observation import Observation
from app.models.patient import Patient
from app.models.staff import CareTeamMembership, StaffUser
from app.models.tenant import Tenant
from app.security.staff_context import StaffIdentity, require_staff_context
from app.services.staff_auth import hash_staff_token


@pytest.fixture
def fhir_context(db_session):
    tenant_id, patient_id, other_id, device_id, staff_id = (uuid.uuid4() for _ in range(5))
    token = 'fhir-' + uuid.uuid4().hex
    db_session.add(Tenant(id=tenant_id, name='fhir-' + uuid.uuid4().hex))
    db_session.flush()
    db_session.add_all([
        Patient(id=patient_id, tenant_id=tenant_id, external_id='fhir-allowed'),
        Patient(id=other_id, tenant_id=tenant_id, external_id='fhir-denied'),
    ])
    db_session.flush()
    db_session.add(Device(id=device_id, tenant_id=tenant_id, patient_id=patient_id))
    db_session.add(StaffUser(id=staff_id, tenant_id=tenant_id, role='clinician', token_hash=hash_staff_token(token)))
    db_session.flush()
    db_session.add(CareTeamMembership(tenant_id=tenant_id, patient_id=patient_id, staff_id=staff_id))
    db_session.flush()

    def insert_observation(effective, *, received=None, kind='heart_rate'):
        obs_id = uuid.uuid4()
        db_session.add(Observation(
            id=obs_id, tenant_id=tenant_id, patient_id=patient_id, device_id=device_id,
            client_obs_id=str(obs_id), type=kind, value=Decimal('72'), unit='/min',
            original_effective_at=effective, effective_at=effective,
            received_at=received or datetime.now(timezone.utc), original_payload={},
        ))
        db_session.flush()
        return obs_id

    def authorize():
        db_session.execute(text('SET LOCAL ROLE patient_monitoring_runtime'))
        db_session.execute(text('SELECT * FROM public.app_authorize_staff(:digest)'),
                           {'digest': hash_staff_token(token)})

    def identity(role='clinician'):
        return StaffIdentity(id=staff_id, tenant_id=tenant_id, role=role)

    app.dependency_overrides[get_runtime_db] = lambda: db_session
    app.dependency_overrides[require_staff_context] = identity
    try:
        yield {
            'patient': patient_id, 'other': other_id, 'insert': insert_observation,
            'authorize': authorize, 'identity': identity, 'session': db_session,
        }
    finally:
        app.dependency_overrides.pop(get_runtime_db, None)
        app.dependency_overrides.pop(require_staff_context, None)


def test_fhir_http_filters_and_care_team(fhir_context):
    """
    An assigned clinician searches a patient's FHIR observations with heart-rate LOINC
    8867-4 and a date lower bound. Of the seeded heart-rate and SpO2 events, only the
    matching heart-rate ID should appear in the searchset Bundle. Searching another patient
    returns 404, while changing the identity to auditor returns 403.
    """
    ctx = fhir_context
    base = datetime(2026, 11, 19, 8, tzinfo=timezone.utc)
    included = ctx['insert'](base, kind='heart_rate')
    ctx['insert'](base + timedelta(hours=1), kind='spo2')
    ctx['authorize']()
    with TestClient(app) as client:
        response = client.get('/fhir/Observation', params={
            'patient': str(ctx['patient']), 'code': '8867-4',
            'date': 'ge2026-11-19T00:00:00Z', '_count': 10,
        })
        assert response.status_code == 200, response.text
        bundle = response.json()
        assert bundle['resourceType'] == 'Bundle'
        assert bundle['type'] == 'searchset'
        assert [entry['resource']['id'] for entry in bundle['entry']] == [str(included)]
        denied = client.get('/fhir/Observation', params={'patient': str(ctx['other'])})
        assert denied.status_code == 404
        app.dependency_overrides[require_staff_context] = lambda: ctx['identity']('auditor')
        forbidden = client.get('/fhir/Observation', params={'patient': str(ctx['patient'])})
        assert forbidden.status_code == 403


def test_fhir_cursor_excludes_late_upload_between_pages(fhir_context):
    """
    Seed events at 08:00, 09:00 and 10:00 and request one result per page. After page one,
    insert a late-arriving event whose effective time is 08:30 but whose receipt is after
    the page snapshot. Following the returned next links must yield the original 09:00 and
    10:00 events, not the newly arrived 08:30 event.
    """
    ctx = fhir_context
    base = datetime(2026, 11, 19, 8, tzinfo=timezone.utc)
    ids = [ctx['insert'](base + timedelta(hours=i)) for i in range(3)]
    ctx['authorize']()
    with TestClient(app) as client:
        first = client.get('/fhir/Observation', params={'patient': str(ctx['patient']), '_count': 1})
        assert first.status_code == 200, first.text
        assert [x['resource']['id'] for x in first.json()['entry']] == [str(ids[0])]
        next_url = next(link['url'] for link in first.json()['link'] if link['relation'] == 'next')
        # Emulate a later device upload, with an event timestamp between page 1 and page 2.
        # Its receipt time must be later than the original page's snapshot watermark.
        ctx['session'].execute(text('SET LOCAL ROLE NONE'))
        late_id = ctx['insert'](base + timedelta(minutes=30),
                                received=datetime.now(timezone.utc) + timedelta(minutes=1))
        ctx['authorize']()
        second = client.get(next_url)
        assert second.status_code == 200, second.text
        assert [x['resource']['id'] for x in second.json()['entry']] == [str(ids[1])]
        third_url = next(link['url'] for link in second.json()['link'] if link['relation'] == 'next')
        third = client.get(third_url)
        assert third.status_code == 200, third.text
        assert [x['resource']['id'] for x in third.json()['entry']] == [str(ids[2])]
        assert str(late_id) not in [str(ids[0]), str(ids[1]), str(ids[2])]


def test_fhir_test_mode_includes_simulated_future_receipt(fhir_context, monkeypatch):
    """
    A replayed observation can have a received_at later than the host machine's
    wall clock. With TEST_MODE enabled and X-Test-Now at that simulated receipt
    time, the FHIR search must return the observation instead of hiding it
    behind PostgreSQL's real-time pagination watermark.
    """
    from app.clock import get_current_time
    from app.config import settings

    ctx = fhir_context
    db_time = ctx['session'].execute(text("SELECT statement_timestamp()")).scalar_one()
    replay_now = db_time + timedelta(days=30)
    event_id = ctx['insert'](replay_now - timedelta(minutes=1),
                             received=replay_now)
    ctx['authorize']()
    monkeypatch.setattr(settings, 'test_mode', True)
    app.dependency_overrides[get_current_time] = lambda: replay_now
    try:
        with TestClient(app) as client:
            response = client.get('/fhir/Observation',
                                  params={'patient': str(ctx['patient'])},
                                  headers={'X-Test-Now': replay_now.isoformat()})
            assert response.status_code == 200, response.text
            ids = [item['resource']['id'] for item in response.json()['entry']]
            assert str(event_id) in ids
    finally:
        app.dependency_overrides.pop(get_current_time, None)


def test_fhir_cursor_excludes_new_upload_with_same_simulated_receipt(fhir_context, monkeypatch):
    """
    A TEST_MODE search must keep its original result set across pages even
    when a later upload uses the same simulated receipt time as page one.
    The new observation falls between the first and second original events
    by effective time, so a receipt-time-only watermark would leak it.
    """
    from app.clock import get_current_time
    from app.config import settings

    ctx = fhir_context
    db_time = ctx['session'].execute(text('SELECT statement_timestamp()')).scalar_one()
    replay_now = db_time + timedelta(days=30)
    base = replay_now - timedelta(hours=3)
    original_ids = [ctx['insert'](base + timedelta(hours=i), received=replay_now)
                    for i in range(3)]
    ctx['authorize']()
    monkeypatch.setattr(settings, 'test_mode', True)
    app.dependency_overrides[get_current_time] = lambda: replay_now
    try:
        with TestClient(app) as client:
            first = client.get('/fhir/Observation',
                               params={'patient': str(ctx['patient']), '_count': 1},
                               headers={'X-Test-Now': replay_now.isoformat()})
            assert first.status_code == 200, first.text
            assert [e['resource']['id'] for e in first.json()['entry']] == [str(original_ids[0])]
            next_url = next(link['url'] for link in first.json()['link']
                            if link['relation'] == 'next')

            # Simulate a later upload at the exact same replay-clock instant.
            ctx['session'].execute(text('SET LOCAL ROLE NONE'))
            inserted_later = ctx['insert'](base + timedelta(minutes=30),
                                           received=replay_now)
            ctx['authorize']()

            seen = [str(original_ids[0])]
            while next_url:
                page = client.get(next_url,
                                  headers={'X-Test-Now': replay_now.isoformat()})
                assert page.status_code == 200, page.text
                seen.extend(e['resource']['id'] for e in page.json()['entry'])
                next_url = next((link['url'] for link in page.json()['link']
                                 if link['relation'] == 'next'), None)
            assert seen == [str(item) for item in original_ids]
            assert str(inserted_later) not in seen
    finally:
        app.dependency_overrides.pop(get_current_time, None)

