from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import MappingProxyType, SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import repository
from app.api.routes import analyses as routes
from app.db import (
    Analysis,
    AnalysisMode,
    AnalysisStage,
    AnalysisStatus,
    StoryVocalPreference,
)
from app.dependencies import get_authenticated_user, get_session, get_storage
from app.errors import AppError, app_error_handler
from app.security import CurrentUser
from app.storage import PresignedUpload, StoredObject

USER_ID = UUID("10000000-0000-4000-8000-000000000001")


class FakeStorage:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            max_video_bytes=100_000_000,
            max_image_bytes=15_000_000,
            upload_expiry_seconds=900,
        )
        self.upload_keys: list[str] = []
        self.upload_expiries: list[int | None] = []
        self.deleted_keys: list[str] = []
        self.head_result: StoredObject | None = None
        self.head_calls = 0

    def generate_object_key(
        self,
        *,
        user_id: str | UUID,
        analysis_id: str | UUID,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> str:
        extension = {
            "video/quicktime": ".mov",
            "video/mp4": ".mp4",
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }.get(content_type, ".bin")
        return f"reelmate/analyses/{user_id}/{analysis_id}/source-test{extension}"

    async def create_upload(
        self,
        object_key: str,
        content_type: str,
        *,
        content_length: int,
        expires_seconds: int | None = None,
    ) -> PresignedUpload:
        self.upload_keys.append(object_key)
        self.upload_expiries.append(expires_seconds)
        return PresignedUpload(
            object_key=object_key,
            url="https://storage.example.test/private-signed-upload",
            headers={
                "Content-Type": content_type,
                "Content-Length": str(content_length),
            },
            expires_in_seconds=expires_seconds or 600,
        )

    async def head_object(self, object_key: str) -> StoredObject:
        self.head_calls += 1
        assert self.head_result is not None
        assert object_key == self.head_result.object_key
        return self.head_result

    async def delete_object(self, object_key: str) -> None:
        self.deleted_keys.append(object_key)


def make_analysis(
    *,
    analysis_id: UUID | None = None,
    user_id: UUID = USER_ID,
    status: AnalysisStatus = AnalysisStatus.AWAITING_UPLOAD,
    stage: AnalysisStage = AnalysisStage.AWAITING_UPLOAD,
    declared_size_bytes: int = 1_024,
    mime_type: str = "video/mp4",
    mode: AnalysisMode = AnalysisMode.VIDEO_COACH,
    vocal_preference: StoryVocalPreference = StoryVocalPreference.ANY,
    created_at: datetime | None = None,
) -> Analysis:
    created = created_at or datetime.now(UTC)
    return Analysis(
        id=analysis_id or uuid4(),
        user_id=user_id,
        idempotency_key="request-key-123",
        object_key=f"reelmate/analyses/{user_id}/{analysis_id or uuid4()}/source-test.mp4",
        declared_size_bytes=declared_size_bytes,
        mime_type=mime_type,
        mode=mode,
        vocal_preference=vocal_preference,
        status=status,
        stage=stage,
        score=None,
        failure_code=None,
        failure_retryable=False,
        result_json=None,
        upload_expires_at=datetime.now(UTC) + timedelta(minutes=10),
        created_at=created,
        updated_at=created,
    )


@pytest.fixture
def fake_storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def test_app(fake_storage: FakeStorage) -> FastAPI:
    application = FastAPI()
    application.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
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

    def storage_override() -> Any:
        return fake_storage

    application.dependency_overrides[get_session] = session_override
    application.dependency_overrides[get_authenticated_user] = user_override
    application.dependency_overrides[get_storage] = storage_override
    return application


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app),
        base_url="https://api.example.test",
    ) as http_client:
        yield http_client


async def test_create_is_idempotent_and_presigns_existing_object(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_by_key: dict[str, Analysis] = {}

    async def fake_create(
        _session: AsyncSession,
        **values: Any,
    ) -> Analysis:
        key = cast(str, values["idempotency_key"])
        if key not in created_by_key:
            analysis_id = cast(UUID, values["analysis_id"])
            created_by_key[key] = make_analysis(
                analysis_id=analysis_id,
                user_id=cast(UUID, values["user_id"]),
                declared_size_bytes=cast(int, values["declared_size_bytes"]),
                mime_type=cast(str, values["mime_type"]),
                mode=cast(AnalysisMode, values["mode"]),
            )
            created_by_key[key].object_key = cast(str, values["object_key"])
        return created_by_key[key]

    monkeypatch.setattr(repository, "create_analysis", fake_create)
    payload = {
        "filename": "launch.mp4",
        "content_type": "video/mp4",
        "file_size_bytes": 100_000_000,
    }
    headers = {"Idempotency-Key": "mobile-request-123"}

    first = await client.post("/v1/analyses", json=payload, headers=headers)
    second = await client.post("/v1/analyses", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["analysis_id"] == second.json()["analysis_id"]
    assert first.json()["upload"]["headers"] == {
        "Content-Type": "video/mp4",
        "Content-Length": "100000000",
    }
    assert fake_storage.upload_keys[0] == fake_storage.upload_keys[1]
    assert created_by_key["mobile-request-123"].declared_size_bytes == 100_000_000


async def test_create_rejects_conflicting_idempotency_sources(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/v1/analyses",
        headers={"Idempotency-Key": "header-key-123"},
        json={
            "filename": "launch.mp4",
            "content_type": "video/mp4",
            "file_size_bytes": 10,
            "idempotency_key": "body-key-12345",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"


async def test_create_uses_configured_video_size_limit(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
) -> None:
    fake_storage.settings.max_video_bytes = 1_000

    response = await client.post(
        "/v1/analyses",
        headers={"Idempotency-Key": "configured-size-limit"},
        json={
            "filename": "launch.mp4",
            "content_type": "video/mp4",
            "file_size_bytes": 1_001,
        },
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "MEDIA_TOO_LARGE"


async def test_create_story_image_uses_image_mode_contract(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_create(_session: AsyncSession, **values: Any) -> Analysis:
        analysis = make_analysis(
            analysis_id=cast(UUID, values["analysis_id"]),
            declared_size_bytes=cast(int, values["declared_size_bytes"]),
            mime_type=cast(str, values["mime_type"]),
            mode=cast(AnalysisMode, values["mode"]),
        )
        analysis.object_key = cast(str, values["object_key"])
        return analysis

    monkeypatch.setattr(repository, "create_analysis", fake_create)
    response = await client.post(
        "/v1/analyses",
        headers={"Idempotency-Key": "story-image-123"},
        json={
            "mode": "story_song",
            "filename": "sunset.jpg",
            "content_type": "image/jpeg",
            "file_size_bytes": 2_000_000,
        },
    )

    assert response.status_code == 201
    assert response.json()["mode"] == "story_song"
    assert response.json()["upload"]["headers"] == {
        "Content-Type": "image/jpeg",
        "Content-Length": "2000000",
    }
    assert fake_storage.upload_keys[0].endswith(".jpg")


async def test_create_story_image_persists_no_lyrics_preference(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_create(_session: AsyncSession, **values: Any) -> Analysis:
        captured.update(values)
        return make_analysis(
            analysis_id=cast(UUID, values["analysis_id"]),
            declared_size_bytes=cast(int, values["declared_size_bytes"]),
            mime_type=cast(str, values["mime_type"]),
            mode=cast(AnalysisMode, values["mode"]),
            vocal_preference=cast(StoryVocalPreference, values["vocal_preference"]),
        )

    monkeypatch.setattr(repository, "create_analysis", fake_create)
    response = await client.post(
        "/v1/analyses",
        headers={"Idempotency-Key": "story-no-lyrics-123"},
        json={
            "mode": "story_song",
            "vocal_preference": "no_lyrics",
            "filename": "night.jpg",
            "content_type": "image/jpeg",
            "file_size_bytes": 2_000,
        },
    )

    assert response.status_code == 201
    assert response.json()["vocal_preference"] == "no_lyrics"
    assert captured["vocal_preference"] == StoryVocalPreference.NO_LYRICS


async def test_video_mode_rejects_no_lyrics_preference(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/analyses",
        json={
            "mode": "video_coach",
            "vocal_preference": "no_lyrics",
            "filename": "draft.mp4",
            "content_type": "video/mp4",
            "file_size_bytes": 2_000,
        },
    )

    assert response.status_code == 422


async def test_create_rejects_media_that_does_not_match_mode(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/v1/analyses",
        headers={"Idempotency-Key": "wrong-story-media"},
        json={
            "mode": "story_song",
            "filename": "clip.mp4",
            "content_type": "video/mp4",
            "file_size_bytes": 2_000,
        },
    )

    assert response.status_code == 422


async def test_create_uses_configured_upload_window(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    fake_storage.settings.upload_expiry_seconds = 120

    async def fake_create(_session: AsyncSession, **values: Any) -> Analysis:
        captured.update(values)
        analysis = make_analysis(
            analysis_id=cast(UUID, values["analysis_id"]),
            declared_size_bytes=cast(int, values["declared_size_bytes"]),
            mime_type=cast(str, values["mime_type"]),
        )
        analysis.object_key = cast(str, values["object_key"])
        return analysis

    monkeypatch.setattr(repository, "create_analysis", fake_create)
    response = await client.post(
        "/v1/analyses",
        headers={"Idempotency-Key": "configured-upload-window"},
        json={
            "filename": "launch.mp4",
            "content_type": "video/mp4",
            "file_size_bytes": 1_000,
        },
    )

    assert response.status_code == 201
    assert captured["upload_window_seconds"] == 120
    assert fake_storage.upload_expiries == [120]


async def test_create_maps_one_active_upload_constraint_to_stable_conflict(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def conflict(*args: Any, **kwargs: Any) -> Analysis:
        raise IntegrityError("active analysis", {}, RuntimeError("constraint"))

    monkeypatch.setattr(repository, "create_analysis", conflict)
    response = await client.post(
        "/v1/analyses",
        headers={"Idempotency-Key": "another-upload-123"},
        json={
            "filename": "launch.mp4",
            "content_type": "video/mp4",
            "file_size_bytes": 10,
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ANALYSIS_LIMIT_REACHED"


async def test_submit_head_validates_and_queues_owned_upload(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = make_analysis(declared_size_bytes=100_000_000)
    fake_storage.head_result = StoredObject(
        object_key=analysis.object_key,
        size_bytes=100_000_000,
        content_type="video/mp4",
        etag="abc",
        last_modified=None,
        metadata={},
    )

    async def fake_get(
        _session: AsyncSession,
        *,
        analysis_id: UUID,
        user_id: UUID,
    ) -> Analysis | None:
        assert analysis_id == analysis.id
        assert user_id == USER_ID
        return analysis

    async def fake_queue(
        _session: AsyncSession,
        *,
        analysis_id: UUID,
        user_id: UUID,
        actual_size_bytes: int,
        **_values: Any,
    ) -> Analysis:
        assert analysis_id == analysis.id
        assert user_id == USER_ID
        assert actual_size_bytes == 100_000_000
        analysis.status = AnalysisStatus.QUEUED
        analysis.stage = AnalysisStage.QUEUED
        return analysis

    monkeypatch.setattr(repository, "get_analysis", fake_get)
    monkeypatch.setattr(repository, "queue_analysis", fake_queue)

    response = await client.post(f"/v1/analyses/{analysis.id}/submit")

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert fake_storage.head_calls == 1


async def test_submit_rejects_a_byte_over_decimal_100_mb(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = make_analysis(declared_size_bytes=100_000_000)
    fake_storage.head_result = StoredObject(
        object_key=analysis.object_key,
        size_bytes=100_000_001,
        content_type="video/mp4",
        etag=None,
        last_modified=None,
        metadata={},
    )

    async def fake_get(
        _session: AsyncSession,
        *,
        analysis_id: UUID,
        user_id: UUID,
    ) -> Analysis | None:
        assert analysis_id == analysis.id
        assert user_id == USER_ID
        return analysis

    monkeypatch.setattr(repository, "get_analysis", fake_get)
    response = await client.post(f"/v1/analyses/{analysis.id}/submit")

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "MEDIA_TOO_LARGE"


async def test_submit_replay_does_not_require_deleted_source(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = make_analysis(
        status=AnalysisStatus.COMPLETED,
        stage=AnalysisStage.COMPLETED,
    )

    async def fake_get(
        _session: AsyncSession,
        *,
        analysis_id: UUID,
        user_id: UUID,
    ) -> Analysis | None:
        assert analysis_id == analysis.id
        assert user_id == USER_ID
        return analysis

    monkeypatch.setattr(repository, "get_analysis", fake_get)
    response = await client.post(f"/v1/analyses/{analysis.id}/submit")

    assert response.status_code == 202
    assert response.json()["status"] == "completed"
    assert fake_storage.head_calls == 0


async def test_submit_enforces_one_active_analysis_per_user(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = make_analysis(declared_size_bytes=10_000)
    fake_storage.head_result = StoredObject(
        object_key=analysis.object_key,
        size_bytes=10_000,
        content_type="video/mp4",
        etag=None,
        last_modified=None,
        metadata={},
    )

    async def fake_get(*args: Any, **kwargs: Any) -> Analysis:
        return analysis

    async def conflict(*args: Any, **kwargs: Any) -> Analysis:
        raise IntegrityError("active analysis", {}, RuntimeError("constraint"))

    monkeypatch.setattr(repository, "get_analysis", fake_get)
    monkeypatch.setattr(repository, "queue_analysis", conflict)

    response = await client.post(f"/v1/analyses/{analysis.id}/submit")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ANALYSIS_LIMIT_REACHED"
    assert response.json()["error"]["retryable"] is True


async def test_list_uses_owned_stable_opaque_cursor(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamp = datetime(2026, 8, 9, 8, 0, tzinfo=UTC)
    first = make_analysis(
        analysis_id=UUID("20000000-0000-4000-8000-000000000003"),
        created_at=timestamp,
    )
    second = make_analysis(
        analysis_id=UUID("20000000-0000-4000-8000-000000000002"),
        created_at=timestamp - timedelta(seconds=1),
    )
    third = make_analysis(
        analysis_id=UUID("20000000-0000-4000-8000-000000000001"),
        created_at=timestamp - timedelta(seconds=2),
    )
    calls: list[dict[str, Any]] = []

    async def fake_list(_session: AsyncSession, **values: Any) -> list[Analysis]:
        calls.append(values)
        return [first, second, third] if len(calls) == 1 else [third]

    monkeypatch.setattr(repository, "list_analyses", fake_list)

    page_one = await client.get("/v1/analyses", params={"limit": 2})
    assert page_one.status_code == 200
    cursor = page_one.json()["next_cursor"]
    assert isinstance(cursor, str) and "{" not in cursor

    page_two = await client.get("/v1/analyses", params={"limit": 2, "cursor": cursor})
    assert page_two.status_code == 200
    assert calls[0]["user_id"] == USER_ID
    assert calls[0]["limit"] == 3
    assert calls[1]["before_created_at"] == second.created_at
    assert calls[1]["before_id"] == second.id


async def test_invalid_cursor_has_stable_error_envelope(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/v1/analyses", params={"cursor": "not-a-valid-cursor"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CURSOR"


async def test_retry_maps_non_retryable_transition(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis_id = uuid4()

    async def fake_retry(_session: AsyncSession, **_values: Any) -> Analysis:
        raise repository.InvalidAnalysisTransitionError("no")

    monkeypatch.setattr(repository, "retry_analysis", fake_retry)
    response = await client.post(f"/v1/analyses/{analysis_id}/retry")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_RETRYABLE"


async def test_retry_maps_active_job_constraint_to_stable_conflict(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def conflict(*args: Any, **kwargs: Any) -> Analysis:
        raise IntegrityError("active analysis", {}, RuntimeError("constraint"))

    monkeypatch.setattr(repository, "retry_analysis", conflict)
    response = await client.post(f"/v1/analyses/{uuid4()}/retry")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ANALYSIS_LIMIT_REACHED"


async def test_cancel_returns_terminal_state(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = make_analysis(status=AnalysisStatus.QUEUED, stage=AnalysisStage.QUEUED)

    async def fake_cancel(
        _session: AsyncSession,
        *,
        analysis_id: UUID,
        user_id: UUID,
    ) -> Analysis:
        assert analysis_id == analysis.id
        assert user_id == USER_ID
        analysis.status = AnalysisStatus.CANCELLED
        analysis.stage = AnalysisStage.CANCELLED
        return analysis

    monkeypatch.setattr(repository, "cancel_analysis", fake_cancel)
    response = await client.post(f"/v1/analyses/{analysis.id}/cancel")

    assert response.status_code == 202
    assert response.json() == {
        "analysis_id": str(analysis.id),
        "mode": "video_coach",
        "vocal_preference": "any",
        "status": "cancelled",
        "stage": "cancelled",
    }


async def test_cancel_maps_non_cancellable_transition(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def reject(*args: Any, **kwargs: Any) -> Analysis:
        raise repository.InvalidAnalysisTransitionError("completed")

    monkeypatch.setattr(repository, "cancel_analysis", reject)
    response = await client.post(f"/v1/analyses/{uuid4()}/cancel")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_CANCELLABLE"


async def test_delete_denies_queued_row_atomically(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = make_analysis(status=AnalysisStatus.QUEUED, stage=AnalysisStage.QUEUED)

    async def fake_delete(
        _session: AsyncSession,
        *,
        analysis_id: UUID,
        user_id: UUID,
    ) -> Analysis | None:
        assert analysis_id == analysis.id
        assert user_id == USER_ID
        return None

    async def fake_get(
        _session: AsyncSession,
        *,
        analysis_id: UUID,
        user_id: UUID,
    ) -> Analysis | None:
        assert analysis_id == analysis.id
        assert user_id == USER_ID
        return analysis

    monkeypatch.setattr(routes, "_delete_if_deletable", fake_delete)
    monkeypatch.setattr(repository, "get_analysis", fake_get)
    response = await client.delete(f"/v1/analyses/{analysis.id}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ANALYSIS_BUSY"
    assert fake_storage.deleted_keys == []


async def test_delete_durably_schedules_private_object_cleanup(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = make_analysis()

    async def fake_delete(
        _session: AsyncSession,
        *,
        analysis_id: UUID,
        user_id: UUID,
    ) -> Analysis | None:
        assert analysis_id == analysis.id
        assert user_id == USER_ID
        return analysis

    monkeypatch.setattr(routes, "_delete_if_deletable", fake_delete)
    response = await client.delete(f"/v1/analyses/{analysis.id}")

    assert response.status_code == 204
    assert response.content == b""
    # Object deletion is performed from the Postgres outbox by the worker, not
    # inline where a process crash could orphan the private upload.
    assert fake_storage.deleted_keys == []
