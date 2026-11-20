from datetime import datetime
from fastapi import FastAPI, Depends
from app.clock import get_current_time
from app.routers.ingestion import router as ingestion_router
from app.routers.staff import router as staff_router
from app.routers.patients import router as patients_router
from app.routers.audit import router as audit_router

from app.routers.alerts import router as alerts_router
from app.routers.aggregates import router as aggregates_router

app = FastAPI(
    title="Patient Monitoring API",
    description="Backend API for remote patient monitoring",
    version="1.0.0"
)

app.include_router(ingestion_router)
app.include_router(staff_router)
app.include_router(patients_router)
app.include_router(audit_router)
app.include_router(alerts_router)
app.include_router(aggregates_router)

@app.get("/health")
def health_check(_now: datetime = Depends(get_current_time)):
    return {"status": "healthy"}

@app.get("/")
def root(_now: datetime = Depends(get_current_time)):
    return {
        "message": "Patient Monitoring API",
        "version": "1.0.0"
    }