"""Authenticated identity endpoint; no patient data exposed before audit-on-read."""
from fastapi import APIRouter, Depends
from app.security.staff_context import StaffIdentity, require_staff_context

router = APIRouter(prefix="/v1/staff", tags=["Staff"])


@router.get("/me")
def staff_identity(staff: StaffIdentity = Depends(require_staff_context)):
    return {"id": staff.id, "tenant_id": staff.tenant_id, "role": staff.role}
