from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


def test_liveness_does_not_require_external_services(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("APP_ENV", "test")
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get("/v1/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_reports_missing_connections(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("R2_ACCOUNT_ID", raising=False)
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get("/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
