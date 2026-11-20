import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.engine import make_url
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db, get_runtime_db
from app.security.tenant_context import require_device_context, get_runtime_db
from app.config import settings


@pytest.fixture
def db_session():
    test_url = settings.test_database_url

    if not test_url:
        raise RuntimeError("TEST_DATABASE_URL is not configured")

    database_name = make_url(test_url).database

    if database_name != "patient_monitoring_test":
        raise RuntimeError(
            "Refusing to run database tests against a non-test database"
        )

    engine = create_engine(test_url, pool_pre_ping=True)

    try:
        with engine.connect() as connection:
            transaction = connection.begin()

            session = Session(
                bind=connection,
                join_transaction_mode="create_savepoint",
            )

            try:
                yield session
            finally:
                session.close()
                transaction.rollback()
    finally:
        engine.dispose()


@pytest.fixture
def api_client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_runtime_db] = override_get_db
    app.dependency_overrides[require_device_context] = lambda: None
    app.dependency_overrides[get_runtime_db] = override_get_db

    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_runtime_db, None)
        app.dependency_overrides.pop(require_device_context, None)
        app.dependency_overrides.pop(get_runtime_db, None)