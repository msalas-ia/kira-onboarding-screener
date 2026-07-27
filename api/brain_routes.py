"""Admin surface for the Company Brain: inspect, list, and swap the active version."""

import hashlib
import logging
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from agent.brain import (
    BrainInvalid,
    BrainReadOnly,
    BrainUnavailable,
    activate,
    list_versions,
    load_brain,
    read_pointer,
)
from api.config import settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/brain", tags=["brain"])


class ActivateRequest(BaseModel):
    """The version to make live."""

    version: str


def require_admin(authorization: str | None = Header(default=None)) -> str:
    """Bearer auth for the one mutating endpoint; an unset token closes it rather than opening it."""
    if not settings.admin_api_token:
        raise HTTPException(status_code=503, detail="ADMIN_API_TOKEN is not configured")

    expected = f"Bearer {settings.admin_api_token}"
    if authorization is None or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")

    return hashlib.sha256(expected.encode()).hexdigest()[:8]


@router.get("")
def describe_brain() -> dict:
    """What policy is in force, and what a rollback would return to."""
    try:
        pointer = read_pointer(settings.brain_dir)
        brain = load_brain(settings.brain_dir)
    except BrainUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "active_version": brain.version,
        "previous_version": pointer.previous_version,
        "brain_hash": brain.brain_hash,
        "rules": len(brain.rules),
        "settings": brain.settings.model_dump(mode="json"),
    }


@router.get("/versions")
def get_versions() -> dict:
    """Every version on the volume, valid or not."""
    try:
        versions = list_versions(settings.brain_dir)
    except BrainUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"versions": versions}


@router.post("/activate")
def activate_version(request: ActivateRequest, caller: str = Depends(require_admin)) -> dict:
    """Hot-swap the active policy; rollback is this same call with the reported previous version."""
    try:
        previous, brain = activate(settings.brain_dir, request.version)
    except BrainInvalid as exc:
        raise HTTPException(status_code=422, detail={"version": exc.version, "errors": exc.errors}) from exc
    except BrainReadOnly as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BrainUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    log.info("brain activated: %s -> %s (%s) by token %s", previous, brain.version, brain.brain_hash, caller)
    return {"previous": previous, "active": brain.version, "brain_hash": brain.brain_hash}
