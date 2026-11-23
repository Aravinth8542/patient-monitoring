
"""HTTP authorization checks for both summary endpoints under runtime RLS."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.database import get_runtime_db
from app.models.tenant import Tenant
from app.models.patient import Patient
from app.models.staff import StaffUser, CareTeamMembership
from app.security.staff_context import StaffIdentity, require_staff_context
from app.services.staff_auth import hash_staff_token


@pytest.mark.parametrize("granularity", ["hourly", "daily"])
def test_aggregate_endpoint_clinician_access(db_session, granularity):
    """
    The clinician belongs to the assigned patient's care team but not the second patient's.
    Both the direct hourly/daily endpoint and the rollups alias must return an empty list
    for a valid patient with no measurements, reject a timezone-less start or limit 501,
    hide the unassigned patient with 404, and reject an auditor with 403. The rollups
    endpoint additionally requires a valid 'hour' or 'day' granularity.
    """
    tenant = Tenant(
        id=uuid.uuid4(),
        name="aggregate-http-" + uuid.uuid4().hex,
    )
    db_session.add(tenant)
    db_session.flush()

    assigned = Patient(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        external_id="agg-assigned",
    )
    unassigned = Patient(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        external_id="agg-unassigned",
    )
    db_session.add_all([assigned, unassigned])
    db_session.flush()

    token = "aggregate-" + uuid.uuid4().hex
    staff = StaffUser(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        role="clinician",
        token_hash=hash_staff_token(token),
    )
    db_session.add(staff)
    db_session.flush()

    db_session.add(
        CareTeamMembership(
            tenant_id=tenant.id,
            staff_id=staff.id,
            patient_id=assigned.id,
        )
    )
    db_session.flush()

    # Cache UUIDs before switching roles or committing.
    # SQLAlchemy expires ORM objects after commit, and RLS may
    # prevent their attributes from being refreshed.
    assigned_id = assigned.id
    unassigned_id = unassigned.id
    staff_id = staff.id
    tenant_id = tenant.id

    db_session.execute(
        text("SET LOCAL ROLE patient_monitoring_runtime")
    )
    db_session.execute(
        text("SELECT * FROM public.app_authorize_staff(:digest)"),
        {"digest": hash_staff_token(token)},
    )

    app.dependency_overrides[get_runtime_db] = lambda: db_session
    app.dependency_overrides[require_staff_context] = lambda: StaffIdentity(
        id=staff_id,
        tenant_id=tenant_id,
        role="clinician",
    )

    try:
        with TestClient(app) as client:
            path = (
                f"/v1/patients/{assigned_id}/"
                f"aggregates/{granularity}"
            )

            response = client.get(path)
            assert response.status_code == 200, response.text
            assert response.json()["aggregates"] == []

            invalid_start = client.get(
                path,
                params={"start": "2026-11-20T10:00:00"},
            )
            assert invalid_start.status_code == 422

            invalid_limit = client.get(
                path,
                params={"limit": 501},
            )
            assert invalid_limit.status_code == 422

            denied = client.get(
                f"/v1/patients/{unassigned_id}/"
                f"aggregates/{granularity}"
            )
            assert denied.status_code == 404

            rollup_path = f"/v1/patients/{assigned_id}/rollups"
            singular = "hour" if granularity == "hourly" else "day"
            rollup = client.get(rollup_path, params={"granularity": singular, "metric": "heart_rate"})
            assert rollup.status_code == 200, rollup.text
            assert rollup.json()["granularity"] == singular
            assert rollup.json()["aggregates"] == []
            assert client.get(rollup_path).status_code == 422
            assert client.get(rollup_path, params={"granularity": "weekly"}).status_code == 422
            assert client.get(f"/v1/patients/{unassigned_id}/rollups", params={"granularity": singular}).status_code == 404

            app.dependency_overrides[
                require_staff_context
            ] = lambda: StaffIdentity(
                id=staff_id,
                tenant_id=tenant_id,
                role="auditor",
            )

            forbidden = client.get(path)
            assert forbidden.status_code == 403
            forbidden_rollup = client.get(rollup_path, params={"granularity": singular})
            assert forbidden_rollup.status_code == 403

    finally:
        app.dependency_overrides.pop(get_runtime_db, None)
        app.dependency_overrides.pop(require_staff_context, None)
