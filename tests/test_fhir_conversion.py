"""FHIR conversion tests independent of database fixtures."""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.fhir_observation import observation_to_fhir


def sample(kind, **kwargs):
    values = dict(id=uuid4(), patient_id=uuid4(), type=kind,
                  effective_at=datetime(2026, 11, 20, 10, tzinfo=timezone.utc),
                  value=Decimal('90'), systolic=Decimal('128'),
                  diastolic=Decimal('84'), medication_ref='med-001')
    values.update(kwargs)
    return SimpleNamespace(**values)


def test_heart_rate_fhir_resource():
    """
    Convert a heart-rate observation into FHIR R4. It must be an Observation with LOINC
    8867-4, a quantity unit of /min, and final status, so external clients can interpret the
    reading as a heart-rate measurement.
    """
    r = observation_to_fhir(sample('heart_rate'))
    assert r['resourceType'] == 'Observation'
    assert r['code']['coding'][0]['code'] == '8867-4'
    assert r['valueQuantity']['code'] == '/min'
    assert r['status'] == 'final'


def test_spo2_and_temperature_units():
    """
    Export SpO2 and body temperature observations to FHIR. Their valueQuantity units must
    use UCUM '%' and 'Cel' respectively, rather than application-specific unit spellings.
    """
    assert observation_to_fhir(sample('spo2'))['valueQuantity']['code'] == '%'
    assert observation_to_fhir(sample('body_temp'))['valueQuantity']['code'] == 'Cel'


def test_blood_pressure_single_resource_with_components():
    """
    Export one blood-pressure observation. It must not have a single top-level valueQuantity
    because pressure has two values; instead its components must use systolic LOINC 8480-6
    with value 128 and diastolic LOINC 8462-4 with value 84.
    """
    r = observation_to_fhir(sample('blood_pressure'))
    assert 'valueQuantity' not in r
    assert [c['code']['coding'][0]['code'] for c in r['component']] == ['8480-6', '8462-4']
    assert [c['valueQuantity']['value'] for c in r['component']] == [128, 84]


def test_symptom_and_medication_representation():
    """
    A symptom score is exported as numeric valueQuantity 90. A medication-taken event is
    exported with valueBoolean True and the medication identifier 'med-001' in its note,
    preserving the event's meaning without misrepresenting it as a vital sign.
    """
    assert observation_to_fhir(sample('symptom_score'))['valueQuantity']['value'] == 90
    med = observation_to_fhir(sample('medication_taken'))
    assert med['valueBoolean'] is True
    assert 'med-001' in med['note'][0]['text']


def test_naive_timestamp_rejected():
    """
    A heart-rate observation with a datetime lacking UTC offset is passed to the FHIR
    converter. Conversion must raise a timezone-related ValueError rather than emitting an
    ambiguous effectiveDateTime.
    """
    with pytest.raises(ValueError, match='timezone'):
        observation_to_fhir(sample('heart_rate', effective_at=datetime(2026, 11, 20)))
