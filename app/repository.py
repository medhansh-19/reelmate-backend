"""Transaction-scoped persistence and job-state operations.

Every user-facing query includes ``user_id`` even though Supabase RLS is also
enabled.  This is intentional defense in depth for backend connections that use
a role capable of bypassing RLS.  Functions never commit; the API or worker owns
the surrounding transaction.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import (
    Analysis,
    AnalysisMode,
    AnalysisStage,
    AnalysisStatus,
    MusicPreference,
    SourceDeletionJob,
    SourceDeletionReason,
    StoryVocalPreference,
    UserProfile,
)

MAX_PAGE_SIZE = 100
MAX_VIDEO_BYTES = 100_000_000
MAX_IMAGE_BYTES = 15_000_000
DEFAULT_UPLOAD_WINDOW = timedelta(minutes=15)
DEFAULT_LEASE_SECONDS = 300
DEFAULT_MAX_WORKER_ATTEMPTS = 3
SOURCE_DELETION_LEASE_SECONDS = 600
SOURCE_DELETION_MAX_BACKOFF_SECONDS = 3_600


class AnalysisRepositoryError(RuntimeError):
    """Base class for stable repository failures."""


class AnalysisNotFoundError(AnalysisRepositoryError):
    pass


class InvalidAnalysisTransitionError(AnalysisRepositoryError):
    pass


class WorkerLeaseError(AnalysisRepositoryError):
    pass


@dataclass(frozen=True, slots=True)
class AnalysisCompletion:
    """All values required to make a processing row immutable and complete."""

    score: int
    hook_score: int | None
    pacing_score: int | None
    av_sync_score: int | None
    text_score: int | None
    result_json: Mapping[str, Any]
    metrics_json: Mapping[str, Any]
    pipeline_version: str
    score_version: str
    prompt_version: str
    model_id: str
    trend_score: int | None = None
    confidence: Decimal | float | None = None
    schema_version: str = "1"
    model_input_tokens: int = 0
    model_output_tokens: int = 0
    estimated_model_cost_usd: Decimal | float | str | None = Decimal("0")
    estimated_total_cost_usd: Decimal | float | str | None = None
    duration_seconds: Decimal | float | None = None


@dataclass(frozen=True, slots=True)
class ProfileUpdate:
    niche: str | None = None
    niche_confidence: Decimal | float | None = None
    editing_style: str | None = None
    editing_style_confidence: Decimal | float | None = None
    typical_energy: str | None = None
    typical_energy_confidence: Decimal | float | None = None
    recurring_issue_codes: Sequence[str] = ()
    profile_version: str = "1"


_SECRET_PATTERNS = (
    re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(?:sk|key|token|secret)[-_][a-z0-9_-]{12,}\b"),
    re.compile(r"(?i)(?:postgres(?:ql)?|https?)://[^\s/@:]+:[^\s/@]+@"),
)


def sanitize_failure_detail(detail: str | None, *, max_length: int = 1_000) -> str | None:
    """Store a useful failure summary without obvious credentials or log spam."""

    if detail is None:
        return None
    value = " ".join(str(detail).split())
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub("[REDACTED]", value)
    if len(value) > max_length:
        value = f"{value[: max_length - 1]}…"
    return value


def _coerce_stage(stage: AnalysisStage | str) -> AnalysisStage:
    try:
        return stage if isinstance(stage, AnalysisStage) else AnalysisStage(stage)
    except ValueError as exc:
        raise InvalidAnalysisTransitionError(f"Unknown analysis stage: {stage}") from exc


def _validate_score(value: int | None, name: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
        raise ValueError(f"{name} must be an integer between 0 and 100")


def _validate_completion(completion: AnalysisCompletion) -> None:
    _validate_score(completion.score, "score")
    if not 5 <= completion.score <= 95:
        raise ValueError("score must be an integer between 5 and 95")
    for field_name in ("hook_score", "pacing_score", "text_score"):
        _validate_score(getattr(completion, field_name), field_name, nullable=True)
    _validate_score(completion.av_sync_score, "av_sync_score", nullable=True)
    _validate_score(completion.trend_score, "trend_score", nullable=True)

    if completion.confidence is not None and not 0 <= Decimal(str(completion.confidence)) <= 1:
        raise ValueError("confidence must be between 0 and 1")

    required_versions = (
        completion.schema_version,
        completion.pipeline_version,
        completion.score_version,
        completion.prompt_version,
        completion.model_id,
    )
    if any(not value or not str(value).strip() for value in required_versions):
        raise ValueError("Completed analyses require every schema/pipeline/model version")
    if completion.model_input_tokens < 0 or completion.model_output_tokens < 0:
        raise ValueError("Model token usage cannot be negative")
    if (
        completion.estimated_total_cost_usd is not None
        and completion.estimated_model_cost_usd is None
    ):
        raise ValueError("Total cost cannot be known when model cost is unknown")
    if completion.estimated_model_cost_usd is not None:
        model_cost = Decimal(str(completion.estimated_model_cost_usd))
        if model_cost < 0:
            raise ValueError("Model cost cannot be negative")
    if completion.estimated_total_cost_usd is not None:
        total_cost = Decimal(str(completion.estimated_total_cost_usd))
        if total_cost < 0:
            raise ValueError("Total cost cannot be negative")
        if completion.estimated_model_cost_usd is not None and total_cost < Decimal(
            str(completion.estimated_model_cost_usd)
        ):
            raise ValueError("Total cost cannot be lower than model cost")


async def _database_now(session: AsyncSession) -> datetime:
    value = await session.scalar(select(func.now()))
    return value if value is not None else datetime.now(UTC)


async def create_analysis(
    session: AsyncSession,
    *,
    user_id: UUID,
    idempotency_key: str,
    object_key: str,
    declared_size_bytes: int,
    mime_type: str,
    mode: AnalysisMode = AnalysisMode.VIDEO_COACH,
    vocal_preference: StoryVocalPreference = StoryVocalPreference.ANY,
    analysis_id: UUID | None = None,
    upload_expires_at: datetime | None = None,
    upload_window_seconds: int | None = None,
) -> Analysis:
    """Create once per ``(user_id, idempotency_key)`` and return that row.

    The conflict target is deliberately limited to the idempotency constraint;
    an accidentally reused object key remains a hard database error.
    """

    idempotency_key = idempotency_key.strip()
    object_key = object_key.strip()
    mime_type = mime_type.lower().strip()
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("idempotency_key must contain 1-255 characters")
    if not object_key:
        raise ValueError("object_key is required")
    allowed_types = (
        {"video/mp4", "video/quicktime"}
        if mode == AnalysisMode.VIDEO_COACH
        else {"image/jpeg", "image/png", "image/webp"}
    )
    if mime_type not in allowed_types:
        raise ValueError("mime_type does not match the selected analysis mode")
    maximum_bytes = MAX_VIDEO_BYTES if mode == AnalysisMode.VIDEO_COACH else MAX_IMAGE_BYTES
    if not 0 < declared_size_bytes <= maximum_bytes:
        raise ValueError(f"declared_size_bytes must be between 1 byte and {maximum_bytes} bytes")
    if upload_window_seconds is not None and not 60 <= upload_window_seconds <= 900:
        raise ValueError("upload_window_seconds must be between 60 and 900")
    if upload_expires_at is not None and upload_window_seconds is not None:
        raise ValueError("Supply upload_expires_at or upload_window_seconds, not both")
    if mode == AnalysisMode.VIDEO_COACH and vocal_preference != StoryVocalPreference.ANY:
        raise ValueError("vocal_preference is only available for story_song analyses")

    now = await _database_now(session)
    expiry = upload_expires_at or now + (
        timedelta(seconds=upload_window_seconds)
        if upload_window_seconds is not None
        else DEFAULT_UPLOAD_WINDOW
    )
    statement = (
        pg_insert(Analysis)
        .values(
            id=analysis_id or uuid4(),
            user_id=user_id,
            idempotency_key=idempotency_key,
            object_key=object_key,
            mode=mode,
            vocal_preference=vocal_preference,
            declared_size_bytes=declared_size_bytes,
            mime_type=mime_type,
            status=AnalysisStatus.AWAITING_UPLOAD,
            stage=AnalysisStage.AWAITING_UPLOAD,
            upload_expires_at=expiry,
        )
        .on_conflict_do_nothing(constraint="uq_analyses_user_idempotency")
        .returning(Analysis)
    )
    analysis = (await session.execute(statement)).scalar_one_or_none()
    if analysis is not None:
        return analysis

    # A concurrent request already inserted the same logical operation.
    existing = await session.scalar(
        select(Analysis).where(
            Analysis.user_id == user_id,
            Analysis.idempotency_key == idempotency_key,
        )
    )
    if existing is None:  # Defensive: this should be impossible in one transaction.
        raise AnalysisRepositoryError("Idempotent create conflict could not be resolved")
    return existing


async def get_music_preference(
    session: AsyncSession,
    *,
    user_id: UUID,
) -> MusicPreference | None:
    return cast(
        MusicPreference | None,
        await session.scalar(select(MusicPreference).where(MusicPreference.user_id == user_id)),
    )


async def upsert_music_preference(
    session: AsyncSession,
    *,
    user_id: UUID,
    preferred_languages: Sequence[str],
    preferred_moods: Sequence[str],
    favorite_artists: Sequence[str],
    favorite_tracks: Sequence[str],
    default_vocal_preference: StoryVocalPreference,
    complete_onboarding: bool = False,
) -> MusicPreference:
    """Replace explicit settings and optionally complete onboarding once."""

    now = await _database_now(session)
    values: dict[str, Any] = {
        "user_id": user_id,
        "preferred_languages": list(preferred_languages),
        "preferred_moods": list(preferred_moods),
        "favorite_artists": list(favorite_artists),
        "favorite_tracks": list(favorite_tracks),
        "default_vocal_preference": default_vocal_preference,
        "profile_version": "1",
        "revision": 1,
        "onboarding_completed_at": now if complete_onboarding else None,
        "updated_at": now,
    }
    excluded = pg_insert(MusicPreference).excluded
    update_values: dict[str, Any] = {
        "preferred_languages": excluded.preferred_languages,
        "preferred_moods": excluded.preferred_moods,
        "favorite_artists": excluded.favorite_artists,
        "favorite_tracks": excluded.favorite_tracks,
        "default_vocal_preference": excluded.default_vocal_preference,
        "profile_version": excluded.profile_version,
        "revision": MusicPreference.revision + 1,
        "updated_at": now,
    }
    if complete_onboarding:
        update_values["onboarding_completed_at"] = func.coalesce(
            MusicPreference.onboarding_completed_at,
            excluded.onboarding_completed_at,
        )
    statement = (
        pg_insert(MusicPreference)
        .values(**values)
        .on_conflict_do_update(
            index_elements=[MusicPreference.user_id],
            set_=update_values,
        )
        .returning(MusicPreference)
    )
    return (await session.execute(statement)).scalar_one()


async def get_analysis(
    session: AsyncSession,
    *,
    analysis_id: UUID,
    user_id: UUID,
) -> Analysis | None:
    return cast(
        Analysis | None,
        await session.scalar(
            select(Analysis).where(Analysis.id == analysis_id, Analysis.user_id == user_id)
        ),
    )


async def get_analysis_or_raise(
    session: AsyncSession,
    *,
    analysis_id: UUID,
    user_id: UUID,
) -> Analysis:
    analysis = await get_analysis(session, analysis_id=analysis_id, user_id=user_id)
    if analysis is None:
        raise AnalysisNotFoundError("Analysis was not found")
    return analysis


async def list_analyses(
    session: AsyncSession,
    *,
    user_id: UUID,
    limit: int = 20,
    before_created_at: datetime | None = None,
    before_id: UUID | None = None,
    statuses: Sequence[AnalysisStatus] | None = None,
    modes: Sequence[AnalysisMode] | None = None,
) -> list[Analysis]:
    """Return newest-first history using a stable ``(created_at, id)`` cursor."""

    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
    if (before_created_at is None) != (before_id is None):
        raise ValueError("before_created_at and before_id must be supplied together")

    statement = select(Analysis).where(Analysis.user_id == user_id)
    if before_created_at is not None and before_id is not None:
        statement = statement.where(
            or_(
                Analysis.created_at < before_created_at,
                and_(
                    Analysis.created_at == before_created_at,
                    Analysis.id < before_id,
                ),
            )
        )
    if statuses:
        statement = statement.where(Analysis.status.in_(statuses))
    if modes:
        statement = statement.where(Analysis.mode.in_(modes))
    statement = statement.order_by(Analysis.created_at.desc(), Analysis.id.desc()).limit(limit)
    return list((await session.scalars(statement)).all())


def _source_delete_available_at(analysis: Analysis, now: datetime) -> datetime:
    """Do not delete while an already-issued presigned PUT may recreate the object."""

    upload_expiry = analysis.upload_expires_at
    if upload_expiry.tzinfo is None:
        upload_expiry = upload_expiry.replace(tzinfo=UTC)
    return max(now, upload_expiry)


async def enqueue_source_deletion(
    session: AsyncSession,
    *,
    analysis: Analysis,
    reason: SourceDeletionReason | str,
    available_at: datetime | None = None,
    database_now: datetime | None = None,
) -> None:
    """Insert idempotent R2 deletion work in the caller's state transaction."""

    if analysis.source_deleted_at is not None:
        return
    normalized_reason = reason.value if isinstance(reason, SourceDeletionReason) else reason.strip()
    if not normalized_reason or len(normalized_reason) > 64:
        raise ValueError("source deletion reason must contain 1-64 characters")
    now = database_now or await _database_now(session)
    due_at = available_at or _source_delete_available_at(analysis, now)
    excluded = pg_insert(SourceDeletionJob).excluded
    statement = (
        pg_insert(SourceDeletionJob)
        .values(
            analysis_id=analysis.id,
            object_key=analysis.object_key,
            reason=normalized_reason,
            available_at=due_at,
            updated_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_source_deletion_outbox_object_key",
            set_={
                "analysis_id": excluded.analysis_id,
                "reason": excluded.reason,
                "available_at": func.least(SourceDeletionJob.available_at, excluded.available_at),
                "updated_at": now,
            },
        )
    )
    await session.execute(statement)


async def delete_analysis(
    session: AsyncSession,
    *,
    analysis_id: UUID,
    user_id: UUID,
    allowed_statuses: Sequence[AnalysisStatus] | None = None,
) -> Analysis | None:
    """Delete an owned row only after its R2 key is durably queued for cleanup."""

    statement = select(Analysis).where(
        Analysis.id == analysis_id,
        Analysis.user_id == user_id,
    )
    if allowed_statuses is not None:
        statement = statement.where(Analysis.status.in_(allowed_statuses))
    analysis = await session.scalar(statement.with_for_update())
    if analysis is None:
        return None
    await enqueue_source_deletion(
        session,
        analysis=analysis,
        reason=SourceDeletionReason.ANALYSIS_DELETED,
    )
    await session.delete(analysis)
    await session.flush()
    return analysis


async def cancel_analysis(
    session: AsyncSession,
    *,
    analysis_id: UUID,
    user_id: UUID,
) -> Analysis:
    """Cancel queued/processing work and revoke its worker lease atomically."""

    analysis = await session.scalar(
        select(Analysis)
        .where(Analysis.id == analysis_id, Analysis.user_id == user_id)
        .with_for_update()
    )
    if analysis is None:
        raise AnalysisNotFoundError("Analysis was not found")
    if analysis.status == AnalysisStatus.CANCELLED:
        return analysis
    if analysis.status not in {AnalysisStatus.QUEUED, AnalysisStatus.PROCESSING}:
        raise InvalidAnalysisTransitionError(
            f"Cannot cancel an analysis in status {analysis.status.value}"
        )

    now = await _database_now(session)
    analysis.status = AnalysisStatus.CANCELLED
    analysis.stage = AnalysisStage.CANCELLED
    analysis.cancelled_at = now
    analysis.failure_retryable = False
    analysis.worker_lease_owner = None
    analysis.worker_lease_expires_at = None
    analysis.updated_at = now
    await enqueue_source_deletion(
        session,
        analysis=analysis,
        reason=SourceDeletionReason.CANCELLED,
        database_now=now,
    )
    await session.flush()
    return analysis


async def queue_analysis(
    session: AsyncSession,
    *,
    analysis_id: UUID,
    user_id: UUID,
    actual_size_bytes: int,
    duration_seconds: Decimal | float | None = None,
    content_sha256: str | None = None,
) -> Analysis:
    """Atomically submit an uploaded analysis; repeated submits are harmless."""

    if not 0 < actual_size_bytes <= MAX_VIDEO_BYTES:
        raise ValueError("actual_size_bytes must be between 1 byte and 100 MB")
    duration = None if duration_seconds is None else Decimal(str(duration_seconds))
    if duration is not None and not Decimal("0") < duration <= Decimal("90"):
        raise ValueError("duration_seconds must be greater than 0 and at most 90")
    if content_sha256 is not None:
        content_sha256 = content_sha256.lower().strip()
        if not re.fullmatch(r"[0-9a-f]{64}", content_sha256):
            raise ValueError("content_sha256 must be a 64-character hexadecimal digest")

    now = await _database_now(session)
    statement = (
        update(Analysis)
        .where(
            Analysis.id == analysis_id,
            Analysis.user_id == user_id,
            Analysis.status == AnalysisStatus.AWAITING_UPLOAD,
            Analysis.upload_expires_at > now,
        )
        .values(
            status=AnalysisStatus.QUEUED,
            stage=AnalysisStage.QUEUED,
            actual_size_bytes=actual_size_bytes,
            duration_seconds=duration,
            content_sha256=content_sha256,
            queued_at=now,
            updated_at=now,
        )
        .returning(Analysis)
    )
    queued = (await session.execute(statement)).scalar_one_or_none()
    if queued is not None:
        return queued

    existing = await get_analysis_or_raise(session, analysis_id=analysis_id, user_id=user_id)
    if existing.status in {
        AnalysisStatus.QUEUED,
        AnalysisStatus.PROCESSING,
        AnalysisStatus.COMPLETED,
    }:
        # Submission is an idempotent operation. Do not overwrite its first
        # verified metadata on a replay.
        return existing
    raise InvalidAnalysisTransitionError(
        "Upload window expired"
        if existing.status == AnalysisStatus.AWAITING_UPLOAD and existing.upload_expires_at <= now
        else f"Cannot queue an analysis in status {existing.status.value}"
    )


async def retry_analysis(
    session: AsyncSession,
    *,
    analysis_id: UUID,
    user_id: UUID,
    max_retries: int = 2,
) -> Analysis:
    """Requeue an explicitly retryable failed job with a bounded retry count."""

    if max_retries < 1:
        raise ValueError("max_retries must be at least 1")
    now = await _database_now(session)
    statement = (
        update(Analysis)
        .where(
            Analysis.id == analysis_id,
            Analysis.user_id == user_id,
            Analysis.status == AnalysisStatus.FAILED,
            Analysis.failure_retryable.is_(True),
            Analysis.retry_count < max_retries,
        )
        .values(
            status=AnalysisStatus.QUEUED,
            stage=AnalysisStage.QUEUED,
            failure_code=None,
            failure_detail=None,
            failure_retryable=False,
            retry_count=Analysis.retry_count + 1,
            queued_at=now,
            started_at=None,
            failed_at=None,
            worker_lease_owner=None,
            worker_lease_expires_at=None,
            updated_at=now,
        )
        .returning(Analysis)
    )
    retried = (await session.execute(statement)).scalar_one_or_none()
    if retried is not None:
        return retried

    existing = await get_analysis_or_raise(session, analysis_id=analysis_id, user_id=user_id)
    raise InvalidAnalysisTransitionError(
        "Analysis is not retryable or has reached the retry limit "
        f"(status={existing.status.value}, retry_count={existing.retry_count})"
    )


async def expire_stale_sources(
    session: AsyncSession,
    *,
    retention_hours: int,
    limit: int = 50,
) -> list[Analysis]:
    """Close abandoned upload/retry windows and return sources for R2 cleanup."""

    if not 1 <= retention_hours <= 168:
        raise ValueError("retention_hours must be between 1 and 168")
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")

    now = await _database_now(session)
    retry_cutoff = now - timedelta(hours=retention_hours)
    statement = (
        select(Analysis)
        .where(
            or_(
                and_(
                    Analysis.status == AnalysisStatus.AWAITING_UPLOAD,
                    Analysis.upload_expires_at <= now,
                ),
                and_(
                    Analysis.status == AnalysisStatus.FAILED,
                    Analysis.failure_retryable.is_(True),
                    Analysis.failed_at <= retry_cutoff,
                ),
            )
        )
        .order_by(Analysis.updated_at.asc(), Analysis.id.asc())
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    analyses = list((await session.scalars(statement)).all())
    for analysis in analyses:
        if analysis.status == AnalysisStatus.AWAITING_UPLOAD:
            deletion_reason = SourceDeletionReason.UPLOAD_EXPIRED
            analysis.status = AnalysisStatus.EXPIRED
            analysis.stage = AnalysisStage.EXPIRED
        else:
            deletion_reason = SourceDeletionReason.RETRY_EXPIRED
            analysis.failure_retryable = False
            analysis.failure_detail = "The source-video retry window expired."
        analysis.updated_at = now
        await enqueue_source_deletion(
            session,
            analysis=analysis,
            reason=deletion_reason,
            available_at=now,
            database_now=now,
        )
    await session.flush()
    return analyses


async def claim_next_analysis(
    session: AsyncSession,
    *,
    worker_id: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    max_worker_attempts: int = DEFAULT_MAX_WORKER_ATTEMPTS,
) -> Analysis | None:
    """Claim one queued/stale job using ``FOR UPDATE SKIP LOCKED``.

    The transaction must be committed before expensive media processing begins;
    the durable lease, rather than the row lock, then owns the job.
    """

    worker_id = worker_id.strip()
    if not worker_id or len(worker_id) > 255:
        raise ValueError("worker_id must contain 1-255 characters")
    if not 1 <= lease_seconds <= 3_600:
        raise ValueError("lease_seconds must be between 1 and 3600")
    if not 1 <= max_worker_attempts <= 10:
        raise ValueError("max_worker_attempts must be between 1 and 10")

    now = await _database_now(session)
    claimable = or_(
        Analysis.status == AnalysisStatus.QUEUED,
        and_(
            Analysis.status == AnalysisStatus.PROCESSING,
            Analysis.worker_lease_expires_at <= now,
        ),
    )
    exhausted = await session.scalar(
        select(Analysis)
        .where(claimable, Analysis.worker_attempt_count >= max_worker_attempts)
        .order_by(Analysis.queued_at.asc().nullslast(), Analysis.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if exhausted is not None:
        exhausted.status = AnalysisStatus.FAILED
        exhausted.stage = AnalysisStage.FAILED
        exhausted.failure_code = "WORKER_ATTEMPT_LIMIT_REACHED"
        exhausted.failure_detail = "The worker retry safety limit was reached."
        exhausted.failure_retryable = False
        exhausted.failed_at = now
        exhausted.worker_lease_owner = None
        exhausted.worker_lease_expires_at = None
        exhausted.updated_at = now
        await enqueue_source_deletion(
            session,
            analysis=exhausted,
            reason=SourceDeletionReason.ATTEMPTS_EXHAUSTED,
            database_now=now,
        )

    statement = (
        select(Analysis)
        .where(
            claimable,
            Analysis.worker_attempt_count < max_worker_attempts,
        )
        .order_by(Analysis.queued_at.asc().nullslast(), Analysis.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    analysis = await session.scalar(statement)
    if analysis is None:
        return None

    analysis.status = AnalysisStatus.PROCESSING
    # A reclaimed job restarts because temporary local artifacts may have been
    # lost with the former worker.
    analysis.stage = AnalysisStage.VALIDATING
    analysis.started_at = analysis.started_at or now
    analysis.worker_lease_owner = worker_id
    analysis.worker_lease_expires_at = now + timedelta(seconds=lease_seconds)
    analysis.worker_attempt_count += 1
    analysis.updated_at = now
    await session.flush()
    return analysis


_PROCESSING_STAGE_ORDER = {
    AnalysisStage.VALIDATING: 0,
    AnalysisStage.EXTRACTING: 1,
    AnalysisStage.SCORING: 2,
    AnalysisStage.GENERATING_FEEDBACK: 3,
}


async def _locked_worker_analysis(
    session: AsyncSession,
    *,
    analysis_id: UUID,
    worker_id: str,
    now: datetime,
) -> Analysis:
    analysis = await session.scalar(
        select(Analysis).where(Analysis.id == analysis_id).with_for_update()
    )
    if analysis is None:
        raise AnalysisNotFoundError("Analysis was not found")
    if analysis.status != AnalysisStatus.PROCESSING:
        raise WorkerLeaseError(f"Worker lease is no longer active (status={analysis.status.value})")
    if (
        analysis.worker_lease_owner != worker_id
        or analysis.worker_lease_expires_at is None
        or analysis.worker_lease_expires_at <= now
    ):
        raise WorkerLeaseError("Worker does not hold a live lease for this analysis")
    return analysis


async def update_analysis_stage(
    session: AsyncSession,
    *,
    analysis_id: UUID,
    worker_id: str,
    stage: AnalysisStage | str,
    metrics_json: Mapping[str, Any] | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> Analysis:
    """Advance progress and heartbeat the claiming worker's lease."""

    next_stage = _coerce_stage(stage)
    if next_stage not in _PROCESSING_STAGE_ORDER:
        raise InvalidAnalysisTransitionError(
            f"{next_stage.value} is not an active processing stage"
        )
    if not 1 <= lease_seconds <= 3_600:
        raise ValueError("lease_seconds must be between 1 and 3600")

    now = await _database_now(session)
    analysis = await _locked_worker_analysis(
        session,
        analysis_id=analysis_id,
        worker_id=worker_id,
        now=now,
    )
    current_order = _PROCESSING_STAGE_ORDER.get(analysis.stage)
    if current_order is None or _PROCESSING_STAGE_ORDER[next_stage] < current_order:
        raise InvalidAnalysisTransitionError(
            f"Cannot move stage backward from {analysis.stage.value} to {next_stage.value}"
        )

    analysis.stage = next_stage
    if metrics_json is not None:
        analysis.metrics_json = dict(metrics_json)
    analysis.worker_lease_expires_at = now + timedelta(seconds=lease_seconds)
    analysis.updated_at = now
    await session.flush()
    return analysis


async def renew_analysis_lease(
    session: AsyncSession,
    *,
    analysis_id: UUID,
    worker_id: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> Analysis:
    """Heartbeat long-running extraction without changing the visible stage."""

    if not 1 <= lease_seconds <= 3_600:
        raise ValueError("lease_seconds must be between 1 and 3600")
    now = await _database_now(session)
    analysis = await _locked_worker_analysis(
        session,
        analysis_id=analysis_id,
        worker_id=worker_id,
        now=now,
    )
    analysis.worker_lease_expires_at = now + timedelta(seconds=lease_seconds)
    analysis.updated_at = now
    await session.flush()
    return analysis


async def complete_analysis(
    session: AsyncSession,
    *,
    analysis_id: UUID,
    worker_id: str,
    completion: AnalysisCompletion,
) -> Analysis:
    """Persist deterministic scores, structured coaching, versions and cost."""

    _validate_completion(completion)
    now = await _database_now(session)
    analysis = await _locked_worker_analysis(
        session,
        analysis_id=analysis_id,
        worker_id=worker_id,
        now=now,
    )

    analysis.score = completion.score
    analysis.hook_score = completion.hook_score
    analysis.pacing_score = completion.pacing_score
    analysis.av_sync_score = completion.av_sync_score
    analysis.text_score = completion.text_score
    analysis.trend_score = completion.trend_score
    analysis.confidence = (
        None if completion.confidence is None else Decimal(str(completion.confidence))
    )
    analysis.result_json = dict(completion.result_json)
    analysis.metrics_json = dict(completion.metrics_json)
    analysis.schema_version = completion.schema_version
    analysis.pipeline_version = completion.pipeline_version
    analysis.score_version = completion.score_version
    analysis.prompt_version = completion.prompt_version
    analysis.model_id = completion.model_id
    analysis.model_input_tokens = completion.model_input_tokens
    analysis.model_output_tokens = completion.model_output_tokens
    analysis.estimated_model_cost_usd = (
        None
        if completion.estimated_model_cost_usd is None
        else Decimal(str(completion.estimated_model_cost_usd))
    )
    analysis.estimated_total_cost_usd = (
        None
        if completion.estimated_total_cost_usd is None
        else Decimal(str(completion.estimated_total_cost_usd))
    )
    if completion.duration_seconds is not None:
        duration = Decimal(str(completion.duration_seconds))
        if not Decimal("0") < duration <= Decimal("90"):
            raise ValueError("duration_seconds must be greater than 0 and at most 90")
        analysis.duration_seconds = duration

    analysis.status = AnalysisStatus.COMPLETED
    analysis.stage = AnalysisStage.COMPLETED
    analysis.completed_at = now
    analysis.worker_lease_owner = None
    analysis.worker_lease_expires_at = None
    analysis.updated_at = now

    # The creator baseline is derived only from video coaching history. Keep its
    # counter aligned by excluding image-to-song jobs.
    if analysis.mode == AnalysisMode.VIDEO_COACH:
        await session.execute(
            pg_insert(UserProfile)
            .values(user_id=analysis.user_id, submission_count=1, last_updated=now)
            .on_conflict_do_update(
                index_elements=[UserProfile.user_id],
                set_={
                    "submission_count": UserProfile.submission_count + 1,
                    "last_updated": now,
                },
            )
        )
    await enqueue_source_deletion(
        session,
        analysis=analysis,
        reason=SourceDeletionReason.COMPLETED,
        database_now=now,
    )
    await session.flush()
    return analysis


async def fail_analysis(
    session: AsyncSession,
    *,
    analysis_id: UUID,
    failure_code: str,
    failure_detail: str | None,
    retryable: bool,
    worker_id: str | None = None,
    user_id: UUID | None = None,
    delete_source: bool = False,
) -> Analysis:
    """Fail a worker-owned job or an owned pre-processing submission.

    Supplying neither ownership scope is rejected so an accidental call cannot
    fail another user's job through a privileged backend connection.
    """

    failure_code = failure_code.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", failure_code):
        raise ValueError("failure_code must be a stable uppercase code")
    if (worker_id is None) == (user_id is None):
        raise ValueError("Supply exactly one of worker_id or user_id")

    now = await _database_now(session)
    if worker_id is not None:
        analysis = await _locked_worker_analysis(
            session,
            analysis_id=analysis_id,
            worker_id=worker_id,
            now=now,
        )
    else:
        owned_analysis = cast(
            Analysis | None,
            await session.scalar(
                select(Analysis)
                .where(Analysis.id == analysis_id, Analysis.user_id == user_id)
                .with_for_update()
            ),
        )
        if owned_analysis is None:
            raise AnalysisNotFoundError("Analysis was not found")
        if owned_analysis.status not in {
            AnalysisStatus.AWAITING_UPLOAD,
            AnalysisStatus.QUEUED,
        }:
            raise InvalidAnalysisTransitionError(
                f"Cannot fail an analysis in status {owned_analysis.status.value}"
            )
        analysis = owned_analysis

    analysis.status = AnalysisStatus.FAILED
    analysis.stage = AnalysisStage.FAILED
    analysis.failure_code = failure_code
    analysis.failure_detail = sanitize_failure_detail(failure_detail)
    analysis.failure_retryable = retryable
    analysis.failed_at = now
    analysis.worker_lease_owner = None
    analysis.worker_lease_expires_at = None
    analysis.updated_at = now
    if delete_source:
        await enqueue_source_deletion(
            session,
            analysis=analysis,
            reason=SourceDeletionReason.INVALID_MEDIA,
            database_now=now,
        )
    await session.flush()
    return analysis


async def claim_source_deletions(
    session: AsyncSession,
    *,
    worker_id: str,
    limit: int = 10,
    lease_seconds: int = SOURCE_DELETION_LEASE_SECONDS,
) -> list[SourceDeletionJob]:
    """Lease due R2 deletion jobs without holding row locks during network I/O."""

    worker_id = worker_id.strip()
    if not worker_id or len(worker_id) > 255:
        raise ValueError("worker_id must contain 1-255 characters")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if not 30 <= lease_seconds <= 3_600:
        raise ValueError("lease_seconds must be between 30 and 3600")

    now = await _database_now(session)
    jobs = list(
        (
            await session.scalars(
                select(SourceDeletionJob)
                .where(
                    SourceDeletionJob.available_at <= now,
                    or_(
                        SourceDeletionJob.lease_expires_at.is_(None),
                        SourceDeletionJob.lease_expires_at <= now,
                    ),
                )
                .order_by(SourceDeletionJob.available_at.asc(), SourceDeletionJob.created_at.asc())
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
        ).all()
    )
    for job in jobs:
        job.lease_owner = worker_id
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        job.last_attempt_at = now
        job.updated_at = now
    await session.flush()
    return jobs


async def complete_source_deletion(
    session: AsyncSession,
    *,
    job_id: UUID,
    worker_id: str,
) -> bool:
    """Acknowledge an idempotent R2 delete and mark a retained analysis clean."""

    now = await _database_now(session)
    job = await session.scalar(
        select(SourceDeletionJob)
        .where(SourceDeletionJob.id == job_id, SourceDeletionJob.lease_owner == worker_id)
        .with_for_update()
    )
    if job is None:
        return False
    if job.analysis_id is not None:
        await session.execute(
            update(Analysis)
            .where(
                Analysis.id == job.analysis_id,
                Analysis.object_key == job.object_key,
            )
            .values(source_deleted_at=now, updated_at=now)
        )
    await session.delete(job)
    await session.flush()
    return True


async def reschedule_source_deletion(
    session: AsyncSession,
    *,
    job_id: UUID,
    worker_id: str,
    error_code: str = "STORAGE_DELETE_FAILED",
) -> bool:
    """Release a failed delete with bounded exponential backoff and no raw error."""

    normalized_error = error_code.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", normalized_error):
        normalized_error = "STORAGE_DELETE_FAILED"
    now = await _database_now(session)
    job = await session.scalar(
        select(SourceDeletionJob)
        .where(SourceDeletionJob.id == job_id, SourceDeletionJob.lease_owner == worker_id)
        .with_for_update()
    )
    if job is None:
        return False
    delay_seconds = min(
        SOURCE_DELETION_MAX_BACKOFF_SECONDS,
        30 * (2 ** min(job.attempt_count, 7)),
    )
    job.attempt_count += 1
    job.available_at = now + timedelta(seconds=delay_seconds)
    job.lease_owner = None
    job.lease_expires_at = None
    job.last_error_code = normalized_error
    job.updated_at = now
    await session.flush()
    return True


async def get_user_profile(
    session: AsyncSession,
    *,
    user_id: UUID,
) -> UserProfile | None:
    return await session.get(UserProfile, user_id)


async def upsert_user_profile(
    session: AsyncSession,
    *,
    user_id: UUID,
    profile: ProfileUpdate,
) -> UserProfile:
    """Update only structured passive-profile fields, never arbitrary model prose."""

    issue_codes = sorted(
        {
            code.strip().lower()
            for code in profile.recurring_issue_codes
            if re.fullmatch(r"[a-z][a-z0-9_]{1,63}", code.strip().lower())
        }
    )
    now = await _database_now(session)
    values = {
        "user_id": user_id,
        "niche": profile.niche,
        "niche_confidence": profile.niche_confidence,
        "editing_style": profile.editing_style,
        "editing_style_confidence": profile.editing_style_confidence,
        "typical_energy": profile.typical_energy,
        "typical_energy_confidence": profile.typical_energy_confidence,
        "recurring_issue_codes": issue_codes,
        "profile_version": profile.profile_version,
        "last_updated": now,
    }
    statement = (
        pg_insert(UserProfile)
        .values(**values)
        .on_conflict_do_update(
            index_elements=[UserProfile.user_id],
            set_={key: value for key, value in values.items() if key != "user_id"},
        )
        .returning(UserProfile)
    )
    return (await session.execute(statement)).scalar_one()
