from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app import repository
from app.api.routes import music_preferences as routes
from app.db import MusicPreference, StoryVocalPreference
from app.dependencies import get_authenticated_user, get_session
from app.security import CurrentUser

USER_ID = UUID("10000000-0000-4000-8000-000000000001")


@pytest.fixture
def test_app() -> FastAPI:
    application = FastAPI()
    application.include_router(routes.router, prefix="/v1")

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, object())

    async def user_override() -> CurrentUser:
        return CurrentUser(
            id=USER_ID,
            role="authenticated",
            email="creator@example.test",
            claims=MappingProxyType({}),
        )

    application.dependency_overrides[get_session] = session_override
    application.dependency_overrides[get_authenticated_user] = user_override
    return application


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app),
        base_url="https://api.example.test",
    ) as http_client:
        yield http_client


async def test_empty_music_profile_has_private_first_party_defaults(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def empty(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(repository, "get_music_preference", empty)
    response = await client.get("/v1/music-preferences")

    assert response.status_code == 200
    assert response.json() == {
        "preferred_languages": [],
        "preferred_moods": [],
        "favorite_artists": [],
        "favorite_tracks": [],
        "default_vocal_preference": "any",
        "profile_version": "1",
        "revision": 0,
        "updated_at": None,
        "onboarding_completed_at": None,
    }


async def test_update_normalizes_and_persists_owned_music_profile(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    updated_at = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)

    async def upsert(_session: AsyncSession, **values: Any) -> MusicPreference:
        captured.update(values)
        return MusicPreference(
            user_id=values["user_id"],
            preferred_languages=values["preferred_languages"],
            preferred_moods=values["preferred_moods"],
            favorite_artists=values["favorite_artists"],
            favorite_tracks=values["favorite_tracks"],
            default_vocal_preference=values["default_vocal_preference"],
            profile_version="1",
            revision=1,
            onboarding_completed_at=None,
            created_at=updated_at,
            updated_at=updated_at,
        )

    monkeypatch.setattr(repository, "upsert_music_preference", upsert)
    response = await client.put(
        "/v1/music-preferences",
        json={
            "preferred_languages": ["Hindi", "Instrumental", "Hindi"],
            "preferred_moods": ["dreamy", "romantic", "dreamy"],
            "favorite_artists": ["  Anuv   Jain  ", "anuv jain", "A.R. Rahman"],
            "favorite_tracks": ["Experience", " experience "],
            "default_vocal_preference": "no_lyrics",
        },
    )

    assert response.status_code == 200
    assert captured["user_id"] == USER_ID
    assert captured["preferred_languages"] == ["Hindi", "Instrumental"]
    assert captured["preferred_moods"] == ["dreamy", "romantic"]
    assert captured["favorite_artists"] == ["Anuv Jain", "A.R. Rahman"]
    assert captured["favorite_tracks"] == ["Experience"]
    assert captured["default_vocal_preference"] == StoryVocalPreference.NO_LYRICS
    assert captured["complete_onboarding"] is False
    assert response.json()["revision"] == 1
    assert response.json()["updated_at"] == "2026-08-09T12:00:00Z"
    assert response.json()["onboarding_completed_at"] is None


async def test_update_can_complete_music_onboarding(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    completed_at = datetime(2026, 8, 9, 12, 5, tzinfo=UTC)

    async def upsert(_session: AsyncSession, **values: Any) -> MusicPreference:
        captured.update(values)
        return MusicPreference(
            user_id=values["user_id"],
            preferred_languages=values["preferred_languages"],
            preferred_moods=values["preferred_moods"],
            favorite_artists=values["favorite_artists"],
            favorite_tracks=values["favorite_tracks"],
            default_vocal_preference=values["default_vocal_preference"],
            profile_version="1",
            revision=1,
            onboarding_completed_at=completed_at,
            created_at=completed_at,
            updated_at=completed_at,
        )

    monkeypatch.setattr(repository, "upsert_music_preference", upsert)
    response = await client.put(
        "/v1/music-preferences",
        json={
            "preferred_languages": ["English"],
            "preferred_moods": ["joyful"],
            "complete_onboarding": True,
        },
    )

    assert response.status_code == 200
    assert captured["complete_onboarding"] is True
    assert response.json()["onboarding_completed_at"] == "2026-08-09T12:05:00Z"


async def test_update_rejects_more_than_twelve_favorite_artists(
    client: httpx.AsyncClient,
) -> None:
    response = await client.put(
        "/v1/music-preferences",
        json={"favorite_artists": [f"Artist {index}" for index in range(13)]},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("favorite_artists", "a" * 101),
        ("favorite_tracks", "t" * 151),
    ],
)
async def test_update_rejects_values_too_long_for_database(
    client: httpx.AsyncClient,
    field: str,
    value: str,
) -> None:
    response = await client.put("/v1/music-preferences", json={field: [value]})

    assert response.status_code == 422


async def test_update_rejects_unknown_fields(client: httpx.AsyncClient) -> None:
    response = await client.put(
        "/v1/music-preferences",
        json={"spotify_history": ["must-not-be-accepted"]},
    )

    assert response.status_code == 422
