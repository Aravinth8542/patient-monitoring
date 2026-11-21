"""Export synthetic FHIR R4 Observations and searchset Bundle for validator CLI."""
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid5, NAMESPACE_URL

from app.services.fhir_observation import observation_to_fhir


def main():
    out = Path('fhir-validation-samples')
    out.mkdir(exist_ok=True)
    resources = []
    for kind in ('heart_rate', 'spo2', 'blood_pressure', 'body_temp', 'symptom_score', 'medication_taken'):
        obs = SimpleNamespace(
            id=uuid5(NAMESPACE_URL, 'observation-' + kind),
            patient_id=uuid5(NAMESPACE_URL, 'patient-demo'),
            type=kind,
            effective_at=datetime(2026, 11, 20, 10, tzinfo=timezone.utc),
            value=Decimal('94'), systolic=Decimal('120'), diastolic=Decimal('80'),
            medication_ref='synthetic-med',
        )
        resource = observation_to_fhir(obs)
        resources.append(resource)
        (out / f'{kind}.json').write_text(json.dumps(resource, indent=2), encoding='utf-8')
    bundle = {'resourceType': 'Bundle', 'type': 'searchset',
              'link': [{'relation': 'self', 'url': 'http://localhost/fhir/Observation?patient=synthetic'}],
              'entry': [{'fullUrl': 'urn:uuid:' + r['id'], 'resource': r,
                         'search': {'mode': 'match'}} for r in resources]}
    (out / 'searchset.json').write_text(json.dumps(bundle, indent=2), encoding='utf-8')
    print(f'Exported {len(resources)} observations and one Bundle to {out}')


if __name__ == '__main__':
    main()
