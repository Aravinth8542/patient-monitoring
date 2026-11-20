from datetime import datetime, timedelta, timezone
from decimal import Decimal
from app.services.alert_rules import Reading, detect_episodes

T=datetime(2026,11,20,10,tzinfo=timezone.utc)
def r(minutes,kind,value):
    return Reading(T+timedelta(minutes=minutes),kind,Decimal(str(value)))

def test_sustained_low_spo2_requires_three_and_ten_minutes():
    assert detect_episodes([r(0,'spo2',91),r(5,'spo2',90)]) == []
    assert detect_episodes([r(0,'spo2',91),r(5,'spo2',90),r(10,'spo2',91)]) == [
        __import__('app.services.alert_rules',fromlist=['Episode']).Episode('low_spo2','high',T)]

def test_normal_reading_breaks_low_episode():
    assert detect_episodes([r(0,'spo2',91),r(5,'spo2',95),r(10,'spo2',90),r(15,'spo2',90)]) == []

def test_heart_rate_rise_within_window():
    episodes=detect_episodes([r(0,'heart_rate',70),r(10,'heart_rate',100)])
    assert [(e.rule,e.severity) for e in episodes]==[('hr_rise','medium')]
    assert detect_episodes([r(0,'heart_rate',70),r(16,'heart_rate',100)]) == []

def test_unsorted_and_repeated_low_readings_do_not_duplicate_episode():
    episodes=detect_episodes([r(15,'spo2',90),r(0,'spo2',91),r(5,'spo2',90),r(10,'spo2',91)])
    assert len(episodes)==1
