"""Persist measurement alerts for a single consenting patient.

Call with a trusted, tenant-scoped database session. This is an explicit
batch evaluator, not a background worker or an HTTP authorization boundary.
The caller owns the transaction and must commit it.
"""
from uuid import UUID, uuid4
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from app.models.alert import Alert
from app.models.observation import Observation
from app.models.patient import Patient
from app.services.alert_rules import Reading, detect_episodes


def evaluate_patient_alerts(db: Session, tenant_id: UUID, patient_id: UUID, now, *, device_context: bool = False) -> int:
    """Insert newly detected episodes; return number inserted (idempotent)."""
    patient = db.execute(select(Patient).where(
        Patient.tenant_id == tenant_id, Patient.id == patient_id,
    )).scalar_one_or_none()
    if patient is None or not patient.consent_active:
        return 0

    rows = db.execute(select(Observation.type, Observation.effective_at, Observation.value)
        .where(Observation.tenant_id == tenant_id,
               Observation.patient_id == patient_id,
               Observation.type.in_(['spo2', 'heart_rate']),
               Observation.value.is_not(None),
               Observation.effective_at <= now)
        .order_by(Observation.effective_at)).all()
    episodes = detect_episodes([Reading(at=at, kind=kind, value=value)
                                for kind, at, value in rows])
    valid_episodes = {(episode.rule, episode.start) for episode in episodes}
    if device_context:
        # Database independently recomputes validity; the device cannot name or retract alerts.
        db.execute(text("SELECT public.app_reconcile_device_alerts(:tenant,:patient,:now)"),
                   {'tenant': tenant_id, 'patient': patient_id, 'now': now})
    else:
        existing = db.scalars(select(Alert).where(
            Alert.tenant_id == tenant_id, Alert.patient_id == patient_id,
            Alert.rule.in_(['low_spo2', 'hr_rise']),
            Alert.status.in_(['open', 'acknowledged', 'resolved']),
            Alert.episode_start <= now,
        )).all()
        for alert in existing:
            if (alert.rule, alert.episode_start) not in valid_episodes:
                alert.status = 'retracted'
                alert.retracted_at = now
                alert.retraction_reason = 'late_observation_correction'
    inserted = 0
    for episode in episodes:
        if device_context:
            created = db.execute(text("""SELECT public.app_insert_device_alert(
                :tenant, :patient, :rule, :severity, :start, :now)"""), {
                'tenant': tenant_id, 'patient': patient_id, 'rule': episode.rule,
                'severity': episode.severity, 'start': episode.start, 'now': now,
            }).scalar_one()
            inserted += int(created)
            continue
        statement = insert(Alert).values(
            id=uuid4(), tenant_id=tenant_id, patient_id=patient_id,
            rule=episode.rule, severity=episode.severity, status='open',
            episode_start=episode.start, created_at=now,
        ).on_conflict_do_nothing(constraint='uq_alert_episode').returning(Alert.id)
        if db.execute(statement).scalar_one_or_none() is not None:
            inserted += 1
    return inserted
