"""FHIR R4 shape smoke tests; not a replacement for the official validator."""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.fhir_observation import observation_to_fhir


def _sample(kind):
    return SimpleNamespace(
        id=uuid4(), patient_id=uuid4(), type=kind,
        effective_at=datetime(2026, 11, 20, 10, tzinfo=timezone.utc),
        value=Decimal('94'), systolic=Decimal('120'),
        diastolic=Decimal('80'), medication_ref='synthetic-med',
    )


@pytest.mark.parametrize('kind', ['heart_rate', 'spo2', 'blood_pressure', 'body_temp'])
def test_vital_signs_category(kind):
    resource = observation_to_fhir(_sample(kind))
    assert resource['category'][0]['coding'][0] == {
        'system': 'http://terminology.hl7.org/CodeSystem/observation-category',
        'code': 'vital-signs', 'display': 'Vital Signs',
    }
    assert resource['subject']['reference'].startswith('Patient/')
    assert resource['effectiveDateTime'].endswith('+00:00')


def test_non_vital_events_not_mislabeled_as_vital_signs():
    for kind in ('symptom_score', 'medication_taken'):
        resource = observation_to_fhir(_sample(kind))
        assert not any(
            coding.get('code') == 'vital-signs'
            for category in resource.get('category', [])
            for coding in category.get('coding', [])
        )


def test_bp_has_two_loinc_components_and_no_top_level_quantity():
    resource = observation_to_fhir(_sample('blood_pressure'))
    assert 'valueQuantity' not in resource
    assert {x['code']['coding'][0]['code'] for x in resource['component']} == {'8480-6', '8462-4'}
    assert all(x['valueQuantity']['system'] == 'http://unitsofmeasure.org' for x in resource['component'])
