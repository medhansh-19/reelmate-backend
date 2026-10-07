"""Durable ReelMate analysis worker.

The worker claims one PostgreSQL-backed job at a time, downloads its private
source object into an isolated temporary directory, runs local media analysis,
and persists only reduced metrics and structured coaching. Raw OCR text,
keyframe bytes, local paths, and source videos never enter PostgreSQL.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import tempfile
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Self
from uuid import UUID

from app.config import Settings, get_settings
from app.db import (
    Analysis,
    AnalysisMode,
    AnalysisStage,
    AnalysisStatus,
    Database,
    StoryVocalPreference,
)
from app.feedback import FeedbackResult, FeedbackService
from app.personalization import ProfileSnapshot, derive_profile
from app.pipeline import (
    MediaValidationError,
    PipelineDependencyError,
    PipelineError,
    PipelineV1,
)
from app.pipeline_runner import run_pipeline_isolated
from app.repository import (
    AnalysisCompletion,
    ProfileUpdate,
    WorkerLeaseError,
    claim_next_analysis,
    claim_source_deletions,
    complete_analysis,
    complete_source_deletion,
    expire_stale_sources,
    fail_analysis,
    get_music_preference,
    list_analyses,
    renew_analysis_lease,
    reschedule_source_deletion,
    update_analysis_stage,
    upsert_user_profile,
)
from app.scoring import ScoreResult, score_pipeline
from app.storage import (
    R2Storage,
    R2StorageSettings,
    StorageDependencyError,
    StorageError,
    StorageObjectNotFound,
)
from app.story_recommender import (
    STORY_PIPELINE_VERSION,
    STORY_RANKER_VERSION,
    StoryPipelineError,
    StoryRecommendationResult,
    StoryTasteProfile,
    analyze_story_image,
)

logger = logging.getLogger(__name__)


class WorkerConfigurationError(RuntimeError):
    """Raised before polling when a required project-owned service is absent."""


@dataclass(frozen=True, slots=True)
class ClaimedAnalysis:
    id: UUID
    user_id: UUID
    object_key: str
    mime_type: str
    declared_size_bytes: int
    actual_size_bytes: int | None
    mode: AnalysisMode
    vocal_preference: StoryVocalPreference

    @classmethod
    def from_model(cls, analysis: Analysis) -> Self:
        return cls(
            id=analysis.id,
            user_id=analysis.user_id,
            object_key=analysis.object_key,
            mime_type=analysis.mime_type,
            declared_size_bytes=analysis.declared_size_bytes,
            actual_size_bytes=analysis.actual_size_bytes,
            mode=analysis.mode,
            vocal_preference=analysis.vocal_preference,
        )


@dataclass(frozen=True, slots=True)
class FailureDisposition:
    code: str
    detail: str
    retryable: bool
    delete_source: bool = False


class _TemporaryWorkspace:
    """Explicit temp workspace whose path is never persisted or logged."""

    def __init__(self) -> None:
        self.path: Path | None = None

    def __enter__(self) -> Path:
        self.path = Path(tempfile.mkdtemp(prefix="reelmate-worker-"))
        return self.path

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.path is not None:
            shutil.rmtree(self.path, ignore_errors=True)


class ReelMateWorker:
    """One testable worker process backed by durable Postgres leases."""

    def __init__(
        self,
        *,
        database: Database,
        storage: R2Storage,
        feedback: FeedbackService,
        settings: Settings,
    ) -> None:
        if not settings.worker_id.strip():
            raise WorkerConfigurationError("WORKER_ID must not be blank")
        self.database = database
        self.storage = storage
        self.feedback = feedback
        self.settings = settings

    async def run_once(self) -> bool:
        """Claim and finish at most one job; return whether a job was claimed."""

        claimed = await self._claim()
        if claimed is None:
            return False

        stop_heartbeat = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat(claimed.id, stop_heartbeat),
            name=f"reelmate-heartbeat-{claimed.id}",
        )
        try:
            await self._process(claimed, heartbeat)
        except asyncio.CancelledError:
            raise
        except WorkerLeaseError:
            # Another worker may reclaim an expired lease. Never overwrite its
            # result or failure state after ownership has been lost.
            logger.warning("Worker lease lost for analysis_id=%s", claimed.id)
        except Exception as exc:
            disposition = _classify_failure(exc)
            await self._record_failure(claimed, disposition)
        finally:
            stop_heartbeat.set()
            heartbeat.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await heartbeat
        return True

    async def run_forever(self, *, stop_event: asyncio.Event | None = None) -> None:
        """Poll until cancelled or until an optional cooperative stop is set."""

        stop = stop_event or asyncio.Event()
        next_cleanup_at = 0.0
        logger.info("ReelMate worker started worker_id=%s", self.settings.worker_id)
        while not stop.is_set():
            if time.monotonic() >= next_cleanup_at:
                await self._cleanup_stale_sources()
                next_cleanup_at = time.monotonic() + 300.0
            try:
                processed = await self.run_once()
            except Exception as exc:
                logger.error("Worker poll failed error_type=%s", type(exc).__name__)
                processed = False
            try:
                await self._drain_source_deletions(limit=2 if processed else 10)
            except Exception as exc:
                logger.error("Source-deletion drain failed error_type=%s", type(exc).__name__)
            if processed:
                continue
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.settings.worker_poll_seconds)
            except TimeoutError:
                pass

    async def _cleanup_stale_sources(self) -> None:
        try:
            async with self.database.session() as session:
                stale = await expire_stale_sources(
                    session,
                    retention_hours=self.settings.source_retention_hours,
                    limit=50,
                )
        except Exception as exc:
            logger.error("Stale-source sweep failed error_type=%s", type(exc).__name__)
            return

        if stale:
            logger.info("Queued stale private sources for deletion count=%s", len(stale))

    async def _drain_source_deletions(self, *, limit: int) -> None:
        async with self.database.session() as session:
            jobs = await claim_source_deletions(
                session,
                worker_id=self.settings.worker_id,
                limit=limit,
                lease_seconds=min(self.settings.worker_lease_seconds, 3_600),
            )
        for job in jobs:
            try:
                await self.storage.delete_object(job.object_key)
            except Exception:
                async with self.database.session() as session:
                    await reschedule_source_deletion(
                        session,
                        job_id=job.id,
                        worker_id=self.settings.worker_id,
                    )
                logger.warning("Private source deletion will retry job_id=%s", job.id)
                continue
            async with self.database.session() as session:
                await complete_source_deletion(
                    session,
                    job_id=job.id,
                    worker_id=self.settings.worker_id,
                )

    async def _claim(self) -> ClaimedAnalysis | None:
        async with self.database.session() as session:
            analysis = await claim_next_analysis(
                session,
                worker_id=self.settings.worker_id,
                lease_seconds=self.settings.worker_lease_seconds,
                max_worker_attempts=self.settings.worker_max_attempts,
            )
            return None if analysis is None else ClaimedAnalysis.from_model(analysis)

    async def _process(
        self,
        claimed: ClaimedAnalysis,
        heartbeat: asyncio.Task[None],
    ) -> None:
        with _TemporaryWorkspace() as workspace:
            source_path = workspace / _source_filename(claimed.mode, claimed.mime_type)
            stored = await self.storage.head_object(claimed.object_key)
            _validate_stored_object(
                claimed,
                stored.size_bytes,
                stored.content_type,
                max_video_bytes=self.settings.max_video_bytes,
                max_image_bytes=self.settings.max_image_bytes,
            )
            await self.storage.download_file(claimed.object_key, source_path)
            self._raise_heartbeat_failure(heartbeat)

            await self._set_stage(claimed.id, AnalysisStage.EXTRACTING)
            if claimed.mode == AnalysisMode.STORY_SONG:
                taste_profile = await self._load_story_taste(claimed.user_id)
                story = await asyncio.to_thread(
                    analyze_story_image,
                    source_path,
                    vocal_preference=claimed.vocal_preference.value,
                    taste_profile=taste_profile,
                )
                self._raise_heartbeat_failure(heartbeat)
                await self._set_stage(claimed.id, AnalysisStage.SCORING)
                await self._persist_story_completion(claimed, story)
                return

            pipeline = await asyncio.to_thread(
                run_pipeline_isolated,
                source_path,
                workspace_root=workspace / "pipeline",
                timeout_seconds=self.settings.worker_job_timeout_seconds,
            )
            if pipeline.metadata.duration_seconds > self.settings.max_video_duration_seconds:
                raise MediaValidationError(
                    "Uploaded video exceeds this deployment's duration limit.",
                    code="VIDEO_TOO_LONG",
                )
            self._raise_heartbeat_failure(heartbeat)

            await self._set_stage(claimed.id, AnalysisStage.SCORING)
            score = score_pipeline(pipeline)
            history = await self._load_history(claimed.user_id)

            await self._set_stage(claimed.id, AnalysisStage.GENERATING_FEEDBACK)
            feedback = await self.feedback.generate(pipeline, score)
            self._raise_heartbeat_failure(heartbeat)

            result, profile = _build_result(pipeline, score, feedback, history)
            await self._persist_completion(claimed, pipeline, score, feedback, result, profile)

    async def _load_history(self, user_id: UUID) -> list[Analysis]:
        async with self.database.session() as session:
            return await list_analyses(
                session,
                user_id=user_id,
                limit=5,
                statuses=[AnalysisStatus.COMPLETED],
                modes=[AnalysisMode.VIDEO_COACH],
            )

    async def _load_story_taste(self, user_id: UUID) -> StoryTasteProfile | None:
        async with self.database.session() as session:
            preference = await get_music_preference(session, user_id=user_id)
        if preference is None:
            return None
        return StoryTasteProfile.model_validate(
            {
                "preferred_languages": preference.preferred_languages,
                "preferred_moods": preference.preferred_moods,
                "favorite_artists": preference.favorite_artists,
                "favorite_tracks": preference.favorite_tracks,
                "profile_version": preference.profile_version,
                "profile_revision": preference.revision,
                "profile_updated_at": preference.updated_at,
            }
        )

    async def _persist_story_completion(
        self,
        claimed: ClaimedAnalysis,
        story: StoryRecommendationResult,
    ) -> None:
        result = story.model_dump(mode="json")
        completion = AnalysisCompletion(
            score=story.score,
            hook_score=None,
            pacing_score=None,
            av_sync_score=None,
            text_score=None,
            trend_score=None,
            confidence=story.confidence,
            result_json=result,
            metrics_json={
                "mode": "story_song",
                "face_count": story.image_summary.face_count,
                "visual_tags": story.image_summary.visual_tags,
                "recommendation_count": len(story.recommendations),
                "vocal_preference": story.requested_vocal_preference,
                "personalization_applied": story.personalization.applied,
                "preference_revision": story.personalization.profile_revision,
                "preference_resolution": story.personalization.resolution,
                "external_api_used": False,
            },
            pipeline_version=STORY_PIPELINE_VERSION,
            score_version=STORY_RANKER_VERSION,
            prompt_version="no-prompt",
            model_id=STORY_RANKER_VERSION,
            schema_version=story.schema_version,
            model_input_tokens=0,
            model_output_tokens=0,
            estimated_model_cost_usd=0,
            estimated_total_cost_usd=None,
            duration_seconds=None,
        )
        async with self.database.session() as session:
            await complete_analysis(
                session,
                analysis_id=claimed.id,
                worker_id=self.settings.worker_id,
                completion=completion,
            )

    async def _persist_completion(
        self,
        claimed: ClaimedAnalysis,
        pipeline: PipelineV1,
        score: ScoreResult,
        feedback: FeedbackResult,
        result: dict[str, Any],
        profile: ProfileSnapshot,
    ) -> None:
        metrics = _reduced_metrics(pipeline, feedback)
        completion = AnalysisCompletion(
            score=score.score,
            hook_score=score.sub_scores.hook,
            pacing_score=score.sub_scores.pacing,
            av_sync_score=score.sub_scores.av_sync,
            text_score=score.sub_scores.text,
            trend_score=None,
            confidence=score.confidence,
            result_json=result,
            metrics_json=metrics,
            pipeline_version=pipeline.pipeline_version,
            score_version=score.score_version,
            prompt_version=feedback.prompt_version,
            model_id=feedback.model_id,
            model_input_tokens=feedback.input_tokens,
            model_output_tokens=feedback.output_tokens,
            estimated_model_cost_usd=feedback.estimated_model_cost_usd,
            # Local compute and storage are deployment-dependent, so an honest
            # per-analysis total remains unknown until deployment meters them.
            estimated_total_cost_usd=None,
            duration_seconds=pipeline.metadata.duration_seconds,
        )
        profile_update = ProfileUpdate(
            niche=profile.inferred_niche,
            niche_confidence=profile.niche_confidence,
            editing_style=profile.editing_style,
            editing_style_confidence=profile.editing_style_confidence,
            typical_energy=profile.typical_energy,
            typical_energy_confidence=profile.typical_energy_confidence,
            recurring_issue_codes=profile.recurring_issue_codes,
            profile_version=profile.profile_version,
        )
        async with self.database.session() as session:
            await complete_analysis(
                session,
                analysis_id=claimed.id,
                worker_id=self.settings.worker_id,
                completion=completion,
            )
            await upsert_user_profile(
                session,
                user_id=claimed.user_id,
                profile=profile_update,
            )

    async def _set_stage(self, analysis_id: UUID, stage: AnalysisStage) -> None:
        async with self.database.session() as session:
            await update_analysis_stage(
                session,
                analysis_id=analysis_id,
                worker_id=self.settings.worker_id,
                stage=stage,
                lease_seconds=self.settings.worker_lease_seconds,
            )

    async def _heartbeat(self, analysis_id: UUID, stop: asyncio.Event) -> None:
        interval = max(1.0, min(30.0, self.settings.worker_lease_seconds / 3))
        while True:
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except TimeoutError:
                async with self.database.session() as session:
                    await renew_analysis_lease(
                        session,
                        analysis_id=analysis_id,
                        worker_id=self.settings.worker_id,
                        lease_seconds=self.settings.worker_lease_seconds,
                    )

    @staticmethod
    def _raise_heartbeat_failure(heartbeat: asyncio.Task[None]) -> None:
        if not heartbeat.done():
            return
        exception = heartbeat.exception()
        if exception is not None:
            raise exception
        raise WorkerLeaseError("Analysis heartbeat stopped before processing completed")

    async def _record_failure(
        self,
        claimed: ClaimedAnalysis,
        failure: FailureDisposition,
    ) -> None:
        try:
            async with self.database.session() as session:
                await fail_analysis(
                    session,
                    analysis_id=claimed.id,
                    worker_id=self.settings.worker_id,
                    failure_code=failure.code,
                    failure_detail=failure.detail,
                    retryable=failure.retryable,
                    delete_source=failure.delete_source,
                )
        except WorkerLeaseError:
            logger.warning("Could not record failure after lease loss analysis_id=%s", claimed.id)
        except Exception as exc:
            # Do not interpolate provider/storage exception messages; they may
            # include signed URLs, request bodies, or credentials.
            logger.error(
                "Could not persist worker failure analysis_id=%s error_type=%s",
                claimed.id,
                type(exc).__name__,
            )


def _source_filename(mode: AnalysisMode, mime_type: str) -> str:
    if mime_type == "video/mp4":
        return "source.mp4"
    if mime_type == "video/quicktime":
        return "source.mov"
    if mode == AnalysisMode.STORY_SONG and mime_type == "image/jpeg":
        return "source.jpg"
    if mode == AnalysisMode.STORY_SONG and mime_type == "image/png":
        return "source.png"
    if mode == AnalysisMode.STORY_SONG and mime_type == "image/webp":
        return "source.webp"
    raise MediaValidationError("Unsupported uploaded media type.", code="UNSUPPORTED_MEDIA_TYPE")


def _validate_stored_object(
    claimed: ClaimedAnalysis,
    size_bytes: int,
    content_type: str | None,
    *,
    max_video_bytes: int,
    max_image_bytes: int,
) -> None:
    maximum_bytes = max_video_bytes if claimed.mode == AnalysisMode.VIDEO_COACH else max_image_bytes
    if not 0 < size_bytes <= maximum_bytes:
        raise MediaValidationError("Uploaded media size is invalid.", code="MEDIA_TOO_LARGE")
    if claimed.actual_size_bytes is not None and size_bytes != claimed.actual_size_bytes:
        raise MediaValidationError("Uploaded media size changed.", code="MEDIA_SIZE_MISMATCH")
    if size_bytes != claimed.declared_size_bytes:
        raise MediaValidationError(
            "Uploaded media size differs from its declaration.", code="MEDIA_SIZE_MISMATCH"
        )
    normalized_type = content_type.split(";", 1)[0].strip().lower() if content_type else None
    if normalized_type is not None and normalized_type != claimed.mime_type:
        raise MediaValidationError(
            "Uploaded video content type changed.", code="MEDIA_TYPE_MISMATCH"
        )


def _classify_failure(exc: Exception) -> FailureDisposition:
    if isinstance(exc, StoryPipelineError):
        return FailureDisposition(
            code=_stable_failure_code(exc.code, "INVALID_IMAGE"),
            detail="The uploaded file is not a supported ReelMate story image.",
            retryable=exc.code in {"IMAGE_DEPENDENCY_MISSING"},
            delete_source=exc.code not in {"IMAGE_DEPENDENCY_MISSING"},
        )
    if isinstance(exc, MediaValidationError):
        return FailureDisposition(
            code=_stable_failure_code(exc.code, "INVALID_VIDEO"),
            detail="The uploaded file is not supported by the selected ReelMate mode.",
            retryable=False,
            delete_source=True,
        )
    if isinstance(exc, StorageObjectNotFound):
        return FailureDisposition(
            code="SOURCE_OBJECT_MISSING",
            detail="The private source upload could not be found.",
            retryable=False,
        )
    if isinstance(exc, (StorageDependencyError, PipelineDependencyError)):
        return FailureDisposition(
            code="WORKER_DEPENDENCY_UNAVAILABLE",
            detail="A required worker dependency is unavailable.",
            retryable=True,
        )
    if isinstance(exc, StorageError):
        return FailureDisposition(
            code="STORAGE_TEMPORARILY_UNAVAILABLE",
            detail="Private object storage could not complete the operation.",
            retryable=True,
        )
    if isinstance(exc, PipelineError):
        retryable = exc.code in {"MEDIA_TOOL_TIMEOUT", "PIPELINE_TIMEOUT"}
        return FailureDisposition(
            code=_stable_failure_code(exc.code, "PIPELINE_FAILED"),
            detail=(
                "Local media processing timed out."
                if retryable
                else "Local media processing could not analyze this video."
            ),
            retryable=retryable,
            delete_source=not retryable,
        )
    return FailureDisposition(
        code="PROCESSING_TEMPORARILY_FAILED",
        detail="The worker could not complete this analysis.",
        retryable=True,
    )


def _stable_failure_code(value: str, fallback: str) -> str:
    normalized = value.strip().upper()
    if (
        2 <= len(normalized) <= 64
        and normalized[0].isalpha()
        and all(character.isalnum() or character == "_" for character in normalized)
    ):
        return normalized
    return fallback


def _history_context(analysis: Analysis) -> dict[str, Any]:
    result = analysis.result_json if isinstance(analysis.result_json, dict) else {}
    return {
        "score": analysis.score,
        "completed_at": analysis.completed_at.isoformat() if analysis.completed_at else None,
        "pipeline_summary": result.get("pipeline_summary", {}),
        "feedback": result.get("feedback", []),
    }


def _build_result(
    pipeline: PipelineV1,
    score: ScoreResult,
    feedback: FeedbackResult,
    history: list[Analysis],
) -> tuple[dict[str, Any], ProfileSnapshot]:
    estimated_model_cost = (
        None
        if feedback.estimated_model_cost_usd is None
        else float(feedback.estimated_model_cost_usd)
    )
    pipeline_summary = _reduce_pipeline(pipeline)
    if feedback.inferred_niche is not None and feedback.niche_confidence is not None:
        pipeline_summary["niche_confidence"] = feedback.niche_confidence
        if feedback.niche_confidence >= 0.6:
            pipeline_summary["niche"] = feedback.inferred_niche
    base_result: dict[str, Any] = {
        "schema_version": "1",
        "mode": "video_coach",
        # Keep the primary result flat so mobile clients do not need to know
        # the worker's internal Pydantic model shape.
        "score": score.score,
        "sub_scores": score.sub_scores.model_dump(mode="json"),
        "confidence": score.confidence,
        "score_label": score.score_label,
        "score_experimental": score.score_experimental,
        "niche_detected": pipeline_summary.get("niche"),
        "niche_confidence": feedback.niche_confidence,
        "feedback": [item.model_dump(mode="json") for item in feedback.feedback],
        "feedback_source": feedback.source,
        "pipeline_summary": pipeline_summary,
        "versions": {
            "pipeline": pipeline.pipeline_version,
            "score": score.score_version,
            "prompt": feedback.prompt_version,
            "model": feedback.model_id,
        },
        "usage": {
            "model_input_tokens": feedback.input_tokens,
            "model_output_tokens": feedback.output_tokens,
            "estimated_model_cost_usd": estimated_model_cost,
            "estimated_total_cost_usd": None,
            "pricing_status": feedback.pricing_status,
            "pricing_version": feedback.pricing_version,
            "cost_limit_exceeded": feedback.cost_limit_exceeded,
            "external_api_used": False,
        },
    }
    if feedback.fallback_reason is not None:
        base_result["feedback_fallback_reason"] = feedback.fallback_reason

    history_for_profile: list[Any] = [*history, {"result_json": base_result}]
    profile = derive_profile(history_for_profile)
    previous_score = history[0].score if history and history[0].score is not None else None
    score_delta = score.score - previous_score if previous_score is not None else None
    base_result["personalization"] = {
        **profile.model_dump(mode="json"),
        "is_repeat_user": bool(history),
        "previous_score": previous_score,
        "score_delta": score_delta,
        "improvement_noted": score_delta is not None and score_delta > 0,
    }
    return base_result, profile


def _reduce_pipeline(pipeline: PipelineV1) -> dict[str, Any]:
    """Return measured signals while intentionally dropping every OCR string."""

    return {
        "pipeline_version": pipeline.pipeline_version,
        "duration_seconds": pipeline.metadata.duration_seconds,
        "size_bytes": pipeline.metadata.size_bytes,
        "dimensions": {
            "width": pipeline.metadata.width,
            "height": pipeline.metadata.height,
            "rotation_degrees": pipeline.metadata.rotation_degrees,
            "frame_rate": pipeline.metadata.frame_rate,
        },
        "has_audio": pipeline.metadata.has_audio,
        "scenes": pipeline.scenes.model_dump(mode="json"),
        "audio": pipeline.audio.model_dump(mode="json"),
        "text": {
            "frames_analyzed": pipeline.text.frames_analyzed,
            "frames_with_text": pipeline.text.frames_with_text,
            "readable_overlay_ratio": pipeline.text.readable_overlay_ratio,
            "has_text_in_hook": pipeline.text.has_text_in_hook,
            "overlays": [
                {
                    "timestamp_seconds": overlay.timestamp_seconds,
                    "duration_seconds": overlay.duration_seconds,
                    "position": overlay.position,
                    "confidence": overlay.confidence,
                    "flagged": overlay.flagged,
                }
                for overlay in pipeline.text.overlays
            ],
        },
        "hook": pipeline.hook.model_dump(mode="json"),
        "representative_frame_timestamps_seconds": (
            pipeline.representative_frame_timestamps_seconds
        ),
    }


def _reduced_metrics(pipeline: PipelineV1, feedback: FeedbackResult) -> dict[str, Any]:
    estimated_model_cost = (
        None
        if feedback.estimated_model_cost_usd is None
        else float(feedback.estimated_model_cost_usd)
    )
    return {
        "scene_count": len(pipeline.scenes.clip_lengths_seconds),
        "cut_count": len(pipeline.scenes.cuts_seconds),
        "dead_air_count": len(pipeline.scenes.dead_air_segments),
        "silence_gap_count": len(pipeline.audio.silence_gaps),
        "text_overlay_count": len(pipeline.text.overlays),
        "feedback_item_count": len(feedback.feedback),
        "feedback_source": feedback.source,
        "estimated_model_cost_usd": estimated_model_cost,
        "pricing_status": feedback.pricing_status,
        "pricing_version": feedback.pricing_version,
        "cost_limit_exceeded": feedback.cost_limit_exceeded,
    }


def build_worker_from_settings(settings: Settings) -> ReelMateWorker:
    """Create clients only from explicit ReelMate environment configuration."""

    missing: list[str] = []
    if settings.database_url is None or not settings.database_url.get_secret_value().strip():
        missing.append("DATABASE_URL")
    if not settings.r2_account_id or not settings.r2_account_id.strip():
        missing.append("R2_ACCOUNT_ID")
    if (
        settings.r2_access_key_id is None
        or not settings.r2_access_key_id.get_secret_value().strip()
    ):
        missing.append("R2_ACCESS_KEY_ID")
    if (
        settings.r2_secret_access_key is None
        or not settings.r2_secret_access_key.get_secret_value().strip()
    ):
        missing.append("R2_SECRET_ACCESS_KEY")
    if not settings.r2_bucket_name or not settings.r2_bucket_name.strip():
        missing.append("R2_BUCKET_NAME")
    if missing:
        raise WorkerConfigurationError(
            "Worker requires fresh ReelMate project configuration: " + ", ".join(missing)
        )

    assert settings.database_url is not None
    assert settings.r2_account_id is not None
    assert settings.r2_access_key_id is not None
    assert settings.r2_secret_access_key is not None
    assert settings.r2_bucket_name is not None

    database_url = settings.database_url.get_secret_value()
    access_key_id = settings.r2_access_key_id.get_secret_value()
    secret_access_key = settings.r2_secret_access_key.get_secret_value()

    database = Database(database_url)
    storage = R2Storage(
        R2StorageSettings(
            account_id=settings.r2_account_id,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            bucket_name=settings.r2_bucket_name,
            key_prefix=settings.r2_key_prefix,
            upload_expiry_seconds=min(settings.r2_upload_expiry_seconds, 900),
            max_video_bytes=settings.max_video_bytes,
            max_image_bytes=settings.max_image_bytes,
        )
    )
    feedback = FeedbackService()
    return ReelMateWorker(
        database=database,
        storage=storage,
        feedback=feedback,
        settings=settings,
    )


async def _run_cli(settings: Settings) -> None:
    worker = build_worker_from_settings(settings)
    try:
        await worker.run_forever()
    finally:
        try:
            await worker.feedback.aclose()
        finally:
            await worker.database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ReelMate PostgreSQL job worker")
    parser.parse_args()
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        asyncio.run(_run_cli(settings))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()
