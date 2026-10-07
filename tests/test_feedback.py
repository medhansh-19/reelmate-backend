from __future__ import annotations

import pytest

from app.feedback import COACHING_MODEL_VERSION, FeedbackService
from app.pipeline import (
    AudioSignals,
    HookSignals,
    MediaMetadata,
    PipelineV1,
    TextOverlay,
    TextSignals,
    TimedSegment,
    build_scene_signals,
)
from app.scoring import score_pipeline


def _pipeline() -> PipelineV1:
    return PipelineV1(
        metadata=MediaMetadata(
            duration_seconds=12.0,
            size_bytes=10_000,
            format_name="mov,mp4",
            video_codec="h264",
            width=1080,
            height=1920,
            frame_rate=30.0,
            has_audio=True,
            audio_codec="aac",
            audio_sample_rate=48_000,
            audio_channels=2,
        ),
        scenes=build_scene_signals(12.0, [2.0, 7.0]),
        audio=AudioSignals(
            has_audio=True,
            bpm=120.0,
            rms_energy_mean=0.08,
            rms_energy_peak=0.2,
            energy="medium",
            mood="chill",
            silence_gaps=[TimedSegment(start_seconds=5.0, duration_seconds=1.8)],
            silence_ratio=0.15,
        ),
        text=TextSignals(
            overlays=[
                TextOverlay(
                    text="not persisted in result",
                    timestamp_seconds=1.0,
                    duration_seconds=0.7,
                    position="top",
                    confidence=88.0,
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
            frames_analyzed=6,
            has_motion=False,
            motion_score=0.01,
            has_face=False,
            face_frame_ratio=0.0,
            has_text=True,
            cuts_in_hook=0,
        ),
        representative_frame_timestamps_seconds=[0.0, 3.0, 8.0],
    )


@pytest.mark.asyncio
async def test_local_coaching_is_deterministic_and_never_metered() -> None:
    pipeline = _pipeline()
    score = score_pipeline(pipeline)
    service = FeedbackService()

    first = await service.generate(pipeline, score)
    second = await service.generate(pipeline, score)

    assert first == second
    assert first.source == "local_signal_engine"
    assert first.model_id == COACHING_MODEL_VERSION
    assert first.input_tokens == first.output_tokens == 0
    assert first.estimated_model_cost_usd == 0
    assert first.pricing_status == "no_model_call"
    assert 3 <= len(first.feedback) <= 5
    assert any(item.type == "strength" for item in first.feedback)
    assert any(item.issue_code == "weak_opening_motion" for item in first.feedback)
    assert all(0 <= item.start_seconds <= item.end_seconds <= 12 for item in first.feedback)


@pytest.mark.asyncio
async def test_local_coaching_uses_measured_timestamps() -> None:
    pipeline = _pipeline()
    result = await FeedbackService().generate(pipeline, score_pipeline(pipeline))

    silence = next(item for item in result.feedback if item.issue_code == "audio_gap")
    assert silence.start_seconds == 5.0
    assert silence.end_seconds == 6.8
    assert "1.8s" in silence.evidence
