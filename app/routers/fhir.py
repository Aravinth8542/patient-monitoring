"""FHIR R4 Observation search with stable keyset paging."""
import base64
import binascii
import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, or_, select, text, func
from sqlalchemy.orm import Session

from app.clock import get_current_time
from app.config import settings
from app.database import get_runtime_db
from app.models.observation import Observation
from app.security.staff_context import StaffIdentity, require_staff_context
from app.services.fhir_observation import observation_to_fhir, CODES

router = APIRouter(prefix="/fhir", tags=["FHIR R4"])

CODE_TO_KIND = {v[0]: k for k, v in CODES.items()}
CODE_TO_KIND["59408-5"] = "spo2"  # accepted alternate LOINC for pulse oximetry
CODE_TO_KIND.update({"symptom-score": "symptom_score", "medication-taken": "medication_taken"})
MAX_PAGE = 100


def _date_filters(raw_dates):
    bounds = []
    for item in raw_dates:
        if not item.startswith(("ge", "lt")):
            raise HTTPException(422, "date_requires_ge_or_lt_prefix")
        prefix, value = item[:2], item[2:]
        try:
            instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(422, "invalid_date_filter") from None
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise HTTPException(422, "date_requires_timezone")
        bounds.append((prefix, instant.astimezone(timezone.utc)))
    return bounds


def _encode_cursor(payload):
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor):
    try:
        if len(cursor) > 2048:
            raise ValueError()
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("v") != 1:
            raise ValueError()
        return value
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
        raise HTTPException(422, "invalid_fhir_cursor") from None


@router.get("/Observation")
def search_observations(
    request: Request,
    patient: UUID = Query(...),
    code: str | None = Query(default=None),
    count: int = Query(default=50, ge=1, le=MAX_PAGE, alias="_count"),
    sort: str = Query(default="date", alias="_sort"),
    cursor: str | None = Query(default=None, max_length=2048, alias="_cursor"),
    staff: StaffIdentity = Depends(require_staff_context),
    db: Session = Depends(get_runtime_db),
    now: datetime = Depends(get_current_time),
):
    if staff.role != "clinician":
        raise HTTPException(403, "clinician_role_required")
    if sort not in ("date", "-date"):
        raise HTTPException(422, "unsupported_fhir_sort")
    if code is not None and code not in CODE_TO_KIND:
        raise HTTPException(422, "unsupported_fhir_code")
    bounds = _date_filters(request.query_params.getlist("date"))
    allowed = db.execute(text("""SELECT 1 FROM public.patients p
        WHERE p.id=:patient AND p.tenant_id=:tenant AND p.consent_active
          AND public.app_staff_can_read(p.id)"""),
        {"patient": patient, "tenant": staff.tenant_id}).scalar_one_or_none()
    if allowed is None:
        raise HTTPException(404, "patient_not_found")

    signature = {
        "patient": str(patient), "tenant": str(staff.tenant_id),
        "staff": str(staff.id), "code": code, "date": [(p, d.isoformat()) for p, d in bounds],
        "sort": sort, "count": count,
    }
    if cursor:
        state = _decode_cursor(cursor)
        if state.get("q") != signature:
            raise HTTPException(422, "cursor_query_mismatch")
        try:
            snapshot = datetime.fromisoformat(state["snapshot"])
            inserted_snapshot = datetime.fromisoformat(state["inserted_snapshot"])
            last_time = datetime.fromisoformat(state["last_time"])
            last_id = UUID(state["last_id"])
            if snapshot.tzinfo is None or inserted_snapshot.tzinfo is None or last_time.tzinfo is None:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise HTTPException(422, "invalid_fhir_cursor") from None
    else:
        # Production uses database time for a stable receipt-time watermark.
        # During replay, receipt timestamps may be simulated in the future;
        # include observations received by the requested test time.
        db_snapshot, inserted_snapshot = db.execute(
            text("SELECT statement_timestamp(), clock_timestamp()")
        ).one()
        snapshot = max(db_snapshot, now) if settings.test_mode else db_snapshot
        last_time = last_id = None

    filters = [
        Observation.tenant_id == staff.tenant_id,
        Observation.patient_id == patient,
        Observation.received_at <= snapshot,
        Observation.inserted_at <= inserted_snapshot,
    ]
    if code:
        filters.append(Observation.type == CODE_TO_KIND[code])
    for prefix, instant in bounds:
        filters.append(Observation.effective_at >= instant if prefix == "ge"
                       else Observation.effective_at < instant)
    if last_time is not None:
        filters.append(
            or_(Observation.effective_at > last_time,
                and_(Observation.effective_at == last_time, Observation.id > last_id))
            if sort == "date" else
            or_(Observation.effective_at < last_time,
                and_(Observation.effective_at == last_time, Observation.id < last_id))
        )
    order = (Observation.effective_at.asc(), Observation.id.asc()) if sort == "date" else (
        Observation.effective_at.desc(), Observation.id.desc())
    rows = db.scalars(select(Observation).where(*filters).order_by(*order).limit(count + 1)).all()
    page = rows[:count]
    entries = [{"fullUrl": f"urn:uuid:{item.id}", "resource": observation_to_fhir(item),
                "search": {"mode": "match"}} for item in page]
    bundle = {"resourceType": "Bundle", "type": "searchset", "entry": entries,
              "link": [{"relation": "self", "url": str(request.url)}]}
    if len(rows) > count:
        last = page[-1]
        next_state = {
            "v": 1, "q": signature, "snapshot": snapshot.isoformat(),
            "inserted_snapshot": inserted_snapshot.isoformat(),
            "last_time": last.effective_at.isoformat(), "last_id": str(last.id),
        }
        # Use the incoming request's URL and preserve all filters.
        next_url = str(request.url.include_query_params(_cursor=_encode_cursor(next_state)))
        bundle["link"].append({"relation": "next", "url": next_url})
    if db.execute(text("SELECT public.app_staff_assigned(:patient)"),
                  {"patient": patient}).scalar_one():
        # Existing permitted action; dedicated FHIR audit action is a later migration.
        db.execute(text("SELECT public.app_record_staff_audit(:patient, 'patient_metadata_read', :now)"),
                   {"patient": patient, "now": now})
    else:
        db.execute(text("SELECT public.app_record_emergency_read(:patient, :now)"),
                   {"patient": patient, "now": now})
    db.commit()
    return bundle
