"""The screening surface: a packet in, a case file and the run's trace out."""

import logging
from functools import lru_cache
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response

from agent.brain import BrainUnavailable, load_brain
from agent.extraction import ExtractionFailed
from agent.guardrails import GuardrailViolated
from agent.llm import AnthropicClient, StructuredClient
from agent.orchestrate import screen
from agent.schemas import Applicant
from agent.screening import WatchlistUnavailable, watchlist_digest
from agent.trace import emit
from api.auth import require_screener
from api.config import settings

log = logging.getLogger(__name__)

router = APIRouter(tags=["screen"])


@lru_cache(maxsize=1)
def model_client() -> StructuredClient:
    """Built once and lazily: constructing it never calls the API, so an unset key still leaves /health green."""
    return AnthropicClient(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
        timeout=float(settings.request_timeout_seconds),
    )


@router.post("/screen")
def screen_applicant(packet: Applicant, caller: str = Depends(require_screener)) -> Response:
    """Screen one applicant. The packet is the request body; the delivered bundle is test data, not a database."""
    try:
        brain = load_brain(settings.brain_dir)
        watchlist_digest()
    except (BrainUnavailable, WatchlistUnavailable) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    run_id = uuid4().hex[:12]
    try:
        case_file, trace = screen(
            packet,
            brain,
            model_client(),
            run_id=run_id,
            model=settings.anthropic_model,
            max_steps=settings.max_steps_per_applicant,
            timeout_seconds=float(settings.request_timeout_seconds),
        )
    except ExtractionFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except GuardrailViolated as exc:
        log.error("guardrail violated on run %s: %s", run_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    line = emit(trace, settings.traces_dir)
    log.info(
        "screened %s run=%s decision=%s rules=%s by token %s",
        packet.applicant_id,
        run_id,
        case_file.decision,
        trace.evaluate[-1].fired_rules,
        caller,
    )

    # Composed from the emitted line rather than re-serialised, so the response
    # carries the same bytes as the log rather than an equivalent object.
    body = f'{{"case_file":{case_file.model_dump_json()},"trace":{line}}}'
    return Response(content=body, media_type="application/json")
