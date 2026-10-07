from __future__ import annotations

import asyncio
import mimetypes
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

_VIDEO_EXTENSIONS = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
}
_IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
_MEDIA_EXTENSIONS = {**_VIDEO_EXTENSIONS, **_IMAGE_EXTENSIONS}


class StorageError(RuntimeError):
    """Base error for private object-storage operations."""


class StorageDependencyError(StorageError):
    """Raised when the optional S3 client dependency is unavailable."""


class StorageConfigurationError(StorageError):
    """Raised when project-specific R2 settings are invalid."""


class StorageObjectNotFound(StorageError):
    """Raised when a requested private object does not exist."""


@dataclass(frozen=True, slots=True)
class R2StorageSettings:
    """Credentials and policy for one ReelMate project's private R2 bucket.

    Values are injected by the application. This module deliberately does not
    read environment variables or share a process-global client, which keeps
    credentials scoped to the project that created this service instance.
    """

    account_id: str
    access_key_id: str = field(repr=False)
    secret_access_key: str = field(repr=False)
    bucket_name: str
    key_prefix: str = "reelmate/analyses"
    upload_expiry_seconds: int = 600
    max_upload_expiry_seconds: int = 900
    max_video_bytes: int = 100_000_000
    max_image_bytes: int = 15_000_000

    def __post_init__(self) -> None:
        required = {
            "account_id": self.account_id,
            "access_key_id": self.access_key_id,
            "secret_access_key": self.secret_access_key,
            "bucket_name": self.bucket_name,
            "key_prefix": self.key_prefix,
        }
        missing = [name for name, value in required.items() if not value.strip()]
        if missing:
            names = ", ".join(sorted(missing))
            raise StorageConfigurationError(f"Missing R2 settings: {names}")

        prefix = self.key_prefix.strip("/")
        if prefix != self.key_prefix or not _is_safe_relative_key(prefix):
            raise StorageConfigurationError("R2 key_prefix must be a safe relative object prefix")
        if not 30 <= self.upload_expiry_seconds <= self.max_upload_expiry_seconds:
            raise StorageConfigurationError(
                "R2 upload expiry must be between 30 seconds and the configured maximum"
            )
        if self.max_upload_expiry_seconds > 900:
            raise StorageConfigurationError("R2 presigned upload expiry cannot exceed 900 seconds")
        if not 0 < self.max_video_bytes <= 100_000_000:
            raise StorageConfigurationError("R2 max video bytes must be between 1 and 100 MB")
        if not 0 < self.max_image_bytes <= 15_000_000:
            raise StorageConfigurationError("R2 max image bytes must be between 1 and 15 MB")

    @property
    def endpoint_url(self) -> str:
        return f"https://{self.account_id}.r2.cloudflarestorage.com"


@dataclass(frozen=True, slots=True)
class PresignedUpload:
    """A temporary capability to PUT one private object.

    ``url`` is a short-lived signed endpoint, never a public bucket URL.
    Clients must send every entry in ``headers`` unchanged.
    """

    object_key: str
    url: str = field(repr=False)
    headers: dict[str, str]
    expires_in_seconds: int
    method: str = "PUT"


@dataclass(frozen=True, slots=True)
class StoredObject:
    object_key: str
    size_bytes: int
    content_type: str | None
    etag: str | None
    last_modified: datetime | None
    metadata: dict[str, str]


class R2Storage:
    """Async facade over boto3 for a private Cloudflare R2 bucket."""

    def __init__(self, settings: R2StorageSettings, *, client: Any | None = None) -> None:
        self.settings = settings
        self._client = client if client is not None else _build_r2_client(settings)

    def generate_object_key(
        self,
        *,
        user_id: str | UUID,
        analysis_id: str | UUID,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> str:
        """Generate an unguessable, traversal-safe key for owned source media."""

        user_uuid = _canonical_uuid(user_id, "user_id")
        analysis_uuid = _canonical_uuid(analysis_id, "analysis_id")
        extension = _safe_media_extension(filename=filename, content_type=content_type)
        return (
            f"{self.settings.key_prefix}/{user_uuid}/{analysis_uuid}/"
            f"source-{uuid4().hex}{extension}"
        )

    async def create_upload(
        self,
        object_key: str,
        content_type: str,
        *,
        content_length: int,
        expires_seconds: int | None = None,
    ) -> PresignedUpload:
        """Create a short-lived signed PUT bound to type and exact byte length."""

        key = self._validate_object_key(object_key)
        if content_type not in _MEDIA_EXTENSIONS:
            raise ValueError("content_type must be a supported video or image type")
        maximum_bytes = (
            self.settings.max_video_bytes
            if content_type in _VIDEO_EXTENSIONS
            else self.settings.max_image_bytes
        )
        if not 0 < content_length <= maximum_bytes:
            raise ValueError(f"content_length must be between 1 byte and {maximum_bytes} bytes")

        expires = (
            self.settings.upload_expiry_seconds if expires_seconds is None else expires_seconds
        )
        maximum_expiry = min(
            self.settings.upload_expiry_seconds,
            self.settings.max_upload_expiry_seconds,
        )
        if not 30 <= expires <= maximum_expiry:
            raise ValueError(
                "expires_seconds must be between 30 seconds and the configured maximum"
            )

        params = {
            "Bucket": self.settings.bucket_name,
            "Key": key,
            "ContentType": content_type,
            "ContentLength": content_length,
        }
        try:
            url = await asyncio.to_thread(
                self._client.generate_presigned_url,
                "put_object",
                Params=params,
                ExpiresIn=expires,
                HttpMethod="PUT",
            )
        except Exception as exc:
            raise StorageError("Could not create a private upload target") from exc

        if not isinstance(url, str) or not _is_https_url(url):
            raise StorageError("R2 returned an invalid signed upload target")
        return PresignedUpload(
            object_key=key,
            url=url,
            headers={
                "Content-Type": content_type,
                "Content-Length": str(content_length),
            },
            expires_in_seconds=expires,
        )

    async def create_analysis_upload(
        self,
        *,
        user_id: str | UUID,
        analysis_id: str | UUID,
        filename: str,
        content_type: str,
        content_length: int,
        expires_seconds: int | None = None,
    ) -> PresignedUpload:
        key = self.generate_object_key(
            user_id=user_id,
            analysis_id=analysis_id,
            filename=filename,
            content_type=content_type,
        )
        return await self.create_upload(
            key,
            content_type,
            content_length=content_length,
            expires_seconds=expires_seconds,
        )

    async def head_object(self, object_key: str) -> StoredObject:
        key = self._validate_object_key(object_key)
        try:
            response = await asyncio.to_thread(
                self._client.head_object,
                Bucket=self.settings.bucket_name,
                Key=key,
            )
        except Exception as exc:
            if _is_not_found_error(exc):
                raise StorageObjectNotFound("Private object was not found") from exc
            raise StorageError("Could not inspect the private object") from exc

        return StoredObject(
            object_key=key,
            size_bytes=int(response.get("ContentLength", 0)),
            content_type=response.get("ContentType"),
            etag=_normalize_etag(response.get("ETag")),
            last_modified=response.get("LastModified"),
            metadata={str(k): str(v) for k, v in response.get("Metadata", {}).items()},
        )

    async def download_file(self, object_key: str, destination: str | Path) -> Path:
        """Download a private object to a caller-managed local path."""

        key = self._validate_object_key(object_key)
        path = Path(destination)
        if not path.name:
            raise ValueError("destination must be a file path")
        try:
            await asyncio.to_thread(
                self._client.download_file,
                self.settings.bucket_name,
                key,
                str(path),
            )
        except Exception as exc:
            if _is_not_found_error(exc):
                raise StorageObjectNotFound("Private object was not found") from exc
            raise StorageError("Could not download the private object") from exc
        return path

    async def delete_object(self, object_key: str) -> None:
        """Delete a private object. S3-compatible deletes are idempotent."""

        key = self._validate_object_key(object_key)
        try:
            await asyncio.to_thread(
                self._client.delete_object,
                Bucket=self.settings.bucket_name,
                Key=key,
            )
        except Exception as exc:
            raise StorageError("Could not delete the private object") from exc

    def _validate_object_key(self, object_key: str) -> str:
        key = object_key.strip()
        expected_prefix = f"{self.settings.key_prefix}/"
        if not _is_safe_relative_key(key) or not key.startswith(expected_prefix):
            raise ValueError("object_key is outside the configured private prefix")
        return key


def _build_r2_client(settings: R2StorageSettings) -> Any:
    try:
        import boto3  # type: ignore[import-untyped]
        from botocore.config import Config  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - exercised without optional dependency
        raise StorageDependencyError("boto3 is required for Cloudflare R2 storage") from exc

    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def _canonical_uuid(value: str | UUID, field_name: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{field_name} must be a UUID") from exc


def _safe_media_extension(*, filename: str | None, content_type: str | None) -> str:
    if content_type is not None:
        try:
            return _MEDIA_EXTENSIONS[content_type]
        except KeyError as exc:
            raise ValueError("content_type must be a supported video or image type") from exc

    if filename:
        suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
        if suffix in _MEDIA_EXTENSIONS.values() or suffix == ".jpeg":
            if suffix == ".jpeg":
                return ".jpg"
            return suffix
        guessed_type, _ = mimetypes.guess_type(filename)
        if guessed_type in _MEDIA_EXTENSIONS:
            return _MEDIA_EXTENSIONS[guessed_type]
    raise ValueError("a supported media content_type or filename is required")


def _is_safe_relative_key(value: str) -> bool:
    if not value or value.startswith(("/", "\\")) or "\\" in value:
        return False
    path = PurePosixPath(value)
    return all(part not in {"", ".", ".."} for part in path.parts)


def _is_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _normalize_etag(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip('"')


def _is_not_found_error(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    error = response.get("Error", {})
    metadata = response.get("ResponseMetadata", {})
    code = str(error.get("Code", ""))
    status = metadata.get("HTTPStatusCode")
    return code in {"404", "NoSuchKey", "NotFound"} or status == 404
