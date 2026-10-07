from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Project-specific configuration loaded from environment variables.

    Secret values are never given defaults and are excluded from repr output.
    Local development may use this repository's ignored ``.env`` file; hosted
    environments should inject variables directly.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "ReelMate API"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    api_prefix: str = "/v1"
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    database_url: SecretStr | None = Field(default=None, repr=False)
    supabase_url: str | None = None
    supabase_jwt_audience: str = "authenticated"
    supabase_jwt_issuer: str | None = None

    r2_account_id: str | None = None
    r2_access_key_id: SecretStr | None = Field(default=None, repr=False)
    r2_secret_access_key: SecretStr | None = Field(default=None, repr=False)
    r2_bucket_name: str | None = None
    r2_key_prefix: str = "reelmate/analyses"
    r2_upload_expiry_seconds: int = Field(default=900, ge=60, le=900)

    worker_id: str = "worker-local"
    worker_poll_seconds: float = Field(default=2.0, ge=0.2, le=30.0)
    worker_lease_seconds: int = Field(default=600, ge=60, le=3600)
    worker_job_timeout_seconds: int = Field(default=600, ge=60, le=1800)
    worker_max_attempts: int = Field(default=3, ge=1, le=10)

    max_video_bytes: int = Field(default=100_000_000, gt=0, le=100_000_000)
    max_video_duration_seconds: float = Field(default=90.0, gt=0, le=90.0)
    max_image_bytes: int = Field(default=15_000_000, gt=0, le=15_000_000)
    source_retention_hours: int = Field(default=24, ge=1, le=168)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def keep_supabase_connections_project_scoped(self) -> Self:
        """Reject discoverable cross-project or non-Supabase production DB URLs."""

        if "*" in self.cors_origins:
            raise ValueError("CORS_ORIGINS must list explicit trusted origins")
        if self.supabase_url:
            auth_host = (urlparse(self.supabase_url).hostname or "").lower()
            if self.app_env in {"staging", "production"} and not auth_host.endswith(".supabase.co"):
                raise ValueError("Hosted SUPABASE_URL must belong to a Supabase project")
        if self.database_url is None:
            return self

        database_value = self.database_url.get_secret_value().strip()
        database_url = urlparse(database_value)
        database_host = (database_url.hostname or "").lower()
        is_supabase = database_host.endswith((".supabase.co", ".supabase.com"))
        if self.app_env in {"staging", "production"} and not is_supabase:
            raise ValueError("Hosted DATABASE_URL must belong to Supabase Postgres")

        auth_ref = _supabase_auth_project_ref(self.supabase_url)
        database_ref = _supabase_database_project_ref(
            hostname=database_host,
            username=database_url.username,
        )
        if auth_ref and database_ref and auth_ref != database_ref:
            raise ValueError("SUPABASE_URL and DATABASE_URL belong to different projects")
        return self

    @property
    def database_configured(self) -> bool:
        return self.database_url is not None

    @property
    def supabase_auth_configured(self) -> bool:
        return bool(self.supabase_url)

    @property
    def r2_configured(self) -> bool:
        return all(
            (
                self.r2_account_id,
                self.r2_access_key_id,
                self.r2_secret_access_key,
                self.r2_bucket_name,
            )
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _supabase_auth_project_ref(supabase_url: str | None) -> str | None:
    if not supabase_url:
        return None
    hostname = (urlparse(supabase_url).hostname or "").lower()
    if not hostname.endswith(".supabase.co"):
        return None
    labels = hostname.split(".")
    return labels[0] if len(labels) >= 3 else None


def _supabase_database_project_ref(
    *,
    hostname: str,
    username: str | None,
) -> str | None:
    if hostname.startswith("db.") and hostname.endswith(".supabase.co"):
        labels = hostname.split(".")
        return labels[1] if len(labels) >= 4 else None
    if hostname.endswith(".pooler.supabase.com") and username:
        prefix, separator, project_ref = username.partition(".")
        if prefix == "postgres" and separator and project_ref:
            return project_ref.lower()
    return None
