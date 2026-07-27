from fastapi import FastAPI
from fastapi.responses import JSONResponse

from agent.brain import BrainUnavailable, load_brain
from api.brain_routes import router as brain_router
from api.config import settings

app = FastAPI(title="Kira Onboarding Screener", version="0.1.0")
app.include_router(brain_router)


@app.get("/health")
def health() -> JSONResponse:
    """Readiness probe: 503 unless the Brain loads and validates; never calls the Anthropic API."""
    try:
        brain = load_brain(settings.brain_dir)
    except BrainUnavailable as exc:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "app_env": settings.app_env,
                "reason": str(exc),
            },
        )

    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "app_env": settings.app_env,
            "brain_version": brain.version,
            "brain_hash": brain.brain_hash,
            "model": settings.anthropic_model,
            "commit": settings.git_commit,
        },
    )
