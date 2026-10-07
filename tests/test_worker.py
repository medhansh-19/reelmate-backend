from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app import worker as worker_module
from app.config import Settings
from app.db import AnalysisMode, MusicPreference, StoryVocalPreference
from app.feedback import FeedbackItem, FeedbackResult
from app.pipeline import (
    AudioSignals,
    HookSignals,
    MediaMetadata,
    MediaValidationError,
    PipelineV1,
    TextOverlay,
    TextSignals,
    build_scene_signals,
)
from app.repository import WorkerLeaseError
from app.storage import StorageError
from app.story_recommender import (
    SongRecommendation,
    StoryImageSignals,
    StoryRecommendationResult,
)
from app.worker import ReelMateWorker, WorkerConfigurationError, build_worker_from_settings


class FakeDatabase:
    def __init__(self) -> None:
        self.sessions: list[object] = []

    @asynccontextmanager
    async def session(self) -> Any:
        session = object()
        self.sessions.append(session)
        yield session


class FakeStorage:
    def __init__(
        self,
        *,
        head_error: Exception | None = None,
        delete_error: Exception | None = None,
        content_type: str = "video/mp4",
    ) -> None:
        self.head_error = head_error
        self.delete_error = delete_error
        self.content_type = content_type
        self.deleted: list[str] = []
        self.downloaded: list[str] = []

    async def head_object(self, object_key: str) -> Any:
        if self.head_error is not None:
            raise self.head_error
        return SimpleNamespace(
            size_bytes=10_000,
            content_type=self.content_type,
        )

    async def download_file(self, object_key: str, destination: Path) -> Path:
        await asyncio.to_thread(destination.write_bytes, b"private-video-source")
        self.downloaded.append(object_key)
        return destination

    async def delete_object(self, object_key: str) -> None:
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted.append(object_key)


class FakeFeedback:
    def __init__(self) -> None:
        self.generate_calls = 0

    async def generate(self, *args: Any, **kwargs: Any) -> FeedbackResult:
        self.generate_calls += 1
        return FeedbackResult(
            feedback=[
                FeedbackItem(
                    type="strength",
                    start_seconds=0,
                    end_seconds=1,
                    message="The hook has a clear visual start.",
                    action="Keep this visual opening in the next edit.",
                    evidence="The deterministic hook score is the strongest signal.",
                    severity="low",
                ),
                FeedbackItem(
                    type="pacing",
                    start_seconds=3,
                    end_seconds=5,
                    message="This section can move more quickly.",
                    action="Trim this section by one short beat.",
                    evidence="The measured clip is longer than nearby clips.",
                    severity="medium",
                ),
                FeedbackItem(
                    type="text",
                    start_seconds=1,
                    end_seconds=2,
                    message="The text needs a little more reading time.",
                    action="Keep the overlay visible for another second.",
                    evidence="The measured overlay duration is under the target.",
                    severity="medium",
                ),
            ],
            source="local_signal_engine",
            model_id="local-test",
            prompt_version="rules-test",
        )


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        worker_id="worker-test",
        worker_lease_seconds=60,
        worker_job_timeout_seconds=60,
        worker_poll_seconds=0.2,
    )


def _analysis(
    mode: AnalysisMode = AnalysisMode.VIDEO_COACH,
    vocal_preference: StoryVocalPreference = StoryVocalPreference.ANY,
) -> SimpleNamespace:
    mime_type = "video/mp4" if mode == AnalysisMode.VIDEO_COACH else "image/jpeg"
    extension = "mp4" if mode == AnalysisMode.VIDEO_COACH else "jpg"
    return SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        object_key=f"reelmate/analyses/user/analysis/source.{extension}",
        mime_type=mime_type,
        declared_size_bytes=10_000,
        actual_size_bytes=10_000,
        mode=mode,
        vocal_preference=vocal_preference,
    )


def _pipeline() -> PipelineV1:
    duration = 12.0
    return PipelineV1(
        metadata=MediaMetadata(
            duration_seconds=duration,
            size_bytes=10_000,
            format_name="mov,mp4",
            video_codec="h264",
            width=1080,
            height=1920,
            frame_rate=30.0,
            rotation_degrees=0,
            has_audio=True,
            audio_codec="aac",
            audio_sample_rate=48_000,
            audio_channels=2,
        ),
        scenes=build_scene_signals(duration, [2.0, 4.0, 7.0, 10.0]),
        audio=AudioSignals(
            has_audio=True,
            bpm=120.0,
            rms_energy_mean=0.12,
            rms_energy_peak=0.3,
            energy="high",
            mood="intense",
            silence_gaps=[],
            silence_ratio=0.0,
        ),
        text=TextSignals(
            overlays=[
                TextOverlay(
                    text="RAW OCR MUST NOT BE SAVED",
                    timestamp_seconds=1.0,
                    duration_seconds=0.8,
                    position="top",
                    confidence=90.0,
                    flagged=True,
                )
            ],
            frames_analyzed=8,
            frames_with_text=1,
            readable_overlay_ratio=0.0,
            has_text_in_hook=True,
        ),
        hook=HookSignals(
            duration_analyzed_seconds=3.0,
            frames_analyzed=7,
            has_motion=True,
            motion_score=0.1,
            has_face=True,
            face_frame_ratio=0.7,
            has_text=True,
            cuts_in_hook=1,
        ),
        representative_frame_timestamps_seconds=[0.0, 1.0, 3.0, 8.0],
    )


def _worker(
    database: FakeDatabase,
    storage: FakeStorage,
) -> ReelMateWorker:
    return ReelMateWorker(
        database=database,  # type: ignore[arg-type]
        storage=storage,  # type: ignore[arg-type]
        feedback=FakeFeedback(),  # type: ignore[arg-type]
        settings=_settings(),
    )


@pytest.mark.asyncio
async def test_run_once_returns_false_when_queue_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_claim(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(worker_module, "claim_next_analysis", no_claim)
    database = FakeDatabase()
    storage = FakeStorage()

    processed = await _worker(database, storage).run_once()

    assert processed is False
    assert storage.downloaded == []
    assert len(database.sessions) == 1


@pytest.mark.asyncio
async def test_run_forever_survives_transient_claim_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(FakeDatabase(), FakeStorage())
    stop = asyncio.Event()
    calls = 0

    async def no_cleanup() -> None:
        return None

    async def flaky_run_once() -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("database outage")
        stop.set()
        return False

    monkeypatch.setattr(worker, "_cleanup_stale_sources", no_cleanup)
    monkeypatch.setattr(worker, "run_once", flaky_run_once)

    await worker.run_forever(stop_event=stop)

    assert calls == 2


@pytest.mark.asyncio
async def test_success_persists_reduced_result_profile_and_queues_source_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _analysis()
    pipeline = _pipeline()
    completed: list[Any] = []
    profile_updates: list[Any] = []
    stages: list[Any] = []

    async def claim(*args: Any, **kwargs: Any) -> Any:
        return analysis

    async def update_stage(*args: Any, **kwargs: Any) -> None:
        stages.append(kwargs["stage"])

    async def history(*args: Any, **kwargs: Any) -> list[Any]:
        return [
            SimpleNamespace(
                result_json={"pipeline_summary": {"audio": {"energy": "high"}}},
                score=70,
                completed_at=datetime.now(UTC),
            )
        ]

    async def complete(*args: Any, **kwargs: Any) -> None:
        completed.append(kwargs["completion"])

    async def upsert(*args: Any, **kwargs: Any) -> None:
        profile_updates.append(kwargs["profile"])

    monkeypatch.setattr(worker_module, "claim_next_analysis", claim)
    monkeypatch.setattr(worker_module, "update_analysis_stage", update_stage)
    monkeypatch.setattr(worker_module, "renew_analysis_lease", update_stage)
    monkeypatch.setattr(worker_module, "run_pipeline_isolated", lambda *args, **kwargs: pipeline)
    monkeypatch.setattr(worker_module, "list_analyses", history)
    monkeypatch.setattr(worker_module, "complete_analysis", complete)
    monkeypatch.setattr(worker_module, "upsert_user_profile", upsert)

    database = FakeDatabase()
    storage = FakeStorage()
    processed = await _worker(database, storage).run_once()

    assert processed is True
    assert storage.deleted == []
    assert [stage.value for stage in stages] == [
        "extracting",
        "scoring",
        "generating_feedback",
    ]
    assert len(completed) == 1
    completion = completed[0]
    assert completion.pipeline_version == "pipeline-v1"
    assert completion.score_version == "score-v1"
    assert completion.prompt_version == "rules-test"
    assert completion.model_id == "local-test"
    assert completion.model_input_tokens == 0
    assert completion.model_output_tokens == 0
    assert completion.duration_seconds == 12.0
    assert isinstance(completion.result_json["score"], int)
    assert completion.result_json["sub_scores"]["hook"] == completion.hook_score
    assert completion.result_json["confidence"] == completion.confidence
    assert completion.result_json["score_label"] == "reel_readiness"
    assert completion.result_json["score_experimental"] is True
    assert completion.estimated_model_cost_usd == 0
    assert completion.estimated_total_cost_usd is None
    assert completion.result_json["usage"]["estimated_model_cost_usd"] == 0.0
    assert completion.result_json["usage"]["estimated_total_cost_usd"] is None
    assert completion.result_json["usage"]["pricing_status"] == "no_model_call"
    assert completion.result_json["usage"]["external_api_used"] is False
    assert completion.metrics_json["pricing_status"] == "no_model_call"
    serialized = str(completion.result_json)
    assert "RAW OCR MUST NOT BE SAVED" not in serialized
    assert "source.mp4" not in serialized
    assert profile_updates[0].typical_energy == "high"
    assert profile_updates[0].niche is None
    assert completion.result_json["niche_detected"] is None
    assert completion.result_json["personalization"]["is_repeat_user"] is True
    assert completion.result_json["personalization"]["previous_score"] == 70


@pytest.mark.asyncio
async def test_story_image_uses_local_ranker_and_skips_video_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _analysis(AnalysisMode.STORY_SONG, StoryVocalPreference.NO_LYRICS)
    stages: list[Any] = []
    completions: list[Any] = []
    story = StoryRecommendationResult(
        requested_vocal_preference="no_lyrics",
        score=88,
        confidence=0.82,
        image_summary=StoryImageSignals(
            width=1080,
            height=1920,
            brightness=0.7,
            saturation=0.6,
            contrast=0.5,
            warmth=0.7,
            colorfulness=0.6,
            edge_density=0.3,
            center_activity=0.4,
            face_count=1,
            face_prominence=0.2,
            dominant_colors=["gold"],
            visual_tags=["portrait", "warm"],
            mood_profile={
                "calm": 0.2,
                "energetic": 0.3,
                "romantic": 0.5,
                "joyful": 0.4,
                "moody": 0.1,
                "dreamy": 0.45,
                "bold": 0.2,
                "nostalgic": 0.35,
            },
        ),
        recommendations=[
            SongRecommendation(
                song_id=f"song-{index}",
                title=f"Song {index}",
                artist=f"Artist {index}",
                language="Instrumental",
                match_score=90 - index,
                bpm=100,
                energy="medium",
                vocal_type="none",
                has_lyrics=False,
                aesthetic_tags=["romantic"],
                matched_moods=["romantic", "dreamy"],
                why="Measured romantic and dreamy signals match this song.",
                search_query=f"Song {index} Artist {index}",
            )
            for index in range(3)
        ],
        personalization={
            "applied": True,
            "source": "first_party",
            "signals_provided": ["preferred_languages", "preferred_moods"],
            "signals_used": ["preferred_languages", "preferred_moods"],
            "profile_version": "1",
            "profile_revision": 4,
            "profile_updated_at": "2026-08-09T12:00:00Z",
            "resolution": "processing_start",
            "spotify_data_used": False,
        },
        versions={
            "pipeline": "story-vision-v1",
            "ranking_model": "visual-song-mmr-v2",
            "catalog": "test-catalog",
        },
        privacy={
            "external_api_used": False,
            "source_included_in_result": False,
            "source_cleanup": "durable_outbox",
        },
    )

    async def claim(*args: Any, **kwargs: Any) -> Any:
        return analysis

    async def update_stage(*args: Any, **kwargs: Any) -> None:
        stages.append(kwargs["stage"])

    async def complete(*args: Any, **kwargs: Any) -> None:
        completions.append(kwargs["completion"])

    def no_video_pipeline(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("story mode must not run the video pipeline")

    monkeypatch.setattr(worker_module, "claim_next_analysis", claim)
    monkeypatch.setattr(worker_module, "update_analysis_stage", update_stage)
    monkeypatch.setattr(worker_module, "renew_analysis_lease", update_stage)

    async def music_preference(*args: Any, **kwargs: Any) -> MusicPreference:
        return MusicPreference(
            user_id=analysis.user_id,
            preferred_languages=["Instrumental"],
            preferred_moods=["dreamy"],
            favorite_artists=[],
            favorite_tracks=[],
            default_vocal_preference=StoryVocalPreference.NO_LYRICS,
            profile_version="1",
            revision=4,
            created_at=datetime(2026, 8, 1, tzinfo=UTC),
            updated_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        )

    monkeypatch.setattr(worker_module, "get_music_preference", music_preference)
    ranker_call: dict[str, Any] = {}

    def local_ranker(*_args: Any, **kwargs: Any) -> StoryRecommendationResult:
        ranker_call.update(kwargs)
        return story

    monkeypatch.setattr(worker_module, "analyze_story_image", local_ranker)
    monkeypatch.setattr(worker_module, "run_pipeline_isolated", no_video_pipeline)
    monkeypatch.setattr(worker_module, "complete_analysis", complete)

    worker = _worker(FakeDatabase(), FakeStorage(content_type="image/jpeg"))
    assert await worker.run_once() is True
    assert [stage.value for stage in stages] == ["extracting", "scoring"]
    assert len(completions) == 1
    completion = completions[0]
    assert completion.hook_score is None
    assert completion.model_input_tokens == 0
    assert completion.result_json["mode"] == "story_song"
    assert completion.result_json["privacy"]["external_api_used"] is False
    assert completion.schema_version == "3"
    assert completion.metrics_json["preference_revision"] == 4
    taste_profile = ranker_call["taste_profile"]
    assert taste_profile.preferred_languages == ["Instrumental"]
    assert taste_profile.preferred_moods == ["dreamy"]
    assert taste_profile.profile_revision == 4
    assert taste_profile.profile_updated_at == datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    assert ranker_call["vocal_preference"] == "no_lyrics"


@pytest.mark.asyncio
async def test_invalid_media_is_non_retryable_and_source_is_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _analysis()
    failures: list[dict[str, Any]] = []

    async def claim(*args: Any, **kwargs: Any) -> Any:
        return analysis

    async def update_stage(*args: Any, **kwargs: Any) -> None:
        return None

    def invalid_pipeline(*args: Any, **kwargs: Any) -> None:
        raise MediaValidationError("untrusted provider detail", code="VIDEO_STREAM_MISSING")

    async def fail(*args: Any, **kwargs: Any) -> None:
        failures.append(kwargs)

    monkeypatch.setattr(worker_module, "claim_next_analysis", claim)
    monkeypatch.setattr(worker_module, "update_analysis_stage", update_stage)
    monkeypatch.setattr(worker_module, "renew_analysis_lease", update_stage)
    monkeypatch.setattr(worker_module, "run_pipeline_isolated", invalid_pipeline)
    monkeypatch.setattr(worker_module, "fail_analysis", fail)

    database = FakeDatabase()
    storage = FakeStorage()
    processed = await _worker(database, storage).run_once()

    assert processed is True
    assert failures[0]["failure_code"] == "VIDEO_STREAM_MISSING"
    assert failures[0]["retryable"] is False
    assert failures[0]["delete_source"] is True
    assert "untrusted provider detail" not in failures[0]["failure_detail"]
    assert storage.deleted == []


@pytest.mark.asyncio
async def test_storage_failure_is_retryable_and_retains_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _analysis()
    failures: list[dict[str, Any]] = []

    async def claim(*args: Any, **kwargs: Any) -> Any:
        return analysis

    async def fail(*args: Any, **kwargs: Any) -> None:
        failures.append(kwargs)

    monkeypatch.setattr(worker_module, "claim_next_analysis", claim)
    monkeypatch.setattr(worker_module, "fail_analysis", fail)

    database = FakeDatabase()
    storage = FakeStorage(head_error=StorageError("signed URL must not be stored"))
    processed = await _worker(database, storage).run_once()

    assert processed is True
    assert failures[0]["failure_code"] == "STORAGE_TEMPORARILY_UNAVAILABLE"
    assert failures[0]["retryable"] is True
    assert "signed URL" not in failures[0]["failure_detail"]
    assert storage.deleted == []


@pytest.mark.asyncio
async def test_stale_source_sweep_uses_retention_policy_and_queues_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _analysis()
    calls: list[dict[str, Any]] = []

    async def expire(*args: Any, **kwargs: Any) -> list[Any]:
        calls.append(kwargs)
        return [analysis]

    monkeypatch.setattr(worker_module, "expire_stale_sources", expire)
    database = FakeDatabase()
    storage = FakeStorage()

    await _worker(database, storage)._cleanup_stale_sources()

    assert calls == [{"retention_hours": 24, "limit": 50}]
    assert storage.deleted == []


@pytest.mark.asyncio
async def test_source_deletion_drain_acknowledges_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = SimpleNamespace(id=uuid4(), object_key="reelmate/analyses/u/a/source.mp4")
    acknowledged: list[Any] = []

    async def claim(*args: Any, **kwargs: Any) -> list[Any]:
        return [job]

    async def complete(*args: Any, **kwargs: Any) -> None:
        acknowledged.append(kwargs)

    monkeypatch.setattr(worker_module, "claim_source_deletions", claim)
    monkeypatch.setattr(worker_module, "complete_source_deletion", complete)
    storage = FakeStorage()

    await _worker(FakeDatabase(), storage)._drain_source_deletions(limit=10)

    assert storage.deleted == [job.object_key]
    assert acknowledged[0]["job_id"] == job.id
    assert acknowledged[0]["worker_id"] == "worker-test"


@pytest.mark.asyncio
async def test_source_deletion_drain_reschedules_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = SimpleNamespace(id=uuid4(), object_key="reelmate/analyses/u/a/source.mp4")
    rescheduled: list[Any] = []
    acknowledged: list[Any] = []

    async def claim(*args: Any, **kwargs: Any) -> list[Any]:
        return [job]

    async def reschedule(*args: Any, **kwargs: Any) -> None:
        rescheduled.append(kwargs)

    async def complete(*args: Any, **kwargs: Any) -> None:
        acknowledged.append(kwargs)

    monkeypatch.setattr(worker_module, "claim_source_deletions", claim)
    monkeypatch.setattr(worker_module, "reschedule_source_deletion", reschedule)
    monkeypatch.setattr(worker_module, "complete_source_deletion", complete)
    storage = FakeStorage(delete_error=StorageError("private provider detail"))

    await _worker(FakeDatabase(), storage)._drain_source_deletions(limit=10)

    assert rescheduled[0]["job_id"] == job.id
    assert acknowledged == []


@pytest.mark.asyncio
async def test_lease_loss_never_overwrites_job_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _analysis()
    failures: list[dict[str, Any]] = []

    async def claim(*args: Any, **kwargs: Any) -> Any:
        return analysis

    async def lose_lease(*args: Any, **kwargs: Any) -> None:
        raise WorkerLeaseError("lease now belongs to another worker")

    async def fail(*args: Any, **kwargs: Any) -> None:
        failures.append(kwargs)

    monkeypatch.setattr(worker_module, "claim_next_analysis", claim)
    monkeypatch.setattr(worker_module, "update_analysis_stage", lose_lease)
    monkeypatch.setattr(worker_module, "fail_analysis", fail)

    database = FakeDatabase()
    storage = FakeStorage()
    processed = await _worker(database, storage).run_once()

    assert processed is True
    assert failures == []
    assert storage.deleted == []


def test_cli_builder_fails_before_creating_clients_without_fresh_project_config() -> None:
    with pytest.raises(WorkerConfigurationError) as raised:
        build_worker_from_settings(Settings(_env_file=None, app_env="test"))

    message = str(raised.value)
    assert "DATABASE_URL" in message
    assert "SUPABASE_URL" not in message
    assert "R2_ACCESS_KEY_ID" in message
    assert "OPENAI_API_KEY" not in message
    assert "OPENAI_SAFETY_IDENTIFIER_SECRET" not in message
