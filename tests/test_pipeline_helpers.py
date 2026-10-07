from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import pipeline
from app.pipeline import (
    AudioSignals,
    MediaMetadata,
    MediaValidationError,
    PipelineDependencyError,
    build_scene_signals,
    detect_scenes,
    no_audio_signals,
    probe_media,
    select_representative_timestamps,
    temporary_pipeline_workspace,
)


def _probe_payload(*, duration: str = "30.0", include_video: bool = True) -> dict:
    streams: list[dict] = []
    if include_video:
        streams.append(
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1080,
                "height": 1920,
                "avg_frame_rate": "30000/1001",
                "duration": duration,
                "tags": {"rotate": "90"},
            }
        )
    streams.append(
        {
            "codec_type": "audio",
            "codec_name": "aac",
            "sample_rate": "48000",
            "channels": 2,
        }
    )
    return {
        "streams": streams,
        "format": {"duration": duration, "format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
    }


def test_models_are_strict_and_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        MediaMetadata(
            duration_seconds=30,  # strict float: an integer must not be coerced
            size_bytes=100,
            format_name="mov,mp4",
            video_codec="h264",
            width=1080,
            height=1920,
            frame_rate=30.0,
            rotation_degrees=0,
            has_audio=False,
            unexpected=True,
        )


def test_probe_media_parses_actual_stream_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"valid-sized-placeholder")

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(_probe_payload()),
            stderr="",
        )

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
    metadata = probe_media(source)

    assert metadata.duration_seconds == 30.0
    assert metadata.size_bytes == source.stat().st_size
    assert metadata.rotation_degrees == 90
    assert metadata.has_audio is True
    assert metadata.audio_codec == "aac"
    assert metadata.frame_rate == pytest.approx(29.97002997)


def test_probe_media_rejects_missing_video_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "audio-only.mp4"
    source.write_bytes(b"placeholder")
    monkeypatch.setattr(
        pipeline.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(_probe_payload(include_video=False)),
            stderr="",
        ),
    )

    with pytest.raises(MediaValidationError) as raised:
        probe_media(source)

    assert raised.value.code == "VIDEO_STREAM_MISSING"


def test_probe_media_rejects_duration_over_90_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "too-long.mov"
    source.write_bytes(b"placeholder")
    monkeypatch.setattr(
        pipeline.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(_probe_payload(duration="90.0011")),
            stderr="",
        ),
    )

    with pytest.raises(MediaValidationError) as raised:
        probe_media(source)

    assert raised.value.code == "VIDEO_TOO_LONG"


def test_probe_media_rejects_size_over_100_mib(tmp_path: Path) -> None:
    source = tmp_path / "too-large.mp4"
    with source.open("wb") as output:
        output.truncate(pipeline.MAX_VIDEO_BYTES + 1)

    with pytest.raises(MediaValidationError) as raised:
        probe_media(source)

    assert raised.value.code == "VIDEO_TOO_LARGE"


def test_scene_helper_normalizes_cuts_and_marks_dead_air() -> None:
    signals = build_scene_signals(12.0, [0.0, 2.0, 2.0, 6.5, 99.0])

    assert signals.cuts_seconds == [2.0, 6.5]
    assert signals.clip_lengths_seconds == [2.0, 4.5, 5.5]
    assert len(signals.dead_air_segments) == 2
    assert signals.dead_air_segments[-1].start_seconds == 6.5


def test_timestamp_selection_is_dense_in_hook_capped_and_ordered() -> None:
    timestamps = select_representative_timestamps(
        30.0,
        [4.0, 7.0, 9.0, 12.0, 18.0, 25.0],
        max_frames=10,
    )

    assert timestamps[:7] == [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
    assert len(timestamps) == 10
    assert timestamps == sorted(set(timestamps))
    assert all(0.0 <= timestamp < 30.0 for timestamp in timestamps)


def test_no_audio_is_distinct_from_a_silent_audio_track() -> None:
    missing = no_audio_signals()
    silent = AudioSignals(
        has_audio=True,
        bpm=None,
        rms_energy_mean=0.0,
        rms_energy_peak=0.0,
        energy="low",
        mood="melancholic",
        silence_gaps=[],
        silence_ratio=1.0,
    )

    assert missing.has_audio is False
    assert missing.energy is None
    assert missing.silence_ratio == 0.0
    assert silent.has_audio is True
    assert silent.energy == "low"


def test_optional_scene_dependency_fails_at_call_time_not_import_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = pipeline.importlib.import_module

    def fake_import(name: str, package: str | None = None) -> object:
        if name == "scenedetect":
            raise ModuleNotFoundError(name)
        return real_import(name, package)

    monkeypatch.setattr(pipeline.importlib, "import_module", fake_import)

    with pytest.raises(PipelineDependencyError) as raised:
        detect_scenes("ignored.mp4", duration_seconds=10.0)

    assert raised.value.dependency == "scenedetect"
    assert "scenedetect[opencv]" in raised.value.install_hint


def test_temporary_workspace_is_removed_after_an_error(tmp_path: Path) -> None:
    captured: Path | None = None
    with pytest.raises(RuntimeError):
        with temporary_pipeline_workspace(tmp_path) as workspace:
            captured = workspace
            (workspace / "frame.jpg").write_bytes(b"temporary")
            raise RuntimeError("simulated pipeline failure")

    assert captured is not None
    assert not captured.exists()


def test_feedback_keyframes_remain_caller_owned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.pipeline import (
        HookSignals,
        PipelineV1,
        TextSignals,
        extract_feedback_keyframes,
    )

    source = tmp_path / "source.mp4"
    source.write_bytes(b"placeholder")
    metadata = MediaMetadata(
        duration_seconds=10.0,
        size_bytes=source.stat().st_size,
        format_name="mov,mp4",
        video_codec="h264",
        width=720,
        height=1280,
        frame_rate=30.0,
        rotation_degrees=0,
        has_audio=False,
    )
    scenes = build_scene_signals(10.0, [2.0, 5.0, 8.0])
    result = PipelineV1(
        metadata=metadata,
        scenes=scenes,
        audio=no_audio_signals(),
        text=TextSignals(
            overlays=[],
            frames_analyzed=8,
            frames_with_text=0,
            readable_overlay_ratio=0.0,
            has_text_in_hook=False,
        ),
        hook=HookSignals(
            duration_analyzed_seconds=3.0,
            frames_analyzed=7,
            has_motion=True,
            motion_score=0.08,
            has_face=False,
            face_frame_ratio=0.0,
            has_text=False,
            cuts_in_hook=1,
        ),
        representative_frame_timestamps_seconds=[0.0, 1.0, 2.0, 5.0, 8.0],
    )

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        Path(args[-1]).write_bytes(b"jpeg")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
    output = tmp_path / "feedback-frames"
    frames = extract_feedback_keyframes(source, result, output, max_frames=4)

    assert len(frames) == 4
    assert output.exists()
    assert all(frame.path.exists() for frame in frames)
