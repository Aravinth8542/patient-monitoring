"""Scheduled missing-data detection and recovery; caller commits the transaction."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from app.models.patient import Patient
from app.models.observation import Observation
from app.models.alert import Alert
from app.models.tenant import Tenant
from app.services.alert_rules import rules_for


def evaluate_no_data_alerts(db: Session, now: datetime) -> int:
    """Evaluate every consenting patient, including those without observations.

    A missing-data episode starts at the last observation's effective time, or
    monitoring start if none exists. Late backfills correct obsolete episodes;
    genuine reporting recovery resolves the previous episode. Historical alerts
    remain available, and subsequent silence creates a distinct episode.
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
    patients = db.execute(
        select(Patient.tenant_id, Patient.id, Patient.monitoring_started_at,
               last_reading.c.last_at, Tenant.alert_rules)
        .join(Tenant, Tenant.id == Patient.tenant_id)
        .outerjoin(last_reading, (last_reading.c.tenant_id == Patient.tenant_id) &
                             (last_reading.c.patient_id == Patient.id))
        .where(Patient.consent_active.is_(True), Patient.monitoring_started_at <= now)
    ).all()
    inserted = 0
    for tenant_id, patient_id, started_at, last_at, config in patients:
        # An observation recorded before enrollment must not move the baseline
        # earlier than the patient's monitoring start.
        baseline = max(started_at, last_at) if last_at is not None else started_at
        for rule in rules_for(config):
            if rule['type'] != 'missing_data':
                continue
            window = timedelta(hours=int(rule['window_hours']))
            overdue = baseline <= now - window
            old_alerts = db.scalars(select(Alert).where(
                Alert.tenant_id == tenant_id, Alert.patient_id == patient_id,
                Alert.rule == rule['id'], Alert.status.in_(['open', 'acknowledged']),
                Alert.episode_start < baseline,
            )).all()
            for alert in old_alerts:
                if overdue or (alert.created_at - window < baseline <= alert.created_at):
                    # The old episode start was invalidated by a backfilled
                    # reading. If still overdue, a new episode is due below.
                    alert.status = 'retracted'
                    alert.retracted_at = now
                    alert.retraction_reason = 'late_observation_correction'
                else:
                    # Reporting resumed after the original alert became due.
                    alert.status = 'resolved'
                    alert.resolved_at = now
                    # resolved_by=None denotes an automatic system transition.
            if not overdue:
                continue
            statement = insert(Alert).values(
                id=uuid4(), tenant_id=tenant_id, patient_id=patient_id,
                rule=rule['id'], severity=rule['severity'], status='open',
                episode_start=baseline, created_at=now,
            ).on_conflict_do_nothing(constraint='uq_alert_episode').returning(Alert.id)
            if db.execute(statement).scalar_one_or_none() is not None:
                inserted += 1
    return inserted
