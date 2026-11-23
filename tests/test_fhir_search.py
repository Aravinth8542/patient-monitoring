"""Pure FHIR search helper tests; no database required."""
from datetime import timezone, datetime
from fastapi import HTTPException
import pytest

from app.routers.fhir import _date_filters, _encode_cursor, _decode_cursor, CODE_TO_KIND


def test_date_filter_parsing():
    """
    Parse a FHIR search lower bound of ge2026-11-19T10:00:00+05:30 and an upper bound of
    lt2026-11-20T00:00:00Z. The first must normalize to 04:30 UTC while preserving the 'ge'
    comparison, and the second must retain its 'lt' operator.
    """
    result = _date_filters(["ge2026-11-19T10:00:00+05:30", "lt2026-11-20T00:00:00Z"])
    assert result[0] == ("ge", datetime(2026, 11, 19, 4, 30, tzinfo=timezone.utc))
    assert result[1][0] == "lt"


@pytest.mark.parametrize("raw", ["2026-11-19T10:00:00Z", "eq2026-11-19T10:00:00Z",
                                 "ge2026-11-19", "ltbad"])
def test_invalid_date_filters(raw):
    """
    Pass each parameterized invalid date search string to the FHIR parser. It must raise
    HTTP 422 rather than accept an ambiguous or unsupported filter.
    """
    with pytest.raises(HTTPException) as exc:
        _date_filters([raw])
    assert exc.value.status_code == 422


def test_cursor_roundtrip():
    """
    Encode a pagination cursor containing version, patient query, snapshot timestamp, last
    result time and last ID. Decoding must reproduce the same dictionary, so subsequent
    pages retain the original filter and snapshot.
    """
    payload = {"v": 1, "q": {"patient": "test"}, "snapshot": "2026-11-20T10:00:00+00:00",
               "last_time": "2026-11-19T10:00:00+00:00", "last_id": "123"}
    assert _decode_cursor(_encode_cursor(payload)) == payload


@pytest.mark.parametrize("value", ["???", _encode_cursor({"v": 2}), "x" * 2049])
def test_invalid_cursor(value):
    """
    Pass each parameterized malformed pagination cursor to the decoder. It must fail with
    HTTP 422 rather than silently reset pagination or trust corrupted state.
    """
    with pytest.raises(HTTPException) as exc:
        _decode_cursor(value)
    assert exc.value.status_code == 422


def test_loinc_search_codes():
    """
    Verify the search-code lookup maps LOINC 8867-4 to heart_rate and 85354-9 to
    blood_pressure. This is what allows FHIR clients to filter by standard clinical codes
    rather than internal metric names.
    """
    assert CODE_TO_KIND["8867-4"] == "heart_rate"
    assert CODE_TO_KIND["85354-9"] == "blood_pressure"
