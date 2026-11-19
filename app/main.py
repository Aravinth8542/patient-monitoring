from fastapi import FastAPI

app = FastAPI(
    title="Patient Monitoring API",
    description="Backend API for remote patient monitoring",
    version="1.0.0"
)


@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.get("/")
def root():
    return {
        "message": "Patient Monitoring API",
        "version": "1.0.0"
    }