"""Advance missing-data detection on an authorized alert read during HTTP test replay."""
from datetime import datetime
from uuid import UUID

from app.config import settings
from app.database import SessionLocal
from app.services.no_data_alerts import evaluate_no_data_alerts


def evaluate_replay_no_data(now: datetime, has_test_header: bool,
                            tenant_id: UUID, patient_id: UUID) -> None:
    """Use the evaluator's HTTP clock only for explicit TEST_MODE replay requests.

    The normal scheduler is independent and unchanged. This evaluation needs the
    owner database session because it must not reuse a clinician RLS-scoped session;
    it must not reuse a clinician's RLS-scoped session.
    """
    if not settings.test_mode or not has_test_header:
        return
    with SessionLocal() as db:
        evaluate_no_data_alerts(db, now, tenant_id=tenant_id, patient_id=patient_id)
        db.commit()
