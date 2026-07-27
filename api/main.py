from fastapi import FastAPI
from fastapi.responses import JSONResponse

from api.brain import BrainUnavailable, active_version
from api.config import settings

app = FastAPI(title="Kira Onboarding Screener", version="0.1.0")


@app.get("/health")
def health() -> JSONResponse:
    """Readiness probe: 503 when the Brain is unreadable; never calls the API."""
    try:
        version = active_version(settings.brain_dir)
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
            "brain_version": version,
            "model": settings.anthropic_model,
            "commit": settings.git_commit,
        },
    )
