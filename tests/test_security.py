from __future__ import annotations

import asyncio
from uuid import uuid4

import jwt
import pytest

from app.security import JWTVerificationError, SupabaseJWTVerifier


class _UnusedClient:
    async def get(self, url: str, **kwargs: object) -> object:  # pragma: no cover
        raise AssertionError(f"Unexpected network request: {url}")

    async def aclose(self) -> None:
        return None


def test_verifier_pins_issuer_and_jwks_to_one_supabase_project() -> None:
    verifier = SupabaseJWTVerifier(
        supabase_url="https://reelmate-test.supabase.co/",
        http_client=_UnusedClient(),
    )

    assert verifier.issuer == "https://reelmate-test.supabase.co/auth/v1"
    assert verifier.jwks_url == "https://reelmate-test.supabase.co/auth/v1/.well-known/jwks.json"

    with pytest.raises(ValueError, match="configured Supabase project"):
        SupabaseJWTVerifier(
            supabase_url="https://reelmate-test.supabase.co",
            issuer="https://another-project.supabase.co/auth/v1",
            http_client=_UnusedClient(),
        )


def test_verifier_rejects_insecure_non_local_project_url() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        SupabaseJWTVerifier(
            supabase_url="http://reelmate-test.supabase.co",
            http_client=_UnusedClient(),
        )


def test_verify_enforces_algorithm_audience_issuer_and_authenticated_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    verifier = SupabaseJWTVerifier(
        supabase_url="https://reelmate-test.supabase.co",
        http_client=_UnusedClient(),
    )
    monkeypatch.setattr(
        jwt,
        "get_unverified_header",
        lambda token: {"kid": "project-key", "alg": "RS256"},
    )

    async def signing_key(kid: str) -> str:
        assert kid == "project-key"
        return "public-key-placeholder"

    monkeypatch.setattr(verifier, "_signing_key", signing_key)

    def decode(token: str, key: str, **kwargs: object) -> dict[str, object]:
        assert token == "header.payload.signature"
        assert key == "public-key-placeholder"
        assert kwargs["algorithms"] == ["RS256"]
        assert kwargs["audience"] == "authenticated"
        assert kwargs["issuer"] == "https://reelmate-test.supabase.co/auth/v1"
        return {
            "sub": str(user_id),
            "iss": kwargs["issuer"],
            "aud": kwargs["audience"],
            "exp": 4_102_444_800,
            "role": "authenticated",
            "email": "creator@example.test",
        }

    monkeypatch.setattr(jwt, "decode", decode)
    current_user = asyncio.run(verifier.verify("header.payload.signature"))

    assert current_user.id == user_id
    assert current_user.role == "authenticated"
    assert current_user.email == "creator@example.test"


def test_verify_maps_expired_tokens_to_a_stable_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = SupabaseJWTVerifier(
        supabase_url="https://reelmate-test.supabase.co",
        http_client=_UnusedClient(),
    )
    monkeypatch.setattr(
        jwt,
        "get_unverified_header",
        lambda token: {"kid": "project-key", "alg": "ES256"},
    )

    async def signing_key(kid: str) -> str:
        return "public-key-placeholder"

    monkeypatch.setattr(verifier, "_signing_key", signing_key)

    def expired(*args: object, **kwargs: object) -> None:
        raise jwt.ExpiredSignatureError("expired")

    monkeypatch.setattr(jwt, "decode", expired)
    with pytest.raises(JWTVerificationError) as caught:
        asyncio.run(verifier.verify("header.payload.signature"))

    assert caught.value.code == "token_expired"


def test_verify_rejects_symmetric_algorithm_without_fetching_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = SupabaseJWTVerifier(
        supabase_url="https://reelmate-test.supabase.co",
        http_client=_UnusedClient(),
    )
    monkeypatch.setattr(
        jwt,
        "get_unverified_header",
        lambda token: {"kid": "legacy-key", "alg": "HS256"},
    )

    with pytest.raises(JWTVerificationError) as caught:
        asyncio.run(verifier.verify("header.payload.signature"))

    assert caught.value.code == "unsupported_algorithm"


def test_unknown_key_ids_throttle_forced_jwks_refreshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = SupabaseJWTVerifier(
        supabase_url="https://reelmate-test.supabase.co",
        http_client=_UnusedClient(),
    )
    verifier._key_cache = {"known-key": object()}
    verifier._cache_expires_at = float("inf")
    forced_refreshes = 0

    async def refresh(*, force: bool = False) -> None:
        nonlocal forced_refreshes
        forced_refreshes += int(force)

    monkeypatch.setattr(verifier, "_refresh_keys", refresh)

    async def exercise() -> None:
        for kid in ("fabricated-one", "fabricated-two"):
            with pytest.raises(JWTVerificationError, match="Invalid access token"):
                await verifier._signing_key(kid)

    asyncio.run(exercise())
    assert forced_refreshes == 1
