"""Pure FHIR search helper tests; no database required."""
from datetime import timezone, datetime
from fastapi import HTTPException
import pytest

from app.routers.fhir import _date_filters, _encode_cursor, _decode_cursor, CODE_TO_KIND


def test_date_filter_parsing():
    result = _date_filters(["ge2026-11-19T10:00:00+05:30", "lt2026-11-20T00:00:00Z"])
    assert result[0] == ("ge", datetime(2026, 11, 19, 4, 30, tzinfo=timezone.utc))
    assert result[1][0] == "lt"


@pytest.mark.parametrize("raw", ["2026-11-19T10:00:00Z", "eq2026-11-19T10:00:00Z",
                                 "ge2026-11-19", "ltbad"])
def test_invalid_date_filters(raw):
    with pytest.raises(HTTPException) as exc:
        _date_filters([raw])
    assert exc.value.status_code == 422


def test_cursor_roundtrip():
    payload = {"v": 1, "q": {"patient": "test"}, "snapshot": "2026-11-20T10:00:00+00:00",
               "last_time": "2026-11-19T10:00:00+00:00", "last_id": "123"}
    assert _decode_cursor(_encode_cursor(payload)) == payload


@pytest.mark.parametrize("value", ["???", _encode_cursor({"v": 2}), "x" * 2049])
def test_invalid_cursor(value):
    with pytest.raises(HTTPException) as exc:
        _decode_cursor(value)
    assert exc.value.status_code == 422


def test_loinc_search_codes():
    assert CODE_TO_KIND["8867-4"] == "heart_rate"
    assert CODE_TO_KIND["85354-9"] == "blood_pressure"
