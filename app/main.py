from datetime import datetime
from fastapi import FastAPI, Depends
from app.clock import get_current_time
from app.routers.ingestion import router as ingestion_router

app = FastAPI(
    title="Patient Monitoring API",
    description="Backend API for remote patient monitoring",
    version="1.0.0"
)

app.include_router(ingestion_router)

@app.get("/health")
def health_check(_now: datetime = Depends(get_current_time)):
    return {"status": "healthy"}

@app.get("/")
def root(_now: datetime = Depends(get_current_time)):
    return {
        "message": "Patient Monitoring API",
        "version": "1.0.0"
    }