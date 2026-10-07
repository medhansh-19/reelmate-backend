import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_do_not_require_external_credentials() -> None:
    settings = Settings(_env_file=None, app_env="test")

    assert not settings.database_configured
    assert not settings.r2_configured


def test_cors_origins_accept_comma_separated_value() -> None:
    settings = Settings(
        _env_file=None, app_env="test", cors_origins="https://a.test,https://b.test"
    )

    assert settings.cors_origins == ["https://a.test", "https://b.test"]


def test_matching_supabase_auth_and_database_projects_are_accepted() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        supabase_url="https://reelmate-ref.supabase.co",
        database_url=(
            "postgresql://postgres.reelmate-ref:password@"
            "aws-0-region.pooler.supabase.com:5432/postgres"
        ),
    )

    assert settings.database_configured


def test_cross_project_supabase_connections_are_rejected() -> None:
    with pytest.raises(ValidationError, match="belong to different projects"):
        Settings(
            _env_file=None,
            app_env="production",
            supabase_url="https://reelmate-ref.supabase.co",
            database_url="postgresql://postgres@db.some-other-ref.supabase.co/postgres",
        )


def test_production_database_must_be_supabase_postgres() -> None:
    with pytest.raises(ValidationError, match="must belong to Supabase Postgres"):
        Settings(
            _env_file=None,
            app_env="production",
            database_url="postgresql://postgres:password@database.example.test/postgres",
        )


def test_production_auth_url_must_be_a_supabase_project() -> None:
    with pytest.raises(ValidationError, match="must belong to a Supabase project"):
        Settings(
            _env_file=None,
            app_env="production",
            supabase_url="https://auth.example.test",
        )


def test_production_rejects_local_auth_and_database() -> None:
    with pytest.raises(ValidationError, match="must belong to a Supabase project"):
        Settings(
            _env_file=None,
            app_env="production",
            supabase_url="http://localhost:54321",
        )

    with pytest.raises(ValidationError, match="must belong to Supabase Postgres"):
        Settings(
            _env_file=None,
            app_env="production",
            database_url="postgresql://postgres:password@localhost/postgres",
        )


def test_media_limits_are_bounded() -> None:
    settings = Settings(_env_file=None, app_env="test")
    assert settings.max_video_bytes == 100_000_000
    assert settings.max_image_bytes == 15_000_000

    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="test", max_image_bytes=15_000_001)


def test_cors_wildcard_is_rejected_for_credentialed_requests() -> None:
    with pytest.raises(ValidationError, match="explicit trusted origins"):
        Settings(_env_file=None, app_env="test", cors_origins=["*"])


def test_worker_attempt_limit_is_bounded() -> None:
    assert Settings(_env_file=None, app_env="test", worker_max_attempts=4).worker_max_attempts == 4

    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="test", worker_max_attempts=11)
