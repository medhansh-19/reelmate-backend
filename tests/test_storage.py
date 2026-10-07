from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.storage import (
    R2Storage,
    R2StorageSettings,
    StorageConfigurationError,
    StorageError,
    StorageObjectNotFound,
)


class FakeS3Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object], int]] = []

    def _record(self, name: str, args: tuple[object, ...], kwargs: dict[str, object]) -> None:
        self.calls.append((name, args, kwargs, threading.get_ident()))

    def generate_presigned_url(self, operation: str, **kwargs: object) -> str:
        self._record("generate_presigned_url", (operation,), kwargs)
        return (
            "https://test-account.r2.cloudflarestorage.com/private-bucket/key"
            "?X-Amz-Signature=signed"
        )

    def head_object(self, **kwargs: object) -> dict[str, object]:
        self._record("head_object", (), kwargs)
        return {
            "ContentLength": 1234,
            "ContentType": "video/mp4",
            "ETag": '"etag-value"',
            "LastModified": datetime(2026, 8, 9, tzinfo=UTC),
            "Metadata": {"owner": "private"},
        }

    def download_file(self, *args: object, **kwargs: object) -> None:
        self._record("download_file", args, kwargs)
        Path(str(args[2])).write_bytes(b"private video")

    def delete_object(self, **kwargs: object) -> None:
        self._record("delete_object", (), kwargs)


class FakeClientError(Exception):
    def __init__(self, status: int, code: str) -> None:
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }


class MissingS3Client(FakeS3Client):
    def head_object(self, **kwargs: object) -> dict[str, object]:
        raise FakeClientError(404, "NoSuchKey")


@pytest.fixture
def settings() -> R2StorageSettings:
    return R2StorageSettings(
        account_id="test-account",
        access_key_id="project-specific-access",
        secret_access_key="project-specific-secret",
        bucket_name="private-bucket",
        upload_expiry_seconds=300,
    )


def test_settings_hide_credentials_and_reject_long_lived_urls() -> None:
    settings = R2StorageSettings(
        account_id="account",
        access_key_id="access-secret",
        secret_access_key="top-secret",
        bucket_name="bucket",
    )

    rendered = repr(settings)
    assert "access-secret" not in rendered
    assert "top-secret" not in rendered
    assert settings.endpoint_url == "https://account.r2.cloudflarestorage.com"

    with pytest.raises(StorageConfigurationError):
        R2StorageSettings(
            account_id="account",
            access_key_id="access",
            secret_access_key="secret",
            bucket_name="bucket",
            max_upload_expiry_seconds=901,
        )


def test_generated_object_keys_are_owned_unguessable_and_safe(
    settings: R2StorageSettings,
) -> None:
    storage = R2Storage(settings, client=FakeS3Client())
    user_id = uuid4()
    analysis_id = uuid4()

    first = storage.generate_object_key(
        user_id=user_id,
        analysis_id=analysis_id,
        filename="../../creator.MP4",
        content_type="video/mp4",
    )
    second = storage.generate_object_key(
        user_id=user_id,
        analysis_id=analysis_id,
        filename="creator.mp4",
        content_type="video/mp4",
    )

    assert first.startswith(f"reelmate/analyses/{user_id}/{analysis_id}/source-")
    assert first.endswith(".mp4")
    assert first != second
    assert ".." not in first
    UUID(str(user_id))

    with pytest.raises(ValueError, match="UUID"):
        storage.generate_object_key(
            user_id="../another-user",
            analysis_id=analysis_id,
            content_type="video/mp4",
        )


@pytest.mark.asyncio
async def test_create_upload_signs_private_put_in_a_worker_thread(
    settings: R2StorageSettings,
) -> None:
    client = FakeS3Client()
    storage = R2Storage(settings, client=client)
    key = storage.generate_object_key(
        user_id=uuid4(),
        analysis_id=uuid4(),
        content_type="video/mp4",
    )
    caller_thread = threading.get_ident()

    target = await storage.create_upload(
        key,
        "video/mp4",
        content_length=1_234,
        expires_seconds=120,
    )

    assert target.object_key == key
    assert target.method == "PUT"
    assert target.headers == {"Content-Type": "video/mp4", "Content-Length": "1234"}
    assert target.expires_in_seconds == 120
    assert "X-Amz-Signature=" in target.url
    name, args, kwargs, call_thread = client.calls[0]
    assert name == "generate_presigned_url"
    assert args == ("put_object",)
    assert kwargs == {
        "Params": {
            "Bucket": "private-bucket",
            "Key": key,
            "ContentType": "video/mp4",
            "ContentLength": 1_234,
        },
        "ExpiresIn": 120,
        "HttpMethod": "PUT",
    }
    assert call_thread != caller_thread


@pytest.mark.asyncio
async def test_create_upload_uses_configured_expiry_and_size_ceiling() -> None:
    configured = R2StorageSettings(
        account_id="test-account",
        access_key_id="project-specific-access",
        secret_access_key="project-specific-secret",
        bucket_name="private-bucket",
        upload_expiry_seconds=120,
        max_video_bytes=2_000,
    )
    client = FakeS3Client()
    storage = R2Storage(configured, client=client)

    target = await storage.create_upload(
        "reelmate/analyses/u/a/source.mp4",
        "video/mp4",
        content_length=2_000,
    )

    assert target.expires_in_seconds == 120
    assert client.calls[0][2]["ExpiresIn"] == 120
    with pytest.raises(ValueError, match="configured maximum"):
        await storage.create_upload(
            "reelmate/analyses/u/a/source.mp4",
            "video/mp4",
            content_length=2_000,
            expires_seconds=600,
        )
    with pytest.raises(ValueError, match="2000 bytes"):
        await storage.create_upload(
            "reelmate/analyses/u/a/source.mp4",
            "video/mp4",
            content_length=2_001,
        )


@pytest.mark.asyncio
async def test_private_head_download_and_delete_use_injected_bucket(
    settings: R2StorageSettings, tmp_path: Path
) -> None:
    client = FakeS3Client()
    storage = R2Storage(settings, client=client)
    key = storage.generate_object_key(
        user_id=uuid4(),
        analysis_id=uuid4(),
        content_type="video/quicktime",
    )
    destination = tmp_path / "source.mov"
    caller_thread = threading.get_ident()

    metadata = await storage.head_object(key)
    downloaded = await storage.download_file(key, destination)
    await storage.delete_object(key)

    assert metadata.object_key == key
    assert metadata.size_bytes == 1234
    assert metadata.content_type == "video/mp4"
    assert metadata.etag == "etag-value"
    assert metadata.metadata == {"owner": "private"}
    assert downloaded == destination
    assert destination.read_bytes() == b"private video"
    assert [call[0] for call in client.calls] == [
        "head_object",
        "download_file",
        "delete_object",
    ]
    assert all(call[3] != caller_thread for call in client.calls)
    assert client.calls[0][2] == {"Bucket": "private-bucket", "Key": key}
    assert client.calls[1][1] == ("private-bucket", key, str(destination))
    assert client.calls[2][2] == {"Bucket": "private-bucket", "Key": key}


@pytest.mark.asyncio
async def test_storage_rejects_keys_outside_private_prefix_and_bad_targets(
    settings: R2StorageSettings,
) -> None:
    storage = R2Storage(settings, client=FakeS3Client())

    with pytest.raises(ValueError, match="private prefix"):
        await storage.create_upload("another-project/video.mp4", "video/mp4", content_length=1)
    with pytest.raises(ValueError, match="content_type"):
        await storage.create_upload(
            "reelmate/analyses/video.exe", "application/octet-stream", content_length=1
        )
    with pytest.raises(ValueError, match="content_length"):
        await storage.create_upload(
            "reelmate/analyses/video.mp4", "video/mp4", content_length=100_000_001
        )
    with pytest.raises(ValueError, match="expires_seconds"):
        await storage.create_upload(
            "reelmate/analyses/video.mp4",
            "video/mp4",
            content_length=1,
            expires_seconds=901,
        )
    with pytest.raises(ValueError, match="expires_seconds"):
        await storage.create_upload(
            "reelmate/analyses/video.mp4",
            "video/mp4",
            content_length=1,
            expires_seconds=0,
        )

    class PublicUrlClient(FakeS3Client):
        def generate_presigned_url(self, operation: str, **kwargs: object) -> str:
            return "http://public.example.com/video.mp4"

    public_storage = R2Storage(settings, client=PublicUrlClient())
    with pytest.raises(StorageError, match="invalid signed"):
        await public_storage.create_upload(
            "reelmate/analyses/video.mp4", "video/mp4", content_length=1
        )


@pytest.mark.asyncio
async def test_missing_object_has_sanitized_error(settings: R2StorageSettings) -> None:
    storage = R2Storage(settings, client=MissingS3Client())

    with pytest.raises(StorageObjectNotFound, match="Private object was not found") as error:
        await storage.head_object("reelmate/analyses/missing.mp4")

    assert "missing.mp4" not in str(error.value)
