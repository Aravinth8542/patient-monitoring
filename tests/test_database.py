from sqlalchemy import text


def test_database_connection(db_session):
    result = db_session.execute(
        text("SELECT current_database()")
    ).scalar_one()

    assert result == "patient_monitoring_test"


from uuid import uuid4

from sqlalchemy import text

from app.models.tenant import Tenant


def test_transaction_rollback(db_session):
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
    result = db_session.execute(
        text("""
            SELECT COUNT(*)
            FROM tenants
            WHERE name = 'Temporary Test Tenant'
        """)
    ).scalar_one()

    assert result == 0


def test_api_client_health(api_client):
    response = api_client.get("/health")

    assert response.status_code == 200