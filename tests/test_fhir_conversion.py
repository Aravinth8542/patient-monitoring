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
    r = observation_to_fhir(sample('heart_rate'))
    assert r['resourceType'] == 'Observation'
    assert r['code']['coding'][0]['code'] == '8867-4'
    assert r['valueQuantity']['code'] == '/min'
    assert r['status'] == 'final'


def test_spo2_and_temperature_units():
    assert observation_to_fhir(sample('spo2'))['valueQuantity']['code'] == '%'
    assert observation_to_fhir(sample('body_temp'))['valueQuantity']['code'] == 'Cel'


def test_blood_pressure_single_resource_with_components():
    r = observation_to_fhir(sample('blood_pressure'))
    assert 'valueQuantity' not in r
    assert [c['code']['coding'][0]['code'] for c in r['component']] == ['8480-6', '8462-4']
    assert [c['valueQuantity']['value'] for c in r['component']] == [128, 84]


def test_symptom_and_medication_representation():
    assert observation_to_fhir(sample('symptom_score'))['valueQuantity']['value'] == 90
    med = observation_to_fhir(sample('medication_taken'))
    assert med['valueBoolean'] is True
    assert 'med-001' in med['note'][0]['text']


def test_naive_timestamp_rejected():
    with pytest.raises(ValueError, match='timezone'):
        observation_to_fhir(sample('heart_rate', effective_at=datetime(2026, 11, 20)))
