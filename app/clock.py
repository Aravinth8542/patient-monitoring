"""Single injectable, timezone-aware clock for HTTP handlers and background jobs."""
from datetime import datetime, timezone
from fastapi import Header, HTTPException
from app.config import settings


def utc_now() -> datetime:
    """Production clock. Patch this boundary in unit tests if needed."""
    return datetime.now(timezone.utc)


def parse_test_now(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="invalid_x_test_now") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HTTPException(status_code=422, detail="x_test_now_requires_timezone")
    return parsed.astimezone(timezone.utc)


def get_current_time(x_test_now: str | None = Header(default=None, alias="X-Test-Now")) -> datetime:
    """Use X-Test-Now only in TEST_MODE; otherwise ignore untrusted clock headers."""
    if settings.test_mode and x_test_now is not None:
        return parse_test_now(x_test_now)
    return utc_now()


def is_eligible(effective_at: datetime, evaluation_now: datetime) -> bool:
    """For periodic alert/rollup queries, compare event time to injected clock."""
    return effective_at.astimezone(timezone.utc) <= evaluation_now.astimezone(timezone.utc)
