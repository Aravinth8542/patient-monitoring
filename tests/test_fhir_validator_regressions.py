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
    """
    Convert SpO2 to FHIR and require LOINC 2708-6 in the observation code. This guards
    against a regression in the standard code expected by the selected FHIR profile.
    """
    assert observation_to_fhir(sample('spo2'))['code']['coding'][0]['code'] == '2708-6'


def test_spo2_search_supports_both_loinc_codes():
    """
    The FHIR search lookup must treat LOINC 2708-6 and 59408-5 as SpO2. Both standard codes
    should retrieve the same internal observation type instead of excluding otherwise valid
    oxygen saturation data.
    """
    assert CODE_TO_KIND['2708-6'] == CODE_TO_KIND['59408-5'] == 'spo2'


@pytest.mark.parametrize('kind', ['symptom_score', 'medication_taken'])
def test_unspecified_local_concepts_do_not_use_example_code_system(kind):
    """
    For each parameterized local event type, the FHIR code must contain human-readable text
    but no invented coding entry. This avoids publishing a placeholder terminology system as
    if it were a valid standardized code.
    """
    code = observation_to_fhir(sample(kind))['code']
    assert code.get('text')
    assert 'coding' not in code


def test_symptom_score_uses_dimensionless_ucum():
    """
    A symptom score is a dimensionless quantity, not a temperature or percentage. Its FHIR
    valueQuantity must use UCUM code '1' and display unit 'score'.
    """
    value = observation_to_fhir(sample('symptom_score'))['valueQuantity']
    assert value['code'] == '1'
    assert value['unit'] == 'score'


def test_exported_searchset_has_entry_full_urls_and_search_modes(tmp_path, monkeypatch):
    """
    Run the actual FHIR sample-export script in a temporary directory and read
    searchset.json. The Bundle must have a self link and six entries; each entry needs a
    urn:uuid fullUrl matching its resource ID and search.mode 'match', as expected for a
    FHIR search result.
    """
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
