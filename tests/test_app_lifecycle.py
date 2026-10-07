from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _unconfigured_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=None,
        supabase_url=None,
        r2_account_id=None,
        r2_access_key_id=None,
        r2_secret_access_key=None,
        r2_bucket_name=None,
    )


def test_unconfigured_app_starts_for_liveness_but_is_not_ready() -> None:
    settings = _unconfigured_settings()

    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/health/live").status_code == 200
        readiness = client.get("/v1/health/ready")

        assert readiness.status_code == 503
        assert readiness.json()["checks"] == {
            "database": False,
            "supabase_auth": False,
            "r2": False,
        }


def test_framework_http_errors_use_stable_envelope() -> None:
    settings = _unconfigured_settings()

    with TestClient(create_app(settings)) as client:
        response = client.get("/does-not-exist", headers={"X-Request-ID": "request-123"})

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Not Found",
            "retryable": False,
            "request_id": "request-123",
        }
    }


def test_analysis_routes_authenticate_before_checking_infrastructure() -> None:
    settings = _unconfigured_settings()

    with TestClient(create_app(settings)) as client:
        response = client.get("/v1/analyses")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    assert response.headers["www-authenticate"] == "Bearer"


def test_expo_web_origin_can_call_the_api() -> None:
    settings = _unconfigured_settings()

    with TestClient(create_app(settings)) as client:
        response = client.options(
            "/v1/health/live",
            headers={
                "Origin": "http://localhost:8081",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8081"
