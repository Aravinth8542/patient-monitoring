from uuid import UUID

from fastapi import APIRouter, Header
from pydantic import TypeAdapter, ValidationError

from app.schemas.observation import BatchInput, ObservationPayload
from app.services.normalization import normalize_spo2, normalize_temperature
from app.schemas.observation import ObservationType

router = APIRouter(prefix="/v1/devices", tags=["Ingestion"])

observation_adapter = TypeAdapter(ObservationPayload)


@router.post("/{device_id}/observations:batch")
def ingest_observations(
    device_id: UUID,
    batch: BatchInput,
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    results = []

    for index, raw_observation in enumerate(batch.observations):
        try:
            observation = observation_adapter.validate_python(
                raw_observation
            )

            if observation.type == ObservationType.SPO2:
                normalize_spo2(observation.value, observation.unit)

            if observation.type == ObservationType.BODY_TEMP:
                normalize_temperature(observation.value, observation.unit)

            results.append({
                "index": index,
                "client_obs_id": observation.client_obs_id,
                "status": "accepted",
            })

        except ValidationError as exc:
            results.append({
            "index": index,
            "client_obs_id": (
                raw_observation.get("client_obs_id")
                if isinstance(raw_observation, dict)
                else None
            ),
            "status": "rejected",
            "reason": "validation_error",
            "errors": [
                {
                    "field": ".".join(str(part) for part in error["loc"]),
                    "message": error["msg"],
                    "type": error["type"],
                }
                for error in exc.errors()
            ],
        })


        except ValueError as exc:
            results.append({
                "index": index,
                "client_obs_id": (
                    raw_observation.get("client_obs_id")
                    if isinstance(raw_observation, dict)
                    else None
                ),
                "status": "rejected",
                "reason": "invalid_value",
                "errors": [
                    {
                        "field": "value",
                        "message": str(exc),
                        "type": "value_error",
                    }
                ],
            })

    return {
        "batch_id": batch.batch_id,
        "results": results,
    }