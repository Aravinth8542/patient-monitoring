"""FHIR R4 Observation representations for stored canonical measurements.

Part 1 intentionally implements resource conversion only. Search filters and
cursor pagination are introduced in subsequent parts.
"""
from datetime import timezone
from decimal import Decimal

LOINC = 'http://loinc.org'
UCUM = 'http://unitsofmeasure.org'

CODES = {
    'heart_rate': ('8867-4', 'Heart rate'),
    'spo2': ('2708-6', 'Oxygen saturation in Arterial blood'),
    'blood_pressure': ('85354-9', 'Blood pressure panel with all children optional'),
    'body_temp': ('8310-5', 'Body temperature'),
}
UNITS = {
    'heart_rate': ('/min', 'beats/minute'),
    'spo2': ('%', '%'),
    'blood_pressure': ('mm[Hg]', 'mmHg'),
    'body_temp': ('Cel', '°C'),
    'symptom_score': ('1', 'score'),
}


def _code(code, display, system=LOINC):
    return {'coding': [{'system': system, 'code': code, 'display': display}]}


def _quantity(value: Decimal, kind: str):
    code, unit = UNITS[kind]
    return {'value': float(value), 'unit': unit, 'system': UCUM, 'code': code}


def observation_to_fhir(observation):
    """Convert a persisted Observation ORM instance into one FHIR resource."""
    kind = observation.type
    if kind in CODES:
        code, display = CODES[kind]
        concept = _code(code, display)
    elif kind == 'symptom_score':
        # No universal LOINC exists for an unspecified symptom score.
        concept = {'text': 'Patient-reported symptom score (local concept: symptom-score)'}
    elif kind == 'medication_taken':
        # Event is represented as an Observation for this limited read-only subset.
        concept = {'text': 'Patient-reported medication taken (local concept: medication-taken)'}
    else:
        raise ValueError('unsupported_observation_type')
    effective = observation.effective_at
    if effective.tzinfo is None:
        raise ValueError('effective_at_requires_timezone')
    result = {
        'resourceType': 'Observation',
        'id': str(observation.id),
        'status': 'final',
        'code': concept,
        'subject': {'reference': f'Patient/{observation.patient_id}'},
        'effectiveDateTime': effective.isoformat(),
    }
    if kind in CODES:
        result['category'] = [{
            'coding': [{
                'system': 'http://terminology.hl7.org/CodeSystem/observation-category',
                'code': 'vital-signs',
                'display': 'Vital Signs',
            }]
        }]
    if kind == 'blood_pressure':
        result['component'] = [
            {'code': _code('8480-6', 'Systolic blood pressure'), 'valueQuantity': _quantity(observation.systolic, kind)},
            {'code': _code('8462-4', 'Diastolic blood pressure'), 'valueQuantity': _quantity(observation.diastolic, kind)},
        ]
    elif kind == 'medication_taken':
        result['valueBoolean'] = True
        if observation.medication_ref:
            result['note'] = [{'text': f'Medication reference: {observation.medication_ref}'}]
    else:
        result['valueQuantity'] = _quantity(observation.value, kind)
    return result
