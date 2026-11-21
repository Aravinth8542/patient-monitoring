"""Regression checks for issues identified by the HL7 FHIR R4 validator."""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.fhir_observation import observation_to_fhir
from app.routers.fhir import CODE_TO_KIND


def sample(kind):
    return SimpleNamespace(id=uuid4(), patient_id=uuid4(), type=kind,
        effective_at=datetime(2026, 11, 20, 10, tzinfo=timezone.utc),
        value=Decimal('92'), systolic=Decimal('120'), diastolic=Decimal('80'),
        medication_ref='synthetic-med')


def test_spo2_profile_required_code():
    assert observation_to_fhir(sample('spo2'))['code']['coding'][0]['code'] == '2708-6'


def test_spo2_search_supports_both_loinc_codes():
    assert CODE_TO_KIND['2708-6'] == CODE_TO_KIND['59408-5'] == 'spo2'


@pytest.mark.parametrize('kind', ['symptom_score', 'medication_taken'])
def test_unspecified_local_concepts_do_not_use_example_code_system(kind):
    code = observation_to_fhir(sample(kind))['code']
    assert code.get('text')
    assert 'coding' not in code


def test_symptom_score_uses_dimensionless_ucum():
    value = observation_to_fhir(sample('symptom_score'))['valueQuantity']
    assert value['code'] == '1'
    assert value['unit'] == 'score'


def test_exported_searchset_has_entry_full_urls_and_search_modes(tmp_path, monkeypatch):
    import json
    from scripts.export_fhir_validation_samples import main
    monkeypatch.chdir(tmp_path)
    main()
    bundle = json.loads((tmp_path / 'fhir-validation-samples/searchset.json').read_text())
    assert bundle['link'][0]['relation'] == 'self'
    assert len(bundle['entry']) == 6
    for entry in bundle['entry']:
        assert entry['fullUrl'] == 'urn:uuid:' + entry['resource']['id']
        assert entry['search']['mode'] == 'match'
