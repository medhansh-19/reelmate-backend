from fastapi import APIRouter, Request, Response, status

from app.config import Settings
from app.schemas import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse)
async def readiness(
    request: Request,
    response: Response,
) -> HealthResponse:
    settings = request.app.state.settings
    if not isinstance(settings, Settings):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="not_ready", checks={})
    checks = {
        "database": settings.database_configured,
        "supabase_auth": settings.supabase_auth_configured,
        "r2": settings.r2_configured,
    }
    ready = all(checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="ok" if ready else "not_ready", checks=checks)
