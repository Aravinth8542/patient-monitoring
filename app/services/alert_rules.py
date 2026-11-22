"""Evaluate the three supported alert rule types using tenant configuration."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

DEFAULT_RULES = [
    {"id": "low_spo2", "type": "sustained_threshold", "metric": "spo2", "op": "<", "value": 92, "min_duration_minutes": 10, "min_readings": 3, "max_gap_minutes": 10, "severity": "high"},
    {"id": "hr_rise", "type": "rate_of_change", "metric": "heart_rate", "op": ">=", "delta": 30, "window_minutes": 15, "severity": "medium"},
    {"id": "no_data", "type": "missing_data", "window_hours": 24, "severity": "low"},
]

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


def rules_for(config):
    """None uses defaults; an explicit [] disables rules for that tenant."""
    rules = DEFAULT_RULES if config is None else config
    if not isinstance(rules, list):
        raise ValueError('alert_rules must be a list')
    ids = set()
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get('id'), str) or not 0 < len(rule['id']) <= 40 or rule['id'] in ids:
            raise ValueError('invalid or repeated alert rule id')
        ids.add(rule['id'])
        if rule.get('severity') not in ('low', 'medium', 'high'):
            raise ValueError('invalid alert severity')
        kind = rule.get('type')
        if kind == 'sustained_threshold':
            if rule.get('metric') not in ('spo2', 'heart_rate', 'body_temp', 'symptom_score') or rule.get('op') not in ('<', '<=', '>', '>='):
                raise ValueError('invalid sustained rule')
            Decimal(str(rule['value']))
            if int(rule['min_duration_minutes']) <= 0 or int(rule['min_readings']) < 2 or int(rule.get('max_gap_minutes',rule['min_duration_minutes'])) <= 0:
                raise ValueError('invalid sustained duration')
        elif kind == 'rate_of_change':
            if rule.get('metric') not in ('spo2', 'heart_rate', 'body_temp', 'symptom_score') or rule.get('op') not in ('>=', '<='):
                raise ValueError('invalid rate rule')
            if Decimal(str(rule['delta'])) < 0 or int(rule['window_minutes']) <= 0:
                raise ValueError('invalid rate window')
        elif kind == 'missing_data':
            if int(rule['window_hours']) <= 0:
                raise ValueError('invalid silence window')
        else:
            raise ValueError('unsupported alert rule type')
    return rules


def _compare(value, op, threshold):
    return {'<': lambda: value < threshold, '<=': lambda: value <= threshold,
            '>': lambda: value > threshold, '>=': lambda: value >= threshold}[op]()


def detect_episodes(readings: list[Reading], rules=None) -> list[Episode]:
    readings = sorted(readings, key=lambda r: r.at)
    result = []
    for rule in rules_for(rules):
        kind = rule['type']
        if kind == 'missing_data':
            continue
        metric_rows = [r for r in readings if r.kind == rule['metric']]
        if kind == 'sustained_threshold':
            threshold = Decimal(str(rule['value']))
            duration = timedelta(minutes=int(rule['min_duration_minutes']))
            max_gap = timedelta(minutes=int(rule.get('max_gap_minutes', rule['min_duration_minutes'])))
            run = []
            for r in metric_rows:
                if not _compare(r.value, rule['op'], threshold) or (run and r.at-run[-1].at > max_gap):
                    run = []
                if _compare(r.value, rule['op'], threshold):
                    run.append(r)
                    if len(run) >= int(rule['min_readings']) and r.at-run[0].at >= duration:
                        episode = Episode(rule['id'], rule['severity'], run[0].at)
                        if episode not in result:
                            result.append(episode)
        elif kind == 'rate_of_change':
            window = timedelta(minutes=int(rule['window_minutes']))
            delta = Decimal(str(rule['delta']))
            active = False
            for i, current in enumerate(metric_rows):
                previous = [r for r in metric_rows[:i] if timedelta(0) < current.at-r.at <= window]
                baseline = (min(previous, key=lambda r:r.value) if rule['op'] == '>=' else max(previous,key=lambda r:r.value)) if previous else None
                triggered = baseline is not None and _compare(current.value-baseline.value, rule['op'], delta if rule['op']=='>=' else -delta)
                if triggered and not active:
                    result.append(Episode(rule['id'], rule['severity'], baseline.at))
                active = triggered
    return sorted(result, key=lambda e:(e.start,e.rule))
