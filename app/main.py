from fastapi import FastAPI
from app.routers.ingestion import router as ingestion_router

app = FastAPI(
    title="Patient Monitoring API",
    description="Backend API for remote patient monitoring",
    version="1.0.0"
)

app.include_router(ingestion_router)

@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.get("/")
def root():
    return {
        "message": "Patient Monitoring API",
        "version": "1.0.0"
    }