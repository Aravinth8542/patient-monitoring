from datetime import datetime, timedelta, timezone
from decimal import Decimal
from app.services.alert_rules import Reading, detect_episodes

T=datetime(2026,11,20,10,tzinfo=timezone.utc)
def r(minutes,kind,value):
    return Reading(T+timedelta(minutes=minutes),kind,Decimal(str(value)))

def test_sustained_low_spo2_requires_three_and_ten_minutes():
    """
    Two low readings (91% at minute 0 and 90% at minute 5) are insufficient. Adding 91% at
    minute 10 completes three consecutive low readings spanning ten minutes, producing
    exactly one high-severity low-SpO2 episode whose start is the first reading.
    """
    assert detect_episodes([r(0,'spo2',91),r(5,'spo2',90)]) == []
    assert detect_episodes([r(0,'spo2',91),r(5,'spo2',90),r(10,'spo2',91)]) == [
        __import__('app.services.alert_rules',fromlist=['Episode']).Episode('low_spo2','high',T)]

def test_normal_reading_breaks_low_episode():
    """
    The 95% SpO2 value at minute 5 interrupts the low sequence begun at minute 0. Although
    later readings at minutes 10 and 15 are 90%, they do not establish a new ten-minute
    three-reading run, so no alert episode should be detected.
    """
    assert detect_episodes([r(0,'spo2',91),r(5,'spo2',95),r(10,'spo2',90),r(15,'spo2',90)]) == []

def test_heart_rate_rise_within_window():
    """
    A heart rate increase from 70 to 100 bpm over ten minutes satisfies the 30-bpm rapid-
    rise threshold and produces a medium-severity episode. The same increase over sixteen
    minutes falls outside the permitted window and must not alert.
    """
    episodes=detect_episodes([r(0,'heart_rate',70),r(10,'heart_rate',100)])
    assert [(e.rule,e.severity) for e in episodes]==[('hr_rise','medium')]
    assert detect_episodes([r(0,'heart_rate',70),r(16,'heart_rate',100)]) == []

def test_unsorted_and_repeated_low_readings_do_not_duplicate_episode():
    """
    The readings are intentionally passed in order 15, 0, 5, 10 minutes, all at 90-91% SpO2.
    Sorting by effective time should reveal one sustained episode; the additional low
    reading at minute 15 must not start a duplicate episode.
    """
    episodes=detect_episodes([r(15,'spo2',90),r(0,'spo2',91),r(5,'spo2',90),r(10,'spo2',91)])
    assert len(episodes)==1
