from enum import Enum
from datetime import datetime
from typing import Annotated, Literal, Any
from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict, TypeAdapter, AwareDatetime, model_validator


class ObservationType(str, Enum):
    HEART_RATE = "heart_rate"
    SPO2 = "spo2"
    BLOOD_PRESSURE = "blood_pressure"
    BODY_TEMP = "body_temp"
    SYMPTOM_SCORE = "symptom_score"
    MEDICATION_TAKEN = "medication_taken"



class ObservationInput(BaseModel):
    client_obs_id: str = Field(min_length=1, max_length=150)
    type: ObservationType
    effective_at: AwareDatetime

class HeartRateInput(ObservationInput):
    model_config = ConfigDict(extra="forbid")

    type: Literal[ObservationType.HEART_RATE]
    value: Decimal = Field(gt=0, le=300, allow_inf_nan=False)
    unit: Literal["/min"]


class BloodPressureInput(ObservationInput):
    model_config = ConfigDict(extra="forbid")

    type: Literal[ObservationType.BLOOD_PRESSURE]
    systolic: Decimal = Field(gt=0, le=300, allow_inf_nan=False)
    diastolic: Decimal = Field(gt=0, le=250, allow_inf_nan=False)
    unit: Literal["mm[Hg]"]

    @model_validator(mode="after")
    def validate_pressure(self):
        if self.systolic <= self.diastolic:
            raise ValueError(
                "Systolic pressure must be greater than diastolic pressure"
            )

        return self


class MedicationTakenInput(ObservationInput):
    model_config = ConfigDict(extra="forbid")

    type: Literal[ObservationType.MEDICATION_TAKEN]
    medication_ref: str = Field(min_length=1, max_length=150)


class SpO2Input(ObservationInput):
    model_config = ConfigDict(extra="forbid")

    type: Literal[ObservationType.SPO2]
    value: Decimal = Field(ge=0, le=100, allow_inf_nan=False)
    unit: Literal["%", "1"]


class BodyTempInput(ObservationInput):
    model_config = ConfigDict(extra="forbid")

    type: Literal[ObservationType.BODY_TEMP]
    value: Decimal
    unit: Literal["Cel", "[degF]"]


class SymptomScoreInput(ObservationInput):
    model_config = ConfigDict(extra="forbid")

    type: Literal[ObservationType.SYMPTOM_SCORE]
    value: int = Field(ge=0, le=10)


ObservationPayload = Annotated[
    HeartRateInput
    | SpO2Input
    | BloodPressureInput
    | BodyTempInput
    | SymptomScoreInput
    | MedicationTakenInput,
    Field(discriminator="type"),
]

class BatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(min_length=1, max_length=150)
    sent_at_device: AwareDatetime
    observations: list[Any] = Field(min_length=1)