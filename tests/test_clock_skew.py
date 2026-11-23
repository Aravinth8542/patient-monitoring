from datetime import datetime, timedelta, timezone
import pytest
from app.services.clock_skew import estimate_device_offset, resolve_effective_at, is_event_time_eligible

UTC = timezone.utc

def test_corrects_every_reading_using_batch_offset():
    """
    The device says it sent the batch at 10:00, while the server received it at 10:30,
    yielding a +30-minute offset. A reading stamped 09:55 must be corrected to 10:25 and
    flagged, preserving its five-minute position relative to the device's send time.
    """
    received = datetime(2026, 11, 20, 10, 30, tzinfo=UTC)
    sent = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    offset = estimate_device_offset(received, sent)
    corrected, flagged = resolve_effective_at(datetime(2026, 11, 20, 9, 55, tzinfo=UTC), received, offset)
    assert offset == timedelta(minutes=30)
    assert corrected == datetime(2026, 11, 20, 10, 25, tzinfo=UTC)
    assert flagged is True

def test_72_hour_old_reading_remains_old():
    """
    An observation received at 10:00 with an effective timestamp exactly 72 hours earlier
    and zero clock offset is legitimate late data. The resolver must preserve that
    historical timestamp and avoid marking it as clock-corrected.
    """
    received = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    corrected, flagged = resolve_effective_at(received - timedelta(hours=72), received, timedelta(0))
    assert corrected == received - timedelta(hours=72)
    assert flagged is False

def test_more_than_30_days_old_rejected():
    """
    A reading timestamped 31 days before receipt exceeds the allowed historical age. The
    clock resolver must raise a ValueError containing the 30-day rejection reason rather
    than silently ingesting stale data.
    """
    received = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="30_days"):
        resolve_effective_at(received - timedelta(days=31), received, timedelta(0))

def test_future_reading_rejected():
    """
    A measurement dated six minutes after the server receipt time exceeds the five-minute
    future tolerance. It must be rejected with a future-time error instead of being treated
    as already available.
    """
    received = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="future"):
        resolve_effective_at(received + timedelta(minutes=6), received, timedelta(0))


def test_future_readings_preserve_spacing_and_become_eligible_over_time():
    """
    Measurements at 10:01 and 10:02 arrive at 10:00. Both are flagged as future-skewed but
    retain their one-minute separation. Neither is eligible at 10:00; only the first is
    eligible at 10:01; both are eligible at 10:02.
    """
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
    """
    A measurement exactly five minutes ahead is accepted with its original timestamp and a
    future-skew flag. Advancing it by one additional second crosses the boundary and must
    raise a future-time error.
    """
    received = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    corrected, flagged = resolve_effective_at(received + timedelta(minutes=5), received, timedelta(0))
    assert corrected == received + timedelta(minutes=5)
    assert flagged
    with pytest.raises(ValueError, match="future"):
        resolve_effective_at(received + timedelta(minutes=5, seconds=1), received, timedelta(0))
