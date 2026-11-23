from sqlalchemy import text


def test_database_connection(db_session):
    """
    The database fixture must connect to the dedicated PostgreSQL test database, not a
    development or production database. SELECT current_database() must return
    patient_monitoring_test.
    """
    result = db_session.execute(
        text("SELECT current_database()")
    ).scalar_one()

    assert result == "patient_monitoring_test"


from uuid import uuid4

from sqlalchemy import text

from app.models.tenant import Tenant


def test_transaction_rollback(db_session):
    """
    Create and commit a temporary tenant inside the test-managed database fixture. Confirm
    it is visible within this test; the following isolation test checks that the fixture
    ultimately rolls back the data.
    """
    tenant_id = uuid4()

    tenant = Tenant(
        id=tenant_id,
        name="Temporary Test Tenant",
    )

    db_session.add(tenant)
    db_session.commit()

    result = db_session.execute(
        text("SELECT COUNT(*) FROM tenants WHERE id = :tenant_id"),
        {"tenant_id": tenant_id},
    ).scalar_one()

    assert result == 1


def test_previous_transaction_was_rolled_back(db_session):
    """
    Search for the temporary tenant created and committed by the preceding fixture test.
    Finding zero rows demonstrates that the outer test transaction was rolled back and data
    does not leak between tests.
    """
    result = db_session.execute(
        text("""
            SELECT COUNT(*)
            FROM tenants
            WHERE name = 'Temporary Test Tenant'
        """)
    ).scalar_one()

    assert result == 0


def test_api_client_health(api_client):
    """
    Send GET /health through the FastAPI test client. A 200 response confirms the
    application can serve a basic HTTP request through its configured test dependencies.
    """
    response = api_client.get("/health")

    assert response.status_code == 200