"""Authenticated asynchronous reel-analysis endpoints."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import repository
from app.db import Analysis, AnalysisMode, AnalysisStatus, StoryVocalPreference
from app.dependencies import SessionDep, StorageDep, UserDep
from app.errors import AppError
from app.schemas import (
    AnalysisCancelResponse,
    AnalysisCreatedResponse,
    AnalysisCreateRequest,
    AnalysisListItem,
    AnalysisListResponse,
    AnalysisStatusResponse,
    AnalysisSubmitResponse,
    UploadTarget,
)
from app.storage import PresignedUpload, StorageError, StorageObjectNotFound

router = APIRouter(prefix="/analyses", tags=["analyses"])

MAX_LIST_LIMIT = 50
_DELETABLE_STATUSES = (
    AnalysisStatus.AWAITING_UPLOAD,
    AnalysisStatus.COMPLETED,
    AnalysisStatus.FAILED,
    AnalysisStatus.CANCELLED,
    AnalysisStatus.EXPIRED,
)


def _app_not_found() -> AppError:
    return AppError(
        "ANALYSIS_NOT_FOUND",
        "The analysis was not found",
        status_code=status.HTTP_404_NOT_FOUND,
    )


def _idempotency_key(body_key: str | None, header_key: str | None) -> str:
    body = body_key.strip() if body_key is not None else None
    header = header_key.strip() if header_key is not None else None
    if body is not None and not 8 <= len(body) <= 128:
        raise AppError(
            "INVALID_IDEMPOTENCY_KEY",
            "The body idempotency key must contain between 8 and 128 characters",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if header is not None and not 8 <= len(header) <= 128:
        raise AppError(
            "INVALID_IDEMPOTENCY_KEY",
            "Idempotency-Key must contain between 8 and 128 characters",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if body is not None and header is not None and body != header:
        raise AppError(
            "IDEMPOTENCY_KEY_CONFLICT",
            "The body and Idempotency-Key header must match when both are supplied",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return header or body or str(uuid4())


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _upload_expiry(analysis: Analysis, *, maximum_seconds: int) -> tuple[datetime, int]:
    now = datetime.now(UTC)
    row_expiry = _aware_utc(analysis.upload_expires_at)
    remaining_seconds = int((row_expiry - now).total_seconds())
    if remaining_seconds < 30:
        raise AppError(
            "UPLOAD_WINDOW_EXPIRED",
            "The upload window expired; create a new analysis",
            status_code=status.HTTP_409_CONFLICT,
        )
    # R2 enforces a maximum 15-minute presigned upload capability.
    return row_expiry, min(remaining_seconds, maximum_seconds, 900)


def _created_response(
    analysis: Analysis,
    upload: PresignedUpload,
    *,
    row_expires_at: datetime,
) -> AnalysisCreatedResponse:
    signed_expiry = datetime.now(UTC) + timedelta(seconds=upload.expires_in_seconds)
    return AnalysisCreatedResponse(
        analysis_id=analysis.id,
        mode=analysis.mode.value,
        vocal_preference=analysis.vocal_preference.value,
        status=analysis.status.value,
        upload=UploadTarget(
            url=upload.url,
            method="PUT",
            headers=upload.headers,
            expires_at=min(signed_expiry, row_expires_at),
        ),
    )


def _status_response(analysis: Analysis) -> AnalysisStatusResponse:
    return AnalysisStatusResponse(
        analysis_id=analysis.id,
        mode=analysis.mode.value,
        vocal_preference=analysis.vocal_preference.value,
        status=analysis.status.value,
        stage=analysis.stage.value,
        retryable=analysis.failure_retryable,
        failure_code=analysis.failure_code,
        result=analysis.result_json,
        created_at=analysis.created_at,
        updated_at=analysis.updated_at,
    )


def _submit_response(analysis: Analysis) -> AnalysisSubmitResponse:
    return AnalysisSubmitResponse(
        analysis_id=analysis.id,
        mode=analysis.mode.value,
        vocal_preference=analysis.vocal_preference.value,
        status=analysis.status.value,
        stage=analysis.stage.value,
    )


def _niche_detected(analysis: Analysis) -> str | None:
    if not isinstance(analysis.result_json, dict):
        return None
    value = analysis.result_json.get("niche_detected")
    return value if isinstance(value, str) else None


def _encode_cursor(analysis: Analysis) -> str:
    payload = {
        "v": 1,
        "created_at": _aware_utc(analysis.created_at).isoformat(),
        "id": str(analysis.id),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return encoded.rstrip(b"=").decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.b64decode(cursor + padding, altchars=b"-_", validate=True)
        payload: Any = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("v") != 1:
            raise ValueError
        created_raw = payload.get("created_at")
        analysis_raw = payload.get("id")
        if not isinstance(created_raw, str) or not isinstance(analysis_raw, str):
            raise ValueError
        created_at = datetime.fromisoformat(created_raw)
        if created_at.tzinfo is None:
            raise ValueError
        return created_at.astimezone(UTC), UUID(analysis_raw)
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
        raise AppError(
            "INVALID_CURSOR",
            "The pagination cursor is invalid",
            status_code=status.HTTP_400_BAD_REQUEST,
        ) from exc


async def _delete_if_deletable(
    session: AsyncSession,
    *,
    analysis_id: UUID,
    user_id: UUID,
) -> Analysis | None:
    return await repository.delete_analysis(
        session,
        analysis_id=analysis_id,
        user_id=user_id,
        allowed_statuses=_DELETABLE_STATUSES,
    )


@router.post("", response_model=AnalysisCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_analysis(
    body: AnalysisCreateRequest,
    user: UserDep,
    session: SessionDep,
    storage: StorageDep,
    idempotency_header: Annotated[
        str | None,
        Header(alias="Idempotency-Key"),
    ] = None,
) -> AnalysisCreatedResponse:
    """Create an owned row and issue a short-lived private R2 PUT target."""

    mode = AnalysisMode(body.mode)
    vocal_preference = StoryVocalPreference(body.vocal_preference)
    maximum_bytes = (
        storage.settings.max_video_bytes
        if mode == AnalysisMode.VIDEO_COACH
        else storage.settings.max_image_bytes
    )
    if body.file_size_bytes > maximum_bytes:
        raise AppError(
            "MEDIA_TOO_LARGE",
            f"The selected media exceeds this mode's {maximum_bytes}-byte limit",
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        )
    key = _idempotency_key(body.idempotency_key, idempotency_header)
    proposed_id = uuid4()
    object_key = storage.generate_object_key(
        user_id=user.id,
        analysis_id=proposed_id,
        filename=body.filename,
        content_type=body.content_type,
    )
    try:
        analysis = await repository.create_analysis(
            session,
            user_id=user.id,
            idempotency_key=key,
            object_key=object_key,
            declared_size_bytes=body.file_size_bytes,
            mime_type=body.content_type,
            mode=mode,
            vocal_preference=vocal_preference,
            analysis_id=proposed_id,
            upload_window_seconds=storage.settings.upload_expiry_seconds,
        )
    except IntegrityError as exc:
        raise AppError(
            "ANALYSIS_LIMIT_REACHED",
            "Finish or remove the current analysis before creating another video",
            status_code=status.HTTP_409_CONFLICT,
            retryable=True,
        ) from exc
    except ValueError as exc:
        raise AppError(
            "INVALID_ANALYSIS",
            "The analysis request is invalid",
            status_code=status.HTTP_400_BAD_REQUEST,
        ) from exc

    if (
        analysis.declared_size_bytes != body.file_size_bytes
        or analysis.mime_type != body.content_type
        or analysis.mode != mode
        or analysis.vocal_preference != vocal_preference
    ):
        raise AppError(
            "IDEMPOTENCY_PAYLOAD_MISMATCH",
            "This idempotency key was already used with different media",
            status_code=status.HTTP_409_CONFLICT,
        )
    if analysis.status != AnalysisStatus.AWAITING_UPLOAD:
        raise AppError(
            "ANALYSIS_ALREADY_SUBMITTED",
            "This idempotent analysis has already been submitted",
            status_code=status.HTTP_409_CONFLICT,
        )

    row_expires_at, expires_seconds = _upload_expiry(
        analysis,
        maximum_seconds=storage.settings.upload_expiry_seconds,
    )
    try:
        upload = await storage.create_upload(
            analysis.object_key,
            analysis.mime_type,
            content_length=analysis.declared_size_bytes,
            expires_seconds=expires_seconds,
        )
    except (StorageError, ValueError) as exc:
        raise AppError(
            "STORAGE_UNAVAILABLE",
            "Could not create the private media upload",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            retryable=True,
        ) from exc
    return _created_response(analysis, upload, row_expires_at=row_expires_at)


@router.post(
    "/{analysis_id}/submit",
    response_model=AnalysisSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_analysis(
    analysis_id: UUID,
    user: UserDep,
    session: SessionDep,
    storage: StorageDep,
) -> AnalysisSubmitResponse:
    """Verify the private upload and atomically enqueue it for processing."""

    analysis = await repository.get_analysis(
        session,
        analysis_id=analysis_id,
        user_id=user.id,
    )
    if analysis is None:
        raise _app_not_found()

    if analysis.status in {
        AnalysisStatus.QUEUED,
        AnalysisStatus.PROCESSING,
        AnalysisStatus.COMPLETED,
    }:
        return _submit_response(analysis)
    if analysis.status != AnalysisStatus.AWAITING_UPLOAD:
        raise AppError(
            "INVALID_ANALYSIS_STATE",
            f"An analysis in status '{analysis.status.value}' cannot be submitted",
            status_code=status.HTTP_409_CONFLICT,
        )

    try:
        uploaded = await storage.head_object(analysis.object_key)
    except StorageObjectNotFound as exc:
        raise AppError(
            "UPLOAD_NOT_FOUND",
            "The media has not finished uploading",
            status_code=status.HTTP_409_CONFLICT,
            retryable=True,
        ) from exc
    except StorageError as exc:
        raise AppError(
            "STORAGE_UNAVAILABLE",
            "Could not verify the private video upload",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            retryable=True,
        ) from exc

    maximum_bytes = (
        storage.settings.max_video_bytes
        if analysis.mode == AnalysisMode.VIDEO_COACH
        else storage.settings.max_image_bytes
    )
    if uploaded.size_bytes > maximum_bytes:
        raise AppError(
            "MEDIA_TOO_LARGE",
            "The uploaded media exceeds this mode's size limit",
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        )
    if uploaded.size_bytes <= 0 or uploaded.size_bytes != analysis.declared_size_bytes:
        raise AppError(
            "UPLOAD_SIZE_MISMATCH",
            "The uploaded media size does not match the declared size",
            status_code=status.HTTP_409_CONFLICT,
        )
    content_type = (uploaded.content_type or "").strip().lower()
    if content_type != analysis.mime_type:
        raise AppError(
            "UPLOAD_TYPE_MISMATCH",
            "The uploaded media content type does not match the request",
            status_code=status.HTTP_409_CONFLICT,
        )

    try:
        queued = await repository.queue_analysis(
            session,
            analysis_id=analysis.id,
            user_id=user.id,
            actual_size_bytes=uploaded.size_bytes,
        )
    except repository.AnalysisNotFoundError as exc:
        raise _app_not_found() from exc
    except repository.InvalidAnalysisTransitionError as exc:
        raise AppError(
            "INVALID_ANALYSIS_STATE",
            "The analysis can no longer be submitted",
            status_code=status.HTTP_409_CONFLICT,
        ) from exc
    except IntegrityError as exc:
        raise AppError(
            "ANALYSIS_LIMIT_REACHED",
            "Finish the current analysis before submitting another video",
            status_code=status.HTTP_409_CONFLICT,
            retryable=True,
        ) from exc
    return _submit_response(queued)


@router.get("/{analysis_id}", response_model=AnalysisStatusResponse)
async def get_analysis(
    analysis_id: UUID,
    user: UserDep,
    session: SessionDep,
) -> AnalysisStatusResponse:
    analysis = await repository.get_analysis(
        session,
        analysis_id=analysis_id,
        user_id=user.id,
    )
    if analysis is None:
        raise _app_not_found()
    return _status_response(analysis)


@router.get("", response_model=AnalysisListResponse)
async def list_analyses(
    user: UserDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = 20,
    cursor: Annotated[str | None, Query(min_length=1, max_length=512)] = None,
) -> AnalysisListResponse:
    before_created_at: datetime | None = None
    before_id: UUID | None = None
    if cursor is not None:
        before_created_at, before_id = _decode_cursor(cursor)

    rows = await repository.list_analyses(
        session,
        user_id=user.id,
        limit=limit + 1,
        before_created_at=before_created_at,
        before_id=before_id,
    )
    visible = rows[:limit]
    next_cursor = _encode_cursor(visible[-1]) if len(rows) > limit and visible else None
    return AnalysisListResponse(
        analyses=[
            AnalysisListItem(
                analysis_id=row.id,
                mode=row.mode.value,
                vocal_preference=row.vocal_preference.value,
                status=row.status.value,
                stage=row.stage.value,
                score=row.score,
                niche_detected=_niche_detected(row),
                created_at=row.created_at,
            )
            for row in visible
        ],
        next_cursor=next_cursor,
    )


@router.post(
    "/{analysis_id}/retry",
    response_model=AnalysisSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_analysis(
    analysis_id: UUID,
    user: UserDep,
    session: SessionDep,
) -> AnalysisSubmitResponse:
    try:
        analysis = await repository.retry_analysis(
            session,
            analysis_id=analysis_id,
            user_id=user.id,
        )
    except IntegrityError as exc:
        raise AppError(
            "ANALYSIS_LIMIT_REACHED",
            "Finish the current analysis before retrying this video",
            status_code=status.HTTP_409_CONFLICT,
            retryable=True,
        ) from exc
    except repository.AnalysisNotFoundError as exc:
        raise _app_not_found() from exc
    except repository.InvalidAnalysisTransitionError as exc:
        raise AppError(
            "ANALYSIS_NOT_RETRYABLE",
            "The analysis is not retryable or has reached its retry limit",
            status_code=status.HTTP_409_CONFLICT,
        ) from exc
    return _submit_response(analysis)


@router.post(
    "/{analysis_id}/cancel",
    response_model=AnalysisCancelResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_analysis(
    analysis_id: UUID,
    user: UserDep,
    session: SessionDep,
) -> AnalysisCancelResponse:
    """Cancel queued/processing work and durably schedule source cleanup."""

    try:
        analysis = await repository.cancel_analysis(
            session,
            analysis_id=analysis_id,
            user_id=user.id,
        )
    except repository.AnalysisNotFoundError as exc:
        raise _app_not_found() from exc
    except repository.InvalidAnalysisTransitionError as exc:
        raise AppError(
            "ANALYSIS_NOT_CANCELLABLE",
            "Only queued or processing analyses can be cancelled",
            status_code=status.HTTP_409_CONFLICT,
        ) from exc
    return AnalysisCancelResponse(
        analysis_id=analysis.id,
        mode=analysis.mode.value,
        vocal_preference=analysis.vocal_preference.value,
        status="cancelled",
        stage="cancelled",
    )


@router.delete("/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_analysis(
    analysis_id: UUID,
    user: UserDep,
    session: SessionDep,
) -> Response:
    """Delete a non-busy row after durably enqueueing its private source key."""

    deleted = await _delete_if_deletable(
        session,
        analysis_id=analysis_id,
        user_id=user.id,
    )
    if deleted is None:
        existing = await repository.get_analysis(
            session,
            analysis_id=analysis_id,
            user_id=user.id,
        )
        if existing is None:
            raise _app_not_found()
        raise AppError(
            "ANALYSIS_BUSY",
            "Queued or processing analyses cannot be deleted",
            status_code=status.HTTP_409_CONFLICT,
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
