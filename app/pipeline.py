"""Local, deterministic media analysis for ReelMate.

The module intentionally imports only lightweight dependencies at import time.
FFmpeg/ffprobe and the optional scientific/computer-vision packages are loaded
or invoked only when their corresponding pipeline stage runs.  This keeps the
API process importable even when it is deployed without worker dependencies.

Temporary frame and audio artifacts never appear in :class:`PipelineV1`; the
orchestrator removes its workspace on every exit path.
"""

from __future__ import annotations

import importlib
import json
import math
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from statistics import median
from types import ModuleType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

MAX_DURATION_SECONDS = 90.0
MAX_VIDEO_BYTES = 100_000_000
HOOK_DURATION_SECONDS = 3.0
DEAD_AIR_SECONDS = 4.0
MIN_TEXT_DURATION_SECONDS = 1.2
MIN_SILENCE_SECONDS = 1.5
PIPELINE_VERSION: Literal["pipeline-v1"] = "pipeline-v1"


class PipelineError(RuntimeError):
    """Base class for stable, user-safe pipeline failures."""

    code = "PIPELINE_FAILED"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code or self.code


class PipelineDependencyError(PipelineError):
    """Raised when a worker-only package or executable is unavailable."""

    code = "PIPELINE_DEPENDENCY_MISSING"

    def __init__(self, dependency: str, install_hint: str) -> None:
        self.dependency = dependency
        self.install_hint = install_hint
        super().__init__(f"Media pipeline dependency '{dependency}' is unavailable. {install_hint}")


class MediaValidationError(PipelineError):
    """An uploaded object is not a supported, safe-to-process video."""

    code = "INVALID_VIDEO"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class TimedSegment(_StrictModel):
    start_seconds: float = Field(ge=0.0)
    duration_seconds: float = Field(gt=0.0)

    @property
    def end_seconds(self) -> float:
        return self.start_seconds + self.duration_seconds


class MediaMetadata(_StrictModel):
    duration_seconds: float = Field(gt=0.0, le=MAX_DURATION_SECONDS)
    size_bytes: int = Field(gt=0, le=MAX_VIDEO_BYTES)
    format_name: str = Field(min_length=1, max_length=128)
    video_codec: str = Field(min_length=1, max_length=64)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    frame_rate: float = Field(gt=0.0, le=1000.0)
    rotation_degrees: int = 0
    has_audio: bool
    audio_codec: str | None = Field(default=None, max_length=64)
    audio_sample_rate: int | None = Field(default=None, gt=0)
    audio_channels: int | None = Field(default=None, gt=0)

    @field_validator("rotation_degrees")
    @classmethod
    def _valid_rotation(cls, value: int) -> int:
        normalized = value % 360
        if normalized not in {0, 90, 180, 270}:
            raise ValueError("rotation must resolve to 0, 90, 180, or 270 degrees")
        return normalized

    @model_validator(mode="after")
    def _audio_fields_match_stream_presence(self) -> MediaMetadata:
        if not self.has_audio and any(
            value is not None
            for value in (self.audio_codec, self.audio_sample_rate, self.audio_channels)
        ):
            raise ValueError("audio metadata is not allowed when has_audio is false")
        return self


class SceneSignals(_StrictModel):
    cuts_seconds: list[float] = Field(default_factory=list)
    clip_lengths_seconds: list[float] = Field(min_length=1)
    average_clip_length_seconds: float = Field(gt=0.0)
    dead_air_segments: list[TimedSegment] = Field(default_factory=list)

    @field_validator("cuts_seconds", "clip_lengths_seconds")
    @classmethod
    def _finite_non_negative_values(cls, values: list[float]) -> list[float]:
        if any(not math.isfinite(value) or value < 0.0 for value in values):
            raise ValueError("scene timestamps and lengths must be finite and non-negative")
        return values

    @model_validator(mode="after")
    def _scene_shape_is_consistent(self) -> SceneSignals:
        if self.cuts_seconds != sorted(set(self.cuts_seconds)):
            raise ValueError("scene cuts must be sorted and unique")
        if len(self.clip_lengths_seconds) != len(self.cuts_seconds) + 1:
            raise ValueError("clip_lengths_seconds must contain one entry per scene")
        calculated_average = sum(self.clip_lengths_seconds) / len(self.clip_lengths_seconds)
        if not math.isclose(
            calculated_average,
            self.average_clip_length_seconds,
            rel_tol=0.0,
            abs_tol=0.002,
        ):
            raise ValueError("average clip length does not match clip lengths")
        return self


EnergyLevel = Literal["low", "medium", "high"]
Mood = Literal["upbeat", "chill", "intense", "melancholic"]


class AudioSignals(_StrictModel):
    has_audio: bool
    bpm: float | None = Field(default=None, gt=0.0, le=400.0)
    beat_timestamps_seconds: list[float] = Field(default_factory=list)
    rms_energy_mean: float | None = Field(default=None, ge=0.0, le=1.0)
    rms_energy_peak: float | None = Field(default=None, ge=0.0, le=1.0)
    energy: EnergyLevel | None = None
    mood: Mood | None = None
    silence_gaps: list[TimedSegment] = Field(default_factory=list)
    silence_ratio: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _no_invented_audio_signals(self) -> AudioSignals:
        if any(not math.isfinite(value) or value < 0.0 for value in self.beat_timestamps_seconds):
            raise ValueError("beat timestamps must be finite and non-negative")
        if self.beat_timestamps_seconds != sorted(set(self.beat_timestamps_seconds)):
            raise ValueError("beat timestamps must be sorted and unique")
        if not self.has_audio:
            if any(
                value is not None
                for value in (
                    self.bpm,
                    self.rms_energy_mean,
                    self.rms_energy_peak,
                    self.energy,
                    self.mood,
                )
            ):
                raise ValueError("derived audio values require an audio stream")
            if self.beat_timestamps_seconds or self.silence_gaps or self.silence_ratio != 0.0:
                raise ValueError("a missing audio stream is not the same as silence")
        return self


TextPosition = Literal["top", "middle", "bottom"]


class TextOverlay(_StrictModel):
    text: str = Field(min_length=1, max_length=200)
    timestamp_seconds: float = Field(ge=0.0)
    duration_seconds: float = Field(gt=0.0)
    position: TextPosition
    confidence: float = Field(ge=0.0, le=100.0)
    flagged: bool


class TextSignals(_StrictModel):
    overlays: list[TextOverlay] = Field(default_factory=list)
    frames_analyzed: int = Field(ge=0)
    frames_with_text: int = Field(ge=0)
    readable_overlay_ratio: float = Field(ge=0.0, le=1.0)
    has_text_in_hook: bool

    @model_validator(mode="after")
    def _valid_frame_counts(self) -> TextSignals:
        if self.frames_with_text > self.frames_analyzed:
            raise ValueError("frames_with_text cannot exceed frames_analyzed")
        if not self.overlays and self.readable_overlay_ratio != 0.0:
            raise ValueError("readability must be zero when there are no overlays")
        return self


class HookSignals(_StrictModel):
    duration_analyzed_seconds: float = Field(gt=0.0, le=HOOK_DURATION_SECONDS)
    frames_analyzed: int = Field(ge=0)
    has_motion: bool
    motion_score: float = Field(ge=0.0, le=1.0)
    has_face: bool
    face_frame_ratio: float = Field(ge=0.0, le=1.0)
    has_text: bool
    cuts_in_hook: int = Field(ge=0)


class PipelineV1(_StrictModel):
    """Versioned, persistence-safe output of local video analysis."""

    schema_version: Literal["1"] = "1"
    pipeline_version: Literal["pipeline-v1"] = PIPELINE_VERSION
    metadata: MediaMetadata
    scenes: SceneSignals
    audio: AudioSignals
    text: TextSignals
    hook: HookSignals
    representative_frame_timestamps_seconds: list[float] = Field(default_factory=list)

    @field_validator("representative_frame_timestamps_seconds")
    @classmethod
    def _ordered_frame_timestamps(cls, values: list[float]) -> list[float]:
        if any(not math.isfinite(value) or value < 0.0 for value in values):
            raise ValueError("frame timestamps must be finite and non-negative")
        if values != sorted(set(values)):
            raise ValueError("frame timestamps must be sorted and unique")
        return values

    @model_validator(mode="after")
    def _signals_fit_media(self) -> PipelineV1:
        duration = self.metadata.duration_seconds
        if self.metadata.has_audio != self.audio.has_audio:
            raise ValueError("metadata and audio stream presence disagree")
        if any(value >= duration for value in self.scenes.cuts_seconds):
            raise ValueError("scene cuts must occur before the video ends")
        if not math.isclose(
            sum(self.scenes.clip_lengths_seconds),
            duration,
            rel_tol=0.0,
            abs_tol=0.02,
        ):
            raise ValueError("scene lengths must cover the video duration")
        if any(value > duration for value in self.representative_frame_timestamps_seconds):
            raise ValueError("frame timestamp exceeds video duration")
        for segment in [
            *self.scenes.dead_air_segments,
            *self.audio.silence_gaps,
        ]:
            if segment.end_seconds > duration + 0.02:
                raise ValueError("timed segment exceeds video duration")
        if any(value > duration for value in self.audio.beat_timestamps_seconds):
            raise ValueError("beat timestamp exceeds video duration")
        for overlay in self.text.overlays:
            if overlay.timestamp_seconds + overlay.duration_seconds > duration + 0.02:
                raise ValueError("text overlay exceeds video duration")
        return self


@dataclass(frozen=True, slots=True)
class ExtractedFrame:
    """A temporary image and its source timestamp (never persisted)."""

    timestamp_seconds: float
    path: Path


@dataclass(frozen=True, slots=True)
class _OCRSample:
    timestamp_seconds: float
    text: str
    position: TextPosition
    confidence: float


def _optional_module(name: str, install_hint: str) -> ModuleType:
    try:
        return importlib.import_module(name)
    except (ImportError, ModuleNotFoundError) as exc:
        raise PipelineDependencyError(name, install_hint) from exc


def _run_media_command(
    args: list[str],
    *,
    dependency: str,
    install_hint: str,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    try:
        # Arguments are passed as an argv list with shell=False. The worker
        # controls the executable and output paths; filenames cannot inject
        # flags or shell syntax.
        result = subprocess.run(  # noqa: S603
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise PipelineDependencyError(dependency, install_hint) from exc
    except subprocess.TimeoutExpired as exc:
        raise PipelineError(
            f"{dependency} exceeded its {timeout_seconds:g}-second time limit.",
            code="MEDIA_TOOL_TIMEOUT",
        ) from exc
    if result.returncode != 0:
        raise PipelineError(
            f"{dependency} could not process the uploaded media.",
            code="MEDIA_TOOL_FAILED",
        )
    return result


def _positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0.0 else None


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _parse_frame_rate(value: Any) -> float | None:
    if isinstance(value, str) and "/" in value:
        numerator, denominator = value.split("/", 1)
        top = _positive_float(numerator)
        bottom = _positive_float(denominator)
        if top is None or bottom is None:
            return None
        return top / bottom
    return _positive_float(value)


def _rotation_from_stream(stream: dict[str, Any]) -> int:
    candidates: list[Any] = [stream.get("tags", {}).get("rotate")]
    candidates.extend(
        side_data.get("rotation")
        for side_data in stream.get("side_data_list", [])
        if isinstance(side_data, dict)
    )
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            return round(float(candidate)) % 360
        except (TypeError, ValueError):
            continue
    return 0


def _metadata_from_probe(payload: dict[str, Any], *, actual_size_bytes: int) -> MediaMetadata:
    streams = payload.get("streams")
    if not isinstance(streams, list):
        raise MediaValidationError(
            "The upload does not contain readable media streams.",
            code="VIDEO_STREAM_MISSING",
        )
    video_stream = next(
        (
            stream
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "video"
        ),
        None,
    )
    if video_stream is None:
        raise MediaValidationError(
            "The upload must contain a video stream.", code="VIDEO_STREAM_MISSING"
        )

    format_data = payload.get("format")
    if not isinstance(format_data, dict):
        format_data = {}
    duration = _positive_float(video_stream.get("duration")) or _positive_float(
        format_data.get("duration")
    )
    if duration is None:
        raise MediaValidationError(
            "The video duration could not be determined.", code="VIDEO_DURATION_INVALID"
        )
    if duration > MAX_DURATION_SECONDS:
        raise MediaValidationError("Video must be 90 seconds or shorter.", code="VIDEO_TOO_LONG")
    if actual_size_bytes <= 0:
        raise MediaValidationError("The uploaded video is empty.", code="VIDEO_EMPTY")
    if actual_size_bytes > MAX_VIDEO_BYTES:
        raise MediaValidationError("Video must be 100 MB or smaller.", code="VIDEO_TOO_LARGE")

    format_name = str(format_data.get("format_name") or "unknown")
    accepted_formats = {part.strip().lower() for part in format_name.split(",")}
    if not accepted_formats.intersection({"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}):
        raise MediaValidationError(
            "Video must use an MP4 or MOV container.", code="VIDEO_FORMAT_UNSUPPORTED"
        )

    width = _positive_int(video_stream.get("width"))
    height = _positive_int(video_stream.get("height"))
    frame_rate = _parse_frame_rate(video_stream.get("avg_frame_rate"))
    if frame_rate is None:
        frame_rate = _parse_frame_rate(video_stream.get("r_frame_rate"))
    codec = str(video_stream.get("codec_name") or "").strip()
    if width is None or height is None or frame_rate is None or not codec:
        raise MediaValidationError(
            "The video stream metadata is incomplete.", code="VIDEO_METADATA_INVALID"
        )

    audio_stream = next(
        (
            stream
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "audio"
        ),
        None,
    )
    try:
        return MediaMetadata(
            duration_seconds=float(duration),
            size_bytes=int(actual_size_bytes),
            format_name=format_name[:128],
            video_codec=codec[:64],
            width=width,
            height=height,
            frame_rate=float(frame_rate),
            rotation_degrees=_rotation_from_stream(video_stream),
            has_audio=audio_stream is not None,
            audio_codec=(
                str(audio_stream.get("codec_name") or "unknown")[:64]
                if audio_stream is not None
                else None
            ),
            audio_sample_rate=(
                _positive_int(audio_stream.get("sample_rate")) if audio_stream is not None else None
            ),
            audio_channels=(
                _positive_int(audio_stream.get("channels")) if audio_stream is not None else None
            ),
        )
    except ValidationError as exc:
        raise MediaValidationError(
            "The video stream metadata is invalid.", code="VIDEO_METADATA_INVALID"
        ) from exc


def validate_metadata(metadata: MediaMetadata) -> None:
    """Apply worker ingress limits to already-parsed metadata."""

    if metadata.duration_seconds > MAX_DURATION_SECONDS:
        raise MediaValidationError("Video must be 90 seconds or shorter.", code="VIDEO_TOO_LONG")
    if metadata.size_bytes > MAX_VIDEO_BYTES:
        raise MediaValidationError("Video must be 100 MB or smaller.", code="VIDEO_TOO_LARGE")
    if metadata.width <= 0 or metadata.height <= 0 or not metadata.video_codec:
        raise MediaValidationError(
            "The upload must contain a valid video stream.",
            code="VIDEO_STREAM_MISSING",
        )


def probe_media(
    video_path: str | Path,
    *,
    ffprobe_binary: str = "ffprobe",
    timeout_seconds: float = 30.0,
) -> MediaMetadata:
    """Read and validate actual container/stream metadata with ffprobe."""

    path = Path(video_path)
    if not path.is_file():
        raise MediaValidationError(
            "The uploaded video file is unavailable.", code="VIDEO_FILE_MISSING"
        )
    size_bytes = path.stat().st_size
    if size_bytes > MAX_VIDEO_BYTES:
        raise MediaValidationError("Video must be 100 MB or smaller.", code="VIDEO_TOO_LARGE")
    if size_bytes <= 0:
        raise MediaValidationError("The uploaded video is empty.", code="VIDEO_EMPTY")

    result = _run_media_command(
        [
            ffprobe_binary,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        dependency="ffprobe",
        install_hint="Install the FFmpeg system package on the worker image.",
        timeout_seconds=timeout_seconds,
    )
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise MediaValidationError(
            "The video metadata could not be decoded.", code="VIDEO_METADATA_INVALID"
        ) from exc
    if not isinstance(payload, dict):
        raise MediaValidationError("The video metadata is invalid.", code="VIDEO_METADATA_INVALID")
    metadata = _metadata_from_probe(payload, actual_size_bytes=size_bytes)
    validate_metadata(metadata)
    return metadata


def build_scene_signals(
    duration_seconds: float,
    cuts_seconds: Sequence[float],
    *,
    dead_air_seconds: float = DEAD_AIR_SECONDS,
) -> SceneSignals:
    """Normalize cut timestamps into complete scene-level signals."""

    if not math.isfinite(duration_seconds) or duration_seconds <= 0.0:
        raise ValueError("duration_seconds must be finite and positive")
    normalized = sorted(
        {
            round(float(cut), 3)
            for cut in cuts_seconds
            if math.isfinite(float(cut)) and 0.0 < float(cut) < duration_seconds
        }
    )
    boundaries = [0.0, *normalized, float(duration_seconds)]
    lengths = [
        round(boundaries[index + 1] - boundaries[index], 3) for index in range(len(boundaries) - 1)
    ]
    # Rounding individual clips can move the sum by a few milliseconds. Keep
    # the final clip authoritative so PipelineV1 always covers the source.
    lengths[-1] = round(float(duration_seconds) - sum(lengths[:-1]), 3)
    dead_air = [
        TimedSegment(
            start_seconds=float(boundaries[index]),
            duration_seconds=float(length),
        )
        for index, length in enumerate(lengths)
        if length > dead_air_seconds
    ]
    return SceneSignals(
        cuts_seconds=[float(value) for value in normalized],
        clip_lengths_seconds=[float(value) for value in lengths],
        average_clip_length_seconds=float(round(sum(lengths) / len(lengths), 3)),
        dead_air_segments=dead_air,
    )


def detect_scenes(
    video_path: str | Path,
    *,
    duration_seconds: float,
    threshold: float = 27.0,
) -> SceneSignals:
    """Detect content cuts with PySceneDetect, loaded lazily."""

    scenedetect = _optional_module(
        "scenedetect", "Install the 'scenedetect[opencv]' worker dependency."
    )
    detectors = _optional_module(
        "scenedetect.detectors",
        "Install the 'scenedetect[opencv]' worker dependency.",
    )
    try:
        video = scenedetect.open_video(str(video_path))
        manager = scenedetect.SceneManager()
        manager.add_detector(detectors.ContentDetector(threshold=float(threshold)))
        manager.detect_scenes(video=video, show_progress=False)
        scene_list = manager.get_scene_list(start_in_scene=True)
        cuts = [float(scene[0].get_seconds()) for scene in scene_list[1:]]
    except PipelineError:
        raise
    except Exception as exc:
        raise PipelineError(
            "Scene detection could not process the uploaded video.",
            code="SCENE_DETECTION_FAILED",
        ) from exc
    return build_scene_signals(duration_seconds, cuts)


def _pick_evenly(values: Sequence[float], count: int) -> list[float]:
    if count <= 0 or not values:
        return []
    if count >= len(values):
        return list(values)
    if count == 1:
        return [values[len(values) // 2]]
    indices = {round(index * (len(values) - 1) / (count - 1)) for index in range(count)}
    return [values[index] for index in sorted(indices)]


def select_representative_timestamps(
    duration_seconds: float,
    cuts_seconds: Sequence[float] = (),
    *,
    max_frames: int = 24,
    hook_interval_seconds: float = 0.5,
    general_interval_seconds: float = 3.0,
) -> list[float]:
    """Select dense hook, scene-boundary, and uniform frame timestamps."""

    if not math.isfinite(duration_seconds) or duration_seconds <= 0.0:
        raise ValueError("duration_seconds must be finite and positive")
    if max_frames <= 0:
        raise ValueError("max_frames must be positive")
    if hook_interval_seconds <= 0.0 or general_interval_seconds <= 0.0:
        raise ValueError("sampling intervals must be positive")

    last_timestamp = max(0.0, duration_seconds - 0.05)
    hook_end = min(HOOK_DURATION_SECONDS, last_timestamp)
    hook_values: list[float] = []
    value = 0.0
    while value <= hook_end + 1e-9:
        hook_values.append(round(value, 3))
        value += hook_interval_seconds

    scene_values = sorted(
        {
            round(min(max(float(cut), 0.0), last_timestamp), 3)
            for cut in cuts_seconds
            if math.isfinite(float(cut)) and 0.0 <= float(cut) < duration_seconds
        }
    )
    uniform_values: list[float] = []
    value = HOOK_DURATION_SECONDS + general_interval_seconds
    while value < last_timestamp:
        uniform_values.append(round(value, 3))
        value += general_interval_seconds
    uniform_values.append(round(last_timestamp, 3))

    hook = sorted(set(hook_values))
    if len(hook) >= max_frames:
        return sorted(_pick_evenly(hook, max_frames))
    remaining_candidates = sorted((set(scene_values) | set(uniform_values)) - set(hook))
    selected = hook + _pick_evenly(remaining_candidates, max_frames - len(hook))
    return sorted(set(selected))


def extract_representative_frames(
    video_path: str | Path,
    output_directory: str | Path,
    timestamps_seconds: Sequence[float],
    *,
    ffmpeg_binary: str = "ffmpeg",
    max_dimension: int = 768,
    timeout_per_frame_seconds: float = 20.0,
) -> list[ExtractedFrame]:
    """Extract capped, downscaled JPEG frames with FFmpeg."""

    if max_dimension <= 0:
        raise ValueError("max_dimension must be positive")
    output_dir = Path(output_directory)
    output_dir.mkdir(parents=True, exist_ok=True)
    frames: list[ExtractedFrame] = []
    for index, raw_timestamp in enumerate(timestamps_seconds):
        timestamp = float(raw_timestamp)
        if not math.isfinite(timestamp) or timestamp < 0.0:
            raise ValueError("frame timestamps must be finite and non-negative")
        output_path = output_dir / f"frame_{index:03d}_{round(timestamp * 1000):08d}ms.jpg"
        _run_media_command(
            [
                ffmpeg_binary,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(video_path),
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-vf",
                (
                    f"scale=w={max_dimension}:h={max_dimension}:"
                    "force_original_aspect_ratio=decrease:force_divisible_by=2"
                ),
                "-q:v",
                "4",
                "-y",
                str(output_path),
            ],
            dependency="ffmpeg",
            install_hint="Install the FFmpeg system package on the worker image.",
            timeout_seconds=timeout_per_frame_seconds,
        )
        if not output_path.is_file() or output_path.stat().st_size <= 0:
            raise PipelineError(
                "FFmpeg did not create a representative frame.",
                code="FRAME_EXTRACTION_FAILED",
            )
        frames.append(ExtractedFrame(timestamp_seconds=timestamp, path=output_path))
    return frames


def extract_feedback_keyframes(
    video_path: str | Path,
    pipeline: PipelineV1,
    output_directory: str | Path,
    *,
    max_frames: int = 8,
    ffmpeg_binary: str = "ffmpeg",
) -> list[ExtractedFrame]:
    """Extract a smaller, caller-owned frame set for structured AI feedback.

    Unlike :func:`run_pipeline`, this helper deliberately does not remove
    ``output_directory``. The worker owns that directory and must delete it in
    its surrounding ``finally`` block after the feedback request completes.
    No frame path is added to the persistence-safe PipelineV1 object.
    """

    timestamps = select_representative_timestamps(
        pipeline.metadata.duration_seconds,
        pipeline.scenes.cuts_seconds,
        max_frames=max_frames,
    )
    return extract_representative_frames(
        video_path,
        output_directory,
        timestamps,
        ffmpeg_binary=ffmpeg_binary,
    )


def extract_audio(
    video_path: str | Path,
    output_path: str | Path,
    *,
    ffmpeg_binary: str = "ffmpeg",
    sample_rate: int = 22_050,
    timeout_seconds: float = 60.0,
) -> Path:
    """Extract mono PCM audio suitable for deterministic local analysis."""

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _run_media_command(
        [
            ffmpeg_binary,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            "-y",
            str(destination),
        ],
        dependency="ffmpeg",
        install_hint="Install the FFmpeg system package on the worker image.",
        timeout_seconds=timeout_seconds,
    )
    if not destination.is_file() or destination.stat().st_size <= 44:
        raise PipelineError(
            "The audio stream could not be extracted.", code="AUDIO_EXTRACTION_FAILED"
        )
    return destination


def classify_mood(bpm: float | None, energy: EnergyLevel) -> Mood:
    """Map measured tempo/energy to the stable v1 coaching vocabulary."""

    tempo = bpm or 0.0
    if tempo > 120.0 and energy == "high":
        return "upbeat"
    if tempo < 90.0 and energy == "low":
        return "melancholic"
    if tempo > 120.0 and energy == "low":
        return "chill"
    return "intense"


def _silence_segments(
    non_silent_intervals: Sequence[Sequence[int]],
    *,
    sample_rate: int,
    duration_seconds: float,
    minimum_seconds: float = MIN_SILENCE_SECONDS,
) -> list[TimedSegment]:
    cursor = 0.0
    gaps: list[TimedSegment] = []
    for interval in non_silent_intervals:
        if len(interval) < 2:
            continue
        start = max(0.0, min(float(interval[0]) / sample_rate, duration_seconds))
        end = max(start, min(float(interval[1]) / sample_rate, duration_seconds))
        if start - cursor >= minimum_seconds:
            gaps.append(
                TimedSegment(
                    start_seconds=float(round(cursor, 3)),
                    duration_seconds=float(round(start - cursor, 3)),
                )
            )
        cursor = max(cursor, end)
    if duration_seconds - cursor >= minimum_seconds:
        gaps.append(
            TimedSegment(
                start_seconds=float(round(cursor, 3)),
                duration_seconds=float(round(duration_seconds - cursor, 3)),
            )
        )
    return gaps


def no_audio_signals() -> AudioSignals:
    """Represent an absent audio stream without pretending it is silence."""

    return AudioSignals(
        has_audio=False,
        bpm=None,
        beat_timestamps_seconds=[],
        rms_energy_mean=None,
        rms_energy_peak=None,
        energy=None,
        mood=None,
        silence_gaps=[],
        silence_ratio=0.0,
    )


def analyze_audio(
    audio_path: str | Path,
    *,
    duration_seconds: float,
    silence_top_db: float = 35.0,
) -> AudioSignals:
    """Measure tempo, RMS energy, and long silence with librosa."""

    librosa = _optional_module(
        "librosa", "Install the 'librosa' and 'soundfile' worker dependencies."
    )
    numpy = _optional_module("numpy", "Install the 'numpy' worker dependency.")
    try:
        samples, sample_rate = librosa.load(str(audio_path), sr=22_050, mono=True)
        sample_count = int(numpy.asarray(samples).size)
        if sample_count == 0:
            rms_mean = 0.0
            rms_peak = 0.0
            tempo: float | None = None
            beat_timestamps: list[float] = []
            non_silent: Sequence[Sequence[int]] = []
        else:
            rms_values = numpy.asarray(librosa.feature.rms(y=samples)).reshape(-1)
            rms_mean = float(numpy.mean(rms_values)) if rms_values.size else 0.0
            rms_peak = float(numpy.max(rms_values)) if rms_values.size else 0.0
            tempo_raw, beat_frames = librosa.beat.beat_track(y=samples, sr=sample_rate)
            tempo_values = numpy.asarray(tempo_raw).reshape(-1)
            beat_count = int(numpy.asarray(beat_frames).size)
            candidate = float(tempo_values[0]) if tempo_values.size else 0.0
            tempo = candidate if beat_count >= 2 and 30.0 <= candidate <= 240.0 else None
            if tempo is None:
                beat_timestamps = []
            else:
                beat_times = numpy.asarray(
                    librosa.frames_to_time(beat_frames, sr=sample_rate)
                ).reshape(-1)
                beat_timestamps = sorted(
                    {
                        float(round(float(value), 3))
                        for value in beat_times
                        if 0.0 <= float(value) <= duration_seconds
                    }
                )
            non_silent = librosa.effects.split(samples, top_db=float(silence_top_db))
    except PipelineError:
        raise
    except Exception as exc:
        raise PipelineError(
            "Audio analysis could not process the extracted track.",
            code="AUDIO_ANALYSIS_FAILED",
        ) from exc

    rms_mean = min(max(rms_mean, 0.0), 1.0)
    rms_peak = min(max(rms_peak, 0.0), 1.0)
    energy: EnergyLevel
    if rms_mean < 0.025:
        energy = "low"
    elif rms_mean >= 0.10:
        energy = "high"
    else:
        energy = "medium"
    gaps = _silence_segments(
        non_silent,
        sample_rate=int(sample_rate),
        duration_seconds=duration_seconds,
    )
    silence_ratio = min(
        1.0,
        sum(segment.duration_seconds for segment in gaps) / duration_seconds,
    )
    return AudioSignals(
        has_audio=True,
        bpm=float(round(tempo, 3)) if tempo is not None else None,
        beat_timestamps_seconds=beat_timestamps,
        rms_energy_mean=float(round(rms_mean, 6)),
        rms_energy_peak=float(round(rms_peak, 6)),
        energy=energy,
        mood=classify_mood(tempo, energy),
        silence_gaps=gaps,
        silence_ratio=float(round(silence_ratio, 6)),
    )


def _text_position(center_y: float, image_height: int) -> TextPosition:
    ratio = center_y / max(image_height, 1)
    if ratio < 1.0 / 3.0:
        return "top"
    if ratio < 2.0 / 3.0:
        return "middle"
    return "bottom"


def _clean_ocr_text(value: str) -> str:
    printable = "".join(character for character in value if character.isprintable())
    return re.sub(r"\s+", " ", printable).strip()[:200]


def _ocr_sample(
    frame: ExtractedFrame, cv2: ModuleType, pytesseract: ModuleType
) -> _OCRSample | None:
    image = cv2.imread(str(frame.path))
    if image is None:
        raise PipelineError("An extracted frame could not be decoded.", code="FRAME_DECODE_FAILED")
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    try:
        data = pytesseract.image_to_data(
            rgb, output_type=pytesseract.Output.DICT, config="--psm 11"
        )
    except Exception as exc:
        if exc.__class__.__name__ == "TesseractNotFoundError":
            raise PipelineDependencyError(
                "tesseract",
                "Install the Tesseract system package on the worker image.",
            ) from exc
        raise PipelineError("OCR could not analyze an extracted frame.", code="OCR_FAILED") from exc

    tokens: list[str] = []
    confidences: list[float] = []
    centers: list[float] = []
    raw_text = data.get("text", [])
    for index, raw_token in enumerate(raw_text):
        token = _clean_ocr_text(str(raw_token))
        try:
            confidence = float(data.get("conf", [])[index])
        except (IndexError, TypeError, ValueError):
            continue
        if not token or confidence < 45.0:
            continue
        try:
            top = float(data.get("top", [])[index])
            height = float(data.get("height", [])[index])
        except (IndexError, TypeError, ValueError):
            top = 0.0
            height = 0.0
        tokens.append(token)
        confidences.append(confidence)
        centers.append(top + height / 2.0)
    text = _clean_ocr_text(" ".join(tokens))
    if not text:
        return None
    center_y = sum(centers) / len(centers) if centers else image.shape[0] / 2.0
    return _OCRSample(
        timestamp_seconds=frame.timestamp_seconds,
        text=text,
        position=_text_position(center_y, int(image.shape[0])),
        confidence=float(round(sum(confidences) / len(confidences), 2)),
    )


def _normalized_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _samples_to_overlays(
    samples: Sequence[_OCRSample],
    *,
    all_timestamps: Sequence[float],
    duration_seconds: float,
) -> list[TextOverlay]:
    if not samples:
        return []
    ordered_timestamps = sorted(set(float(value) for value in all_timestamps))
    deltas = [right - left for left, right in pairwise(ordered_timestamps) if right > left]
    exposure = min(1.0, max(0.25, median(deltas) if deltas else 0.75))
    max_join_gap = max(0.75, exposure * 1.75)

    groups: list[list[_OCRSample]] = []
    for sample in sorted(samples, key=lambda item: item.timestamp_seconds):
        if groups:
            previous = groups[-1][-1]
            same_text = _normalized_text(previous.text) == _normalized_text(sample.text)
            close = sample.timestamp_seconds - previous.timestamp_seconds <= max_join_gap
            if same_text and close:
                groups[-1].append(sample)
                continue
        groups.append([sample])

    overlays: list[TextOverlay] = []
    for group in groups:
        first = group[0]
        last = group[-1]
        end = min(duration_seconds, last.timestamp_seconds + exposure)
        duration = max(0.001, end - first.timestamp_seconds)
        confidence = sum(item.confidence for item in group) / len(group)
        positions: tuple[TextPosition, ...] = ("top", "middle", "bottom")
        position = max(
            positions,
            key=lambda candidate: sum(item.position == candidate for item in group),
        )
        overlays.append(
            TextOverlay(
                text=first.text,
                timestamp_seconds=float(round(first.timestamp_seconds, 3)),
                duration_seconds=float(round(duration, 3)),
                position=position,
                confidence=float(round(confidence, 2)),
                flagged=duration < MIN_TEXT_DURATION_SECONDS or confidence < 55.0,
            )
        )
    return overlays


def analyze_text(frames: Sequence[ExtractedFrame], *, duration_seconds: float) -> TextSignals:
    """Run local Tesseract OCR and derive timestamped overlay signals."""

    if not frames:
        return TextSignals(
            overlays=[],
            frames_analyzed=0,
            frames_with_text=0,
            readable_overlay_ratio=0.0,
            has_text_in_hook=False,
        )
    cv2 = _optional_module("cv2", "Install the 'opencv-python-headless' worker dependency.")
    pytesseract = _optional_module(
        "pytesseract",
        "Install the 'pytesseract' package and Tesseract system dependency.",
    )
    samples = [
        sample for frame in frames if (sample := _ocr_sample(frame, cv2, pytesseract)) is not None
    ]
    overlays = _samples_to_overlays(
        samples,
        all_timestamps=[frame.timestamp_seconds for frame in frames],
        duration_seconds=duration_seconds,
    )
    readable = sum(not overlay.flagged for overlay in overlays)
    return TextSignals(
        overlays=overlays,
        frames_analyzed=len(frames),
        frames_with_text=len(samples),
        readable_overlay_ratio=(float(round(readable / len(overlays), 6)) if overlays else 0.0),
        has_text_in_hook=any(
            overlay.timestamp_seconds < HOOK_DURATION_SECONDS for overlay in overlays
        ),
    )


def analyze_hook(
    frames: Sequence[ExtractedFrame],
    *,
    scenes: SceneSignals,
    text: TextSignals,
    duration_seconds: float,
) -> HookSignals:
    """Measure first-three-second motion, face presence, text, and cuts."""

    cv2 = _optional_module("cv2", "Install the 'opencv-python-headless' worker dependency.")
    hook_duration = min(HOOK_DURATION_SECONDS, duration_seconds)
    hook_frames = [frame for frame in frames if frame.timestamp_seconds <= hook_duration + 0.001]
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(str(cascade_path))
    if detector.empty():
        raise PipelineDependencyError(
            "opencv-face-cascade",
            "Install OpenCV with its Haar cascade data on the worker image.",
        )

    previous_gray: Any | None = None
    motion_values: list[float] = []
    face_frames = 0
    decoded_frames = 0
    for frame in hook_frames:
        image = cv2.imread(str(frame.path))
        if image is None:
            raise PipelineError(
                "An extracted hook frame could not be decoded.",
                code="FRAME_DECODE_FAILED",
            )
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if gray.shape[1] > 480:
            target_height = max(1, round(gray.shape[0] * 480 / gray.shape[1]))
            gray = cv2.resize(gray, (480, target_height))
        if previous_gray is not None:
            if previous_gray.shape != gray.shape:
                previous_gray = cv2.resize(previous_gray, (gray.shape[1], gray.shape[0]))
            difference = cv2.absdiff(previous_gray, gray)
            motion_values.append(float(difference.mean()) / 255.0)
        previous_gray = gray
        faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        face_frames += int(len(faces) > 0)
        decoded_frames += 1

    motion_score = (
        min(1.0, max(0.0, sum(motion_values) / len(motion_values))) if motion_values else 0.0
    )
    face_ratio = face_frames / decoded_frames if decoded_frames else 0.0
    return HookSignals(
        duration_analyzed_seconds=float(hook_duration),
        frames_analyzed=decoded_frames,
        has_motion=motion_score >= 0.02,
        motion_score=float(round(motion_score, 6)),
        has_face=face_frames > 0,
        face_frame_ratio=float(round(face_ratio, 6)),
        has_text=text.has_text_in_hook,
        cuts_in_hook=sum(0.0 < cut <= hook_duration for cut in scenes.cuts_seconds),
    )


@contextmanager
def temporary_pipeline_workspace(
    root: str | Path | None = None,
) -> Iterator[Path]:
    """Yield an isolated workspace and recursively clean it on every exit."""

    root_path = Path(root) if root is not None else None
    if root_path is not None:
        root_path.mkdir(parents=True, exist_ok=True)
    workspace = Path(
        tempfile.mkdtemp(
            prefix="reelmate-pipeline-",
            dir=str(root_path) if root_path is not None else None,
        )
    )
    try:
        yield workspace
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def run_pipeline(
    video_path: str | Path,
    *,
    workspace_root: str | Path | None = None,
    max_frames: int = 24,
    ffmpeg_binary: str = "ffmpeg",
    ffprobe_binary: str = "ffprobe",
) -> PipelineV1:
    """Run the complete local PipelineV1 analysis synchronously.

    Worker code should call this CPU/blocking function in its own process (or
    via ``asyncio.to_thread``); it must not run on the FastAPI event loop.
    """

    source = Path(video_path)
    metadata = probe_media(source, ffprobe_binary=ffprobe_binary)
    with temporary_pipeline_workspace(workspace_root) as workspace:
        audio_future: Future[AudioSignals] | None = None
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="reelmate-media") as executor:
            if metadata.has_audio:
                audio_future = executor.submit(
                    _analyze_audio_branch,
                    source,
                    workspace / "audio.wav",
                    metadata.duration_seconds,
                    ffmpeg_binary,
                )

            scenes = detect_scenes(source, duration_seconds=metadata.duration_seconds)
            timestamps = select_representative_timestamps(
                metadata.duration_seconds,
                scenes.cuts_seconds,
                max_frames=max_frames,
            )
            frames = extract_representative_frames(
                source,
                workspace / "frames",
                timestamps,
                ffmpeg_binary=ffmpeg_binary,
            )
            text = analyze_text(frames, duration_seconds=metadata.duration_seconds)
            hook = analyze_hook(
                frames,
                scenes=scenes,
                text=text,
                duration_seconds=metadata.duration_seconds,
            )
            audio = audio_future.result() if audio_future is not None else no_audio_signals()

        return PipelineV1(
            metadata=metadata,
            scenes=scenes,
            audio=audio,
            text=text,
            hook=hook,
            representative_frame_timestamps_seconds=[
                float(frame.timestamp_seconds) for frame in frames
            ],
        )


def _analyze_audio_branch(
    source: Path,
    audio_path: Path,
    duration_seconds: float,
    ffmpeg_binary: str,
) -> AudioSignals:
    extracted = extract_audio(source, audio_path, ffmpeg_binary=ffmpeg_binary)
    return analyze_audio(extracted, duration_seconds=duration_seconds)


__all__ = [
    "DEAD_AIR_SECONDS",
    "HOOK_DURATION_SECONDS",
    "MAX_DURATION_SECONDS",
    "MAX_VIDEO_BYTES",
    "PIPELINE_VERSION",
    "AudioSignals",
    "ExtractedFrame",
    "HookSignals",
    "MediaMetadata",
    "MediaValidationError",
    "PipelineDependencyError",
    "PipelineError",
    "PipelineV1",
    "SceneSignals",
    "TextOverlay",
    "TextSignals",
    "TimedSegment",
    "analyze_audio",
    "analyze_hook",
    "analyze_text",
    "build_scene_signals",
    "classify_mood",
    "detect_scenes",
    "extract_audio",
    "extract_feedback_keyframes",
    "extract_representative_frames",
    "no_audio_signals",
    "probe_media",
    "run_pipeline",
    "select_representative_timestamps",
    "temporary_pipeline_workspace",
    "validate_metadata",
]
