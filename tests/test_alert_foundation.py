from sqlalchemy import text
from app.config import settings
from app.database import open_alert_session
import pytest


def test_alert_foundation_schema(db_session):
    columns = set(db_session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='alerts'")).scalars())
    assert {"episode_end", "qualified_at", "is_retrospective", "superseded_by_id"} <= columns
    assert db_session.execute(text("SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid='public.pending_alert_evaluations'::regclass")).scalar_one()
    assert not db_session.execute(text("SELECT has_table_privilege('patient_monitoring_runtime','public.pending_alert_evaluations','INSERT')")).scalar_one()
    assert not db_session.execute(text("SELECT pg_has_role('patient_monitoring_runtime','patient_monitoring_alert_processor','MEMBER')")).scalar_one()


def test_alert_processor_login_is_restricted():
    if not settings.alert_database_url:
        pytest.skip("ALERT_DATABASE_URL not configured")
    with open_alert_session() as db:
        assert db.execute(text("SELECT current_database()")).scalar_one() == "patient_monitoring_test"
        for table in ("observations", "alerts", "pending_alert_evaluations", "staff_users"):
            assert not db.execute(text("SELECT has_table_privilege(current_user, :table, 'INSERT')"), {"table": "public." + table}).scalar_one()
