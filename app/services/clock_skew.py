"""Batch-level clock offset estimation and observation event-time policy.

Assumption: sent_at_device is stamped immediately before upload, with small
network delay. The estimate includes network delay and is not a measured RTT.
"""
from datetime import datetime, timedelta, timezone

FUTURE_TOLERANCE = timedelta(minutes=5)
MAX_AGE = timedelta(days=30)
LATE_THRESHOLD = timedelta(hours=72)
SKEW_FLAG_THRESHOLD = timedelta(minutes=5)


def estimate_device_offset(received_at: datetime, sent_at_device: datetime) -> timedelta:
    return received_at.astimezone(timezone.utc) - sent_at_device.astimezone(timezone.utc)


def resolve_effective_at(
    original_effective_at: datetime, received_at: datetime, device_offset: timedelta
) -> tuple[datetime, bool]:
    """Return corrected UTC event time and whether the reading needs clock review.

    Clock correction is applied to all readings in a batch using one offset.
    Reject timestamps beyond the allowed corrected event-time window.
    """
    original = original_effective_at.astimezone(timezone.utc)
    received = received_at.astimezone(timezone.utc)
    corrected = original + device_offset
    age = received - corrected
    if age < -FUTURE_TOLERANCE:
        raise ValueError("corrected_effective_at_more_than_5_minutes_in_future")
    if age > MAX_AGE:
        raise ValueError("corrected_effective_at_more_than_30_days_old")
    flagged = abs(device_offset) > SKEW_FLAG_THRESHOLD or age > LATE_THRESHOLD or age < timedelta(0)
    return corrected, flagged


def is_event_time_eligible(effective_at: datetime, current_time: datetime) -> bool:
    """An event enters alert/rollup calculations only once its time has arrived."""
    return effective_at.astimezone(timezone.utc) <= current_time.astimezone(timezone.utc)
