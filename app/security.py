"""Supabase access-token verification against a project-specific JWKS.

No Supabase API key or shared JWT secret is required.  The verifier accepts the
project URL explicitly, fetches only that project's public signing keys, and
validates both ``iss`` and ``aud`` so a valid token from another Supabase project
cannot authenticate to ReelMate.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, Any, Protocol
from urllib.parse import urlparse
from uuid import UUID

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

ALLOWED_JWT_ALGORITHMS = frozenset({"RS256", "ES256"})


class JWTVerificationError(ValueError):
    """A stable, non-sensitive token failure for API translation."""

    def __init__(self, code: str, message: str = "Invalid access token") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CurrentUser:
    id: UUID
    role: str
    email: str | None
    claims: Mapping[str, Any]


class AsyncHTTPClient(Protocol):
    async def get(self, url: str, **kwargs: Any) -> httpx.Response: ...

    async def aclose(self) -> None: ...


def _normalize_project_url(supabase_url: str) -> str:
    value = supabase_url.strip().rstrip("/")
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("SUPABASE_URL must be an absolute project URL")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("SUPABASE_URL must use HTTPS outside local development")
    if parsed.path not in {"", "/"}:
        raise ValueError("SUPABASE_URL must not include an API path")
    return f"{parsed.scheme}://{parsed.netloc}"


class SupabaseJWTVerifier:
    """Asynchronously caches and verifies a Supabase project's signing keys."""

    def __init__(
        self,
        *,
        supabase_url: str,
        audience: str = "authenticated",
        issuer: str | None = None,
        jwks_cache_ttl_seconds: int = 600,
        unknown_kid_refresh_interval_seconds: int = 30,
        clock_skew_seconds: int = 30,
        http_client: AsyncHTTPClient | None = None,
    ) -> None:
        if not audience.strip():
            raise ValueError("JWT audience cannot be empty")
        if not 30 <= jwks_cache_ttl_seconds <= 86_400:
            raise ValueError("JWKS cache TTL must be between 30 and 86400 seconds")
        if not 5 <= unknown_kid_refresh_interval_seconds <= 300:
            raise ValueError("Unknown-key refresh interval must be between 5 and 300 seconds")
        if not 0 <= clock_skew_seconds <= 300:
            raise ValueError("JWT clock skew must be between 0 and 300 seconds")

        self.supabase_url = _normalize_project_url(supabase_url)
        self.jwks_url = f"{self.supabase_url}/auth/v1/.well-known/jwks.json"
        self.issuer = issuer.rstrip("/") if issuer else f"{self.supabase_url}/auth/v1"
        if self.issuer != f"{self.supabase_url}/auth/v1":
            raise ValueError("JWT issuer must belong to the configured Supabase project")
        self.audience = audience.strip()
        self.jwks_cache_ttl_seconds = jwks_cache_ttl_seconds
        self.unknown_kid_refresh_interval_seconds = unknown_kid_refresh_interval_seconds
        self.clock_skew_seconds = clock_skew_seconds
        self._client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(5.0),
            follow_redirects=False,
        )
        self._owns_client = http_client is None
        self._key_cache: dict[str, Any] = {}
        self._cache_expires_at = 0.0
        self._refresh_lock = asyncio.Lock()
        self._unknown_kid_refresh_lock = asyncio.Lock()
        self._last_unknown_kid_refresh_at = 0.0

    async def _refresh_keys(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and self._key_cache and now < self._cache_expires_at:
            return

        async with self._refresh_lock:
            now = time.monotonic()
            if not force and self._key_cache and now < self._cache_expires_at:
                return
            try:
                response = await self._client.get(
                    self.jwks_url,
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise JWTVerificationError(
                    "jwks_unavailable", "Authentication service is unavailable"
                ) from exc

            keys = payload.get("keys") if isinstance(payload, dict) else None
            if not isinstance(keys, list):
                raise JWTVerificationError(
                    "jwks_invalid", "Authentication service returned invalid keys"
                )

            parsed: dict[str, Any] = {}
            for raw_key in keys:
                if not isinstance(raw_key, dict):
                    continue
                kid = raw_key.get("kid")
                algorithm = raw_key.get("alg")
                if not isinstance(kid, str) or not kid or algorithm not in ALLOWED_JWT_ALGORITHMS:
                    continue
                try:
                    parsed[kid] = jwt.PyJWK.from_dict(raw_key, algorithm=algorithm).key
                except (jwt.PyJWTError, ValueError, TypeError):
                    continue

            if not parsed:
                raise JWTVerificationError(
                    "jwks_invalid", "Authentication service returned no usable keys"
                )
            self._key_cache = parsed
            self._cache_expires_at = time.monotonic() + self.jwks_cache_ttl_seconds

    async def _signing_key(self, kid: str) -> Any:
        await self._refresh_keys()
        key = self._key_cache.get(kid)
        if key is None:
            # Rotation can introduce a kid before the normal cache TTL expires,
            # but fabricated kids must not force one network request apiece.
            async with self._unknown_kid_refresh_lock:
                now = time.monotonic()
                if (
                    now - self._last_unknown_kid_refresh_at
                    >= self.unknown_kid_refresh_interval_seconds
                ):
                    self._last_unknown_kid_refresh_at = now
                    await self._refresh_keys(force=True)
            key = self._key_cache.get(kid)
        if key is None:
            raise JWTVerificationError("unknown_signing_key")
        return key

    async def verify(self, token: str) -> CurrentUser:
        """Verify signature/claims and return the authenticated Supabase user."""

        if not token or len(token) > 16_384:
            raise JWTVerificationError("malformed_token")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise JWTVerificationError("malformed_token") from exc

        kid = header.get("kid")
        algorithm = header.get("alg")
        if not isinstance(kid, str) or not kid:
            raise JWTVerificationError("missing_signing_key")
        if algorithm not in ALLOWED_JWT_ALGORITHMS:
            raise JWTVerificationError("unsupported_algorithm")

        signing_key = await self._signing_key(kid)
        try:
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=[algorithm],
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.clock_skew_seconds,
                options={
                    "require": ["sub", "iss", "aud", "exp"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
        except jwt.ExpiredSignatureError as exc:
            raise JWTVerificationError("token_expired", "Access token has expired") from exc
        except jwt.ImmatureSignatureError as exc:
            raise JWTVerificationError("token_not_active") from exc
        except jwt.InvalidIssuerError as exc:
            raise JWTVerificationError("wrong_project") from exc
        except jwt.InvalidAudienceError as exc:
            raise JWTVerificationError("wrong_audience") from exc
        except jwt.PyJWTError as exc:
            raise JWTVerificationError("invalid_token") from exc

        try:
            user_id = UUID(str(claims["sub"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise JWTVerificationError("invalid_subject") from exc

        role = claims.get("role")
        if not isinstance(role, str) or role != "authenticated":
            raise JWTVerificationError("invalid_role")
        email = claims.get("email")
        if not isinstance(email, str):
            email = None
        return CurrentUser(
            id=user_id,
            role=role,
            email=email,
            claims=MappingProxyType(dict(claims)),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> CurrentUser:
    """FastAPI dependency using ``app.state.jwt_verifier`` configured at startup."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer access token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    verifier = getattr(request.app.state, "jwt_verifier", None)
    if not isinstance(verifier, SupabaseJWTVerifier):
        raise RuntimeError("JWT verifier has not been configured on app.state.jwt_verifier")
    try:
        return await verifier.verify(credentials.credentials)
    except JWTVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from exc
