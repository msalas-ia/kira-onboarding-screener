from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration; staging and production differ only in these values."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: str = "staging"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"

    brain_dir: Path = Path("company_brain")

    admin_api_token: str = ""
    screen_api_token: str = ""
    log_level: str = "INFO"

    # Where run traces are persisted; unset means the log is the only sink.
    traces_dir: Path | None = Path("traces")

    max_steps_per_applicant: int = 12
    request_timeout_seconds: int = 120

    port: int = 8000
    git_commit: str = "unknown"


settings = Settings()
