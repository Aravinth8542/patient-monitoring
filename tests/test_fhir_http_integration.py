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
