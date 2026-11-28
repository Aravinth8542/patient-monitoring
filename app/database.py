from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from functools import lru_cache

from app.config import settings


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True
)


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()

# Protected HTTP operations must use a login that is NOT the table owner.
# Never silently fall back to the migration/owner URL.
@lru_cache(maxsize=1)
def make_runtime_engine():
    if not settings.runtime_database_url:
        raise RuntimeError("RUNTIME_DATABASE_URL must be configured for protected API operations")
    runtime_engine = create_engine(settings.runtime_database_url, pool_pre_ping=True)
    return runtime_engine


def get_runtime_db():
    from sqlalchemy import text
    with Session(make_runtime_engine()) as db:
            # Fail closed if credentials are owner/superuser or RLS bypass.
            row = db.execute(text("""SELECT current_user, rolsuper, rolbypassrls
                FROM pg_roles WHERE rolname = current_user""")).one()
            if row.rolsuper or row.rolbypassrls or row.current_user != 'patient_monitoring_runtime':
                raise RuntimeError("Runtime connection must authenticate as patient_monitoring_runtime")
            yield db


@lru_cache(maxsize=1)
def make_alert_engine():
    if not settings.alert_database_url:
        raise RuntimeError("ALERT_DATABASE_URL must be configured")
    return create_engine(settings.alert_database_url, pool_pre_ping=True, pool_size=2, max_overflow=0)


def open_alert_session():
    from sqlalchemy import text
    db = Session(make_alert_engine())
    try:
        row = db.execute(text("SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")).one()
        if row.current_user != "patient_monitoring_alert_processor" or row.rolsuper or row.rolbypassrls:
            raise RuntimeError("Invalid alert processor credentials")
        return db
    except BaseException:
        db.close()
        raise
