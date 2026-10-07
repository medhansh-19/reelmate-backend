from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException

from app import __version__
from app.api.routes.analyses import router as analyses_router
from app.api.routes.health import router as health_router
from app.api.routes.music_preferences import router as music_preferences_router
from app.config import Settings, get_settings
from app.db import Database
from app.errors import (
    AppError,
    app_error_handler,
    http_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.security import SupabaseJWTVerifier
from app.storage import R2Storage, R2StorageSettings

_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}")


def _request_id(value: str | None) -> str:
    if value and _REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return str(uuid4())


def _lifespan(
    settings: Settings,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.settings = settings
        application.state.database = None
        application.state.jwt_verifier = None
        application.state.storage = None

        if settings.database_url is not None:
            application.state.database = Database(settings.database_url.get_secret_value())
        if settings.supabase_url:
            application.state.jwt_verifier = SupabaseJWTVerifier(
                supabase_url=settings.supabase_url,
                audience=settings.supabase_jwt_audience,
                issuer=settings.supabase_jwt_issuer,
            )
        if settings.r2_configured:
            assert settings.r2_account_id is not None
            assert settings.r2_access_key_id is not None
            assert settings.r2_secret_access_key is not None
            assert settings.r2_bucket_name is not None
            application.state.storage = R2Storage(
                R2StorageSettings(
                    account_id=settings.r2_account_id,
                    access_key_id=settings.r2_access_key_id.get_secret_value(),
                    secret_access_key=settings.r2_secret_access_key.get_secret_value(),
                    bucket_name=settings.r2_bucket_name,
                    key_prefix=settings.r2_key_prefix,
                    upload_expiry_seconds=settings.r2_upload_expiry_seconds,
                    max_video_bytes=settings.max_video_bytes,
                    max_image_bytes=settings.max_image_bytes,
                )
            )
        try:
            yield
        finally:
            jwt_verifier = application.state.jwt_verifier
            if isinstance(jwt_verifier, SupabaseJWTVerifier):
                await jwt_verifier.aclose()
            database = application.state.database
            if isinstance(database, Database):
                await database.dispose()

    return lifespan


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    application = FastAPI(
        title=settings.app_name,
        description="Private, asynchronous AI reel coaching backend",
        version=__version__,
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url=None,
        lifespan=_lifespan(settings),
    )
    application.state.settings = settings
    application.state.database = None
    application.state.jwt_verifier = None
    application.state.storage = None
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    )
    application.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    application.add_exception_handler(HTTPException, http_error_handler)  # type: ignore[arg-type]
    application.add_exception_handler(
        RequestValidationError,
        validation_error_handler,  # type: ignore[arg-type]
    )
    application.add_exception_handler(Exception, unhandled_error_handler)

    @application.middleware("http")
    async def request_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = _request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    application.include_router(health_router, prefix=settings.api_prefix)
    application.include_router(analyses_router, prefix=settings.api_prefix)
    application.include_router(music_preferences_router, prefix=settings.api_prefix)
    return application


app = create_app()
