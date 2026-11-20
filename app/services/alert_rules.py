"""Pure alert-rule detection over effective (not received) observation times.

Input is chronological, normalized measurements for one consenting patient.
No DB writes or network calls occur in this module.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

@dataclass(frozen=True)
class Reading:
    at: datetime
    kind: str
    value: Decimal

@dataclass(frozen=True)
class Episode:
    rule: str
    severity: str
    start: datetime


def detect_episodes(readings: list[Reading]) -> list[Episode]:
    readings = sorted(readings, key=lambda r: r.at)
    result: list[Episode] = []
    # Sustained low SpO2: 3+ consecutive low readings spanning >=10 minutes.
    # A normal reading ends the run; gaps >10m also end it (no evidence of continuity).
    low: list[Reading] = []
    for r in (x for x in readings if x.kind == 'spo2'):
        if r.value >= Decimal('92') or (low and r.at - low[-1].at > timedelta(minutes=10)):
            low = []
        if r.value < Decimal('92'):
            low.append(r)
            if len(low) >= 3 and r.at - low[0].at >= timedelta(minutes=10):
                if not result or result[-1].rule != 'low_spo2' or result[-1].start != low[0].at:
                    # Emit only once for this continuous low run.
                    if not any(e.rule == 'low_spo2' and e.start == low[0].at for e in result):
                        result.append(Episode('low_spo2','high',low[0].at))
    # HR rise: first reading within 15m that is >=30 bpm lower than current.
    # Avoid emitting a new episode on each subsequent elevated sample.
    hr = [r for r in readings if r.kind == 'heart_rate']
    active = False
    for i, current in enumerate(hr):
        previous = [r for r in hr[:i] if timedelta(0) < current.at-r.at <= timedelta(minutes=15)]
        baseline = min(previous, key=lambda r: r.value) if previous else None
        triggered = baseline is not None and current.value - baseline.value >= Decimal('30')
        if triggered and not active:
            result.append(Episode('hr_rise','medium',baseline.at))
        active = triggered
    return sorted(result,key=lambda e:(e.start,e.rule))
