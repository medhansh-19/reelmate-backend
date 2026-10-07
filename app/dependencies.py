"""FastAPI dependencies for project-scoped infrastructure and authentication."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Database
from app.errors import AppError
from app.security import CurrentUser, JWTVerificationError, SupabaseJWTVerifier
from app.storage import R2Storage

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield one transaction from the ReelMate-specific PostgreSQL pool."""

    database = getattr(request.app.state, "database", None)
    if not isinstance(database, Database):
        raise AppError(
            "DATABASE_UNAVAILABLE",
            "The analysis database is not configured",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            retryable=True,
        )
    async with database.session() as session:
        yield session


def get_storage(request: Request) -> R2Storage:
    """Return the private ReelMate R2 client configured during app startup."""

    storage = getattr(request.app.state, "storage", None)
    if not isinstance(storage, R2Storage):
        raise AppError(
            "STORAGE_UNAVAILABLE",
            "Private video storage is not configured",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            retryable=True,
        )
    return storage


async def get_authenticated_user(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_bearer_scheme),
    ],
) -> CurrentUser:
    """Verify a Supabase access token against this project's signing keys."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(
            "AUTH_REQUIRED",
            "A Supabase bearer access token is required",
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    verifier = getattr(request.app.state, "jwt_verifier", None)
    if not isinstance(verifier, SupabaseJWTVerifier):
        raise AppError(
            "AUTH_UNAVAILABLE",
            "Supabase authentication is not configured",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            retryable=True,
        )
    try:
        return await verifier.verify(credentials.credentials)
    except JWTVerificationError as exc:
        raise AppError(
            "INVALID_ACCESS_TOKEN",
            "The Supabase access token is invalid or expired",
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from exc


SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[CurrentUser, Depends(get_authenticated_user)]
StorageDep = Annotated[R2Storage, Depends(get_storage)]
