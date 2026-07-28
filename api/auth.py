"""Bearer auth for the token-guarded surfaces. Screening an applicant and swapping the policy are different privileges."""

import hashlib
import secrets

from fastapi import Header, HTTPException

from api.config import settings


def require_admin(authorization: str | None = Header(default=None)) -> str:
    """The mutating Brain endpoints."""
    return _guard(settings.admin_api_token, "ADMIN_API_TOKEN", authorization)


def require_screener(authorization: str | None = Header(default=None)) -> str:
    """`POST /screen`. A caller that can screen must not thereby be able to change the policy it screens under."""
    return _guard(settings.screen_api_token, "SCREEN_API_TOKEN", authorization)


def _guard(token: str, label: str, authorization: str | None) -> str:
    """An unset token closes the endpoint rather than opening it; the return value identifies the caller in a log."""
    if not token:
        raise HTTPException(status_code=503, detail=f"{label} is not configured")

    expected = f"Bearer {token}"
    if authorization is None or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")

    return hashlib.sha256(expected.encode()).hexdigest()[:8]
