from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from app.pipeline import (
    HookSignals,
    MediaMetadata,
    MediaValidationError,
    PipelineError,
    PipelineV1,
    TextSignals,
    build_scene_signals,
    no_audio_signals,
)
from app.pipeline_runner import run_pipeline_isolated


def _successful_runner(*args: Any, **kwargs: Any) -> PipelineV1:
    return PipelineV1(
        metadata=MediaMetadata(
            duration_seconds=2.0,
            size_bytes=128,
            format_name="mov,mp4",
            video_codec="h264",
            width=720,
            height=1280,
            frame_rate=30.0,
            rotation_degrees=0,
            has_audio=False,
        ),
        scenes=build_scene_signals(2.0, []),
        audio=no_audio_signals(),
        text=TextSignals(
            overlays=[],
            frames_analyzed=1,
            frames_with_text=0,
            readable_overlay_ratio=0.0,
            has_text_in_hook=False,
        ),
        hook=HookSignals(
            duration_analyzed_seconds=2.0,
            frames_analyzed=1,
            has_motion=False,
            motion_score=0.0,
            has_face=False,
            face_frame_ratio=0.0,
            has_text=False,
            cuts_in_hook=0,
        ),
        representative_frame_timestamps_seconds=[0.0],
    )


def _slow_runner(*args: Any, **kwargs: Any) -> PipelineV1:
    time.sleep(10)
    return _successful_runner()


def _invalid_media_runner(*args: Any, **kwargs: Any) -> PipelineV1:
    raise MediaValidationError("private child detail", code="VIDEO_TOO_LONG")


def test_isolated_pipeline_returns_validated_schema(tmp_path: Path) -> None:
    result = run_pipeline_isolated(
        tmp_path / "video.mp4",
        workspace_root=tmp_path / "workspace",
        timeout_seconds=10,
        runner=_successful_runner,
    )

    assert result.pipeline_version == "pipeline-v1"
    assert result.metadata.duration_seconds == 2.0


def test_isolated_pipeline_kills_work_at_timeout(tmp_path: Path) -> None:
    started = time.monotonic()
    with pytest.raises(PipelineError) as caught:
        run_pipeline_isolated(
            tmp_path / "video.mp4",
            workspace_root=tmp_path / "workspace",
            timeout_seconds=0.5,
            runner=_slow_runner,
        )

    assert caught.value.code == "PIPELINE_TIMEOUT"
    assert time.monotonic() - started < 5


def test_isolated_pipeline_preserves_stable_media_error_code(tmp_path: Path) -> None:
    with pytest.raises(MediaValidationError) as caught:
        run_pipeline_isolated(
            tmp_path / "video.mp4",
            workspace_root=tmp_path / "workspace",
            timeout_seconds=10,
            runner=_invalid_media_runner,
        )

    assert caught.value.code == "VIDEO_TOO_LONG"
    assert "private child detail" not in str(caught.value)
