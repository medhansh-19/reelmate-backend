from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.db import (
    Analysis,
    AnalysisMode,
    AnalysisStage,
    AnalysisStatus,
    MusicPreference,
    SourceDeletionJob,
    StoryVocalPreference,
    normalize_async_database_url,
)
from app.repository import (
    AnalysisCompletion,
    _validate_completion,
    cancel_analysis,
    complete_analysis,
    delete_analysis,
    reschedule_source_deletion,
    sanitize_failure_detail,
    upsert_music_preference,
)


def _valid_completion() -> AnalysisCompletion:
    return AnalysisCompletion(
        score=71,
        hook_score=62,
        pacing_score=78,
        av_sync_score=65,
        text_score=80,
        trend_score=None,
        result_json={"feedback": []},
        metrics_json={"duration_seconds": 20.5},
        pipeline_version="pipeline-v1",
        score_version="score-v1",
        prompt_version="prompt-v1",
        model_id="configured-model",
        estimated_model_cost_usd=Decimal("0.005"),
        estimated_total_cost_usd=Decimal("0.012"),
    )


def _analysis(
    *,
    status: AnalysisStatus,
    stage: AnalysisStage,
    now: datetime,
) -> Analysis:
    return Analysis(
        id=uuid4(),
        user_id=uuid4(),
        idempotency_key=f"request-{uuid4()}",
        object_key=f"reelmate/analyses/u/{uuid4()}/source.mp4",
        declared_size_bytes=1_000,
        mime_type="video/mp4",
        mode=AnalysisMode.VIDEO_COACH,
        status=status,
        stage=stage,
        upload_expires_at=now + timedelta(minutes=10),
        created_at=now,
        updated_at=now,
    )


def test_normalize_supabase_url_uses_asyncpg_and_preserves_injected_password() -> None:
    normalized = normalize_async_database_url(
        "postgresql://postgres:project-specific-test@db.example.test:5432/postgres?sslmode=require"
    )

    assert normalized.startswith("postgresql+asyncpg://")
    assert "project-specific-test" in normalized
    assert "ssl=require" in normalized
    assert "sslmode" not in normalized


def test_normalize_database_url_rejects_non_postgres_connections() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        normalize_async_database_url("sqlite:///tmp/reelmate.db")


def test_failure_detail_is_single_line_bounded_and_redacted() -> None:
    value = sanitize_failure_detail(
        "request failed\nAuthorization: Bearer abc.def.ghi "
        "postgresql://admin:super-secret@db.example.test/postgres",
        max_length=80,
    )

    assert value is not None
    assert "abc.def.ghi" not in value
    assert "super-secret" not in value
    assert "\n" not in value
    assert len(value) <= 80


def test_completion_rejects_out_of_range_scores() -> None:
    with pytest.raises(ValueError, match="score"):
        _validate_completion(replace(_valid_completion(), score=101))

    with pytest.raises(ValueError, match="between 5 and 95"):
        _validate_completion(replace(_valid_completion(), score=4))


def test_completion_requires_all_version_identifiers() -> None:
    with pytest.raises(ValueError, match="every schema/pipeline/model version"):
        _validate_completion(replace(_valid_completion(), prompt_version=""))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("complete_onboarding", "expected_completion_update"),
    [(False, False), (True, True)],
)
async def test_music_preference_upsert_preserves_one_time_onboarding_completion(
    complete_onboarding: bool,
    expected_completion_update: bool,
) -> None:
    now = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    preference = MusicPreference(
        user_id=uuid4(),
        preferred_languages=["English"],
        preferred_moods=["joyful"],
        favorite_artists=[],
        favorite_tracks=[],
        default_vocal_preference=StoryVocalPreference.ANY,
        profile_version="1",
        revision=1,
        onboarding_completed_at=now if complete_onboarding else None,
        created_at=now,
        updated_at=now,
    )

    class Result:
        def scalar_one(self) -> MusicPreference:
            return preference

    session = AsyncMock()
    session.scalar.return_value = now
    session.execute.return_value = Result()

    result = await upsert_music_preference(
        session,
        user_id=preference.user_id,
        preferred_languages=preference.preferred_languages,
        preferred_moods=preference.preferred_moods,
        favorite_artists=preference.favorite_artists,
        favorite_tracks=preference.favorite_tracks,
        default_vocal_preference=preference.default_vocal_preference,
        complete_onboarding=complete_onboarding,
    )

    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect())).casefold()
    conflict_update = sql.split("do update set", maxsplit=1)[1].split(" returning ", maxsplit=1)[0]

    assert result is preference
    assert ("onboarding_completed_at" in conflict_update) is expected_completion_update
    if complete_onboarding:
        assert "coalesce(music_preferences.onboarding_completed_at" in conflict_update


@pytest.mark.asyncio
async def test_cancel_releases_lease_and_enqueues_cleanup_in_same_session() -> None:
    now = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    analysis = _analysis(status=AnalysisStatus.PROCESSING, stage=AnalysisStage.EXTRACTING, now=now)
    analysis.worker_lease_owner = "worker-a"
    analysis.worker_lease_expires_at = now + timedelta(minutes=5)
    session = AsyncMock()
    session.scalar.side_effect = [analysis, now]

    cancelled = await cancel_analysis(
        session,
        analysis_id=analysis.id,
        user_id=analysis.user_id,
    )

    assert cancelled.status == AnalysisStatus.CANCELLED
    assert cancelled.stage == AnalysisStage.CANCELLED
    assert cancelled.cancelled_at == now
    assert cancelled.worker_lease_owner is None
    assert cancelled.worker_lease_expires_at is None
    assert session.execute.await_count == 1
    assert session.flush.await_count == 1


@pytest.mark.asyncio
async def test_delete_enqueues_cleanup_before_removing_analysis_row() -> None:
    now = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    analysis = _analysis(
        status=AnalysisStatus.AWAITING_UPLOAD,
        stage=AnalysisStage.AWAITING_UPLOAD,
        now=now,
    )
    session = AsyncMock()
    session.scalar.side_effect = [analysis, now]

    deleted = await delete_analysis(
        session,
        analysis_id=analysis.id,
        user_id=analysis.user_id,
        allowed_statuses=[AnalysisStatus.AWAITING_UPLOAD],
    )

    assert deleted is analysis
    assert session.execute.await_count == 1
    session.delete.assert_awaited_once_with(analysis)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "expected_execute_count"),
    [(AnalysisMode.VIDEO_COACH, 2), (AnalysisMode.STORY_SONG, 1)],
)
async def test_only_video_completion_increments_creator_baseline(
    mode: AnalysisMode,
    expected_execute_count: int,
) -> None:
    now = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    analysis = _analysis(
        status=AnalysisStatus.PROCESSING,
        stage=AnalysisStage.SCORING,
        now=now,
    )
    analysis.mode = mode
    analysis.worker_lease_owner = "worker-a"
    analysis.worker_lease_expires_at = now + timedelta(minutes=5)
    session = AsyncMock()
    session.scalar.side_effect = [now, analysis]

    await complete_analysis(
        session,
        analysis_id=analysis.id,
        worker_id="worker-a",
        completion=_valid_completion(),
    )

    # Both modes enqueue source cleanup; only video also updates UserProfile.
    assert session.execute.await_count == expected_execute_count


@pytest.mark.asyncio
async def test_source_delete_retry_uses_bounded_backoff_and_sanitized_code() -> None:
    now = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    job = SourceDeletionJob(
        id=uuid4(),
        analysis_id=uuid4(),
        object_key="reelmate/analyses/u/a/source.mp4",
        reason="completed",
        attempt_count=2,
        available_at=now,
        lease_owner="worker-a",
        lease_expires_at=now + timedelta(minutes=5),
        created_at=now,
        updated_at=now,
    )
    session = AsyncMock()
    session.scalar.side_effect = [now, job]

    assert await reschedule_source_deletion(
        session,
        job_id=job.id,
        worker_id="worker-a",
        error_code="provider said secret=https://signed.example.test",
    )

    assert job.attempt_count == 3
    assert job.available_at == now + timedelta(seconds=120)
    assert job.lease_owner is None
    assert job.lease_expires_at is None
    assert job.last_error_code == "STORAGE_DELETE_FAILED"
