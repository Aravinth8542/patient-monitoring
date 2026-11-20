"""Scheduled no-data check; no HTTP request or new infrastructure required."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from app.models.patient import Patient
from app.models.observation import Observation
from app.models.alert import Alert


def evaluate_no_data_alerts(db: Session, now: datetime) -> int:
    """Create one low-severity alert per last-reading timestamp after 24h silence.

    This trusted internal job uses the owner DB connection, not an HTTP runtime
    session. Its caller owns the transaction. Patients without observations
    cannot be evaluated until an enrollment timestamp is available.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('now must be timezone-aware')
    now = now.astimezone(timezone.utc)
    last_reading = (select(
        Observation.tenant_id.label('tenant_id'),
        Observation.patient_id.label('patient_id'),
        func.max(Observation.effective_at).label('last_at'),
    ).where(Observation.effective_at <= now, Observation.received_at <= now)
     .group_by(Observation.tenant_id, Observation.patient_id).subquery())
    due = db.execute(select(last_reading.c.tenant_id, last_reading.c.patient_id,
                            last_reading.c.last_at)
        .join(Patient, (Patient.tenant_id == last_reading.c.tenant_id) &
                       (Patient.id == last_reading.c.patient_id))
        .where(Patient.consent_active.is_(True),
               last_reading.c.last_at <= now - timedelta(hours=24))).all()
    inserted = 0
    for tenant_id, patient_id, last_at in due:
        statement = insert(Alert).values(
            id=uuid4(), tenant_id=tenant_id, patient_id=patient_id,
            rule='no_data', severity='low', status='open',
            episode_start=last_at, created_at=now,
        ).on_conflict_do_nothing(constraint='uq_alert_episode').returning(Alert.id)
        if db.execute(statement).scalar_one_or_none() is not None:
            inserted += 1
    return inserted
