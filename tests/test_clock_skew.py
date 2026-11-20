from datetime import datetime, timedelta, timezone
import pytest
from app.services.clock_skew import estimate_device_offset, resolve_effective_at, is_event_time_eligible

UTC = timezone.utc

def test_corrects_every_reading_using_batch_offset():
    received = datetime(2026, 11, 20, 10, 30, tzinfo=UTC)
    sent = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    offset = estimate_device_offset(received, sent)
    corrected, flagged = resolve_effective_at(datetime(2026, 11, 20, 9, 55, tzinfo=UTC), received, offset)
    assert offset == timedelta(minutes=30)
    assert corrected == datetime(2026, 11, 20, 10, 25, tzinfo=UTC)
    assert flagged is True

def test_72_hour_old_reading_remains_old():
    received = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    corrected, flagged = resolve_effective_at(received - timedelta(hours=72), received, timedelta(0))
    assert corrected == received - timedelta(hours=72)
    assert flagged is False

def test_more_than_30_days_old_rejected():
    received = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="30_days"):
        resolve_effective_at(received - timedelta(days=31), received, timedelta(0))

def test_future_reading_rejected():
    received = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="future"):
        resolve_effective_at(received + timedelta(minutes=6), received, timedelta(0))


def test_future_readings_preserve_spacing_and_become_eligible_over_time():
    received = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    first, first_flag = resolve_effective_at(received + timedelta(minutes=1), received, timedelta(0))
    second, second_flag = resolve_effective_at(received + timedelta(minutes=2), received, timedelta(0))
    assert first_flag and second_flag
    assert second - first == timedelta(minutes=1)
    assert not is_event_time_eligible(first, received)
    assert not is_event_time_eligible(second, received)
    assert is_event_time_eligible(first, received + timedelta(minutes=1))
    assert not is_event_time_eligible(second, received + timedelta(minutes=1))
    assert is_event_time_eligible(second, received + timedelta(minutes=2))

def test_future_tolerance_boundary():
    received = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    corrected, flagged = resolve_effective_at(received + timedelta(minutes=5), received, timedelta(0))
    assert corrected == received + timedelta(minutes=5)
    assert flagged
    with pytest.raises(ValueError, match="future"):
        resolve_effective_at(received + timedelta(minutes=5, seconds=1), received, timedelta(0))
