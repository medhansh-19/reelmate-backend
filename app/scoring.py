"""Pure, versioned ReelMate scoring derived only from PipelineV1 signals.

No model output, database state, randomness, or wall-clock value participates in
these functions.  Replaying a stored PipelineV1 object therefore always yields
the same score for a given ``SCORE_VERSION``.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.pipeline import (
    AudioSignals,
    HookSignals,
    PipelineV1,
    SceneSignals,
    TextSignals,
)

SCORE_VERSION: Literal["score-v1"] = "score-v1"

# The original product weights assigned 15% to an unavailable trend signal.
# V1 deliberately omits that signal and renormalizes the measured components.
MEASURED_WEIGHTS: dict[str, float] = {
    "hook": 0.30,
    "pacing": 0.25,
    "av_sync": 0.20,
    "text": 0.10,
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class SubScores(_StrictModel):
    hook: int = Field(ge=0, le=100)
    pacing: int = Field(ge=0, le=100)
    av_sync: int | None = Field(default=None, ge=0, le=100)
    text: int = Field(ge=0, le=100)
    trend: None = None


class ScoreResult(_StrictModel):
    schema_version: Literal["1"] = "1"
    score_version: Literal["score-v1"] = SCORE_VERSION
    score: int = Field(ge=5, le=95)
    score_label: Literal["reel_readiness"] = "reel_readiness"
    score_experimental: Literal[True] = True
    confidence: float = Field(ge=0.0, le=1.0)
    sub_scores: SubScores


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return min(upper, max(lower, value))


def _score_int(value: float) -> int:
    # Explicit half-up rounding is stable and avoids Python's banker rounding at
    # exact .5 boundaries.
    return math.floor(_clamp(value) + 0.5)


def _interpolate(
    value: float,
    start: float,
    end: float,
    start_score: float,
    end_score: float,
) -> float:
    if end <= start:
        raise ValueError("interpolation range must be increasing")
    ratio = _clamp((value - start) / (end - start), 0.0, 1.0)
    return start_score + ratio * (end_score - start_score)


def score_hook(hook: HookSignals) -> int:
    """Score measurable attention anchors in the first three seconds."""

    # Difference-of-frame motion values around 0.08 are already visually
    # substantial; larger values should not keep inflating the score.
    motion_quality = _clamp(hook.motion_score / 0.08, 0.0, 1.0)
    face_quality = _clamp(hook.face_frame_ratio / 0.50, 0.0, 1.0)
    cut_quality = {
        0: 4.0,
        1: 15.0,
        2: 15.0,
        3: 10.0,
    }.get(hook.cuts_in_hook, 4.0)
    raw = (
        15.0
        + 40.0 * motion_quality
        + 15.0 * face_quality
        + (15.0 if hook.has_text else 0.0)
        + cut_quality
    )
    return _score_int(raw)


def _base_pacing_score(average_clip_seconds: float) -> float:
    if average_clip_seconds < 0.4:
        return _interpolate(average_clip_seconds, 0.0, 0.4, 20.0, 40.0)
    if average_clip_seconds < 0.8:
        return _interpolate(average_clip_seconds, 0.4, 0.8, 40.0, 90.0)
    if average_clip_seconds <= 2.2:
        return 95.0
    if average_clip_seconds <= 4.0:
        return _interpolate(average_clip_seconds, 2.2, 4.0, 95.0, 60.0)
    if average_clip_seconds <= 8.0:
        return _interpolate(average_clip_seconds, 4.0, 8.0, 60.0, 20.0)
    return max(5.0, 20.0 - (average_clip_seconds - 8.0) * 2.0)


def score_pacing(scenes: SceneSignals, *, duration_seconds: float) -> int:
    """Score cut cadence, strongly penalizing measured >4s dead-air clips."""

    if duration_seconds <= 0.0:
        raise ValueError("duration_seconds must be positive")
    base = _base_pacing_score(scenes.average_clip_length_seconds)
    dead_air_duration = sum(segment.duration_seconds for segment in scenes.dead_air_segments)
    dead_air_ratio = _clamp(dead_air_duration / duration_seconds, 0.0, 1.0)
    penalty = 60.0 * dead_air_ratio + min(20.0, 4.0 * len(scenes.dead_air_segments))
    return _score_int(base - penalty)


def _cut_to_beat_score(*, cuts_count: int, duration_seconds: float, bpm: float | None) -> float:
    if bpm is None:
        # Speech, ambient audio, and tracks where beat tracking is inconclusive
        # remain scoreable; no beat is invented.
        return 65.0
    cuts_per_minute = cuts_count * 60.0 / duration_seconds
    cut_to_beat_ratio = cuts_per_minute / bpm
    if cut_to_beat_ratio < 0.08:
        return _interpolate(cut_to_beat_ratio, 0.0, 0.08, 30.0, 60.0)
    if cut_to_beat_ratio < 0.20:
        return _interpolate(cut_to_beat_ratio, 0.08, 0.20, 60.0, 90.0)
    if cut_to_beat_ratio <= 1.0:
        return 95.0
    if cut_to_beat_ratio <= 1.75:
        return _interpolate(cut_to_beat_ratio, 1.0, 1.75, 95.0, 55.0)
    return max(20.0, 55.0 - (cut_to_beat_ratio - 1.75) * 20.0)


def score_av_sync(
    audio: AudioSignals,
    scenes: SceneSignals,
    *,
    duration_seconds: float,
) -> int | None:
    """Score measured cut-to-beat alignment and silence; return None without audio."""

    if not audio.has_audio:
        return None
    if duration_seconds <= 0.0:
        raise ValueError("duration_seconds must be positive")
    cadence = _cut_to_beat_score(
        cuts_count=len(scenes.cuts_seconds),
        duration_seconds=duration_seconds,
        bpm=audio.bpm,
    )
    synchronized = cadence
    if audio.bpm is not None and audio.beat_timestamps_seconds and scenes.cuts_seconds:
        beat_period = 60.0 / audio.bpm
        tolerance = min(0.25, max(0.08, beat_period * 0.20))
        proximity = [
            max(
                0.0,
                1.0 - min(abs(cut - beat) for beat in audio.beat_timestamps_seconds) / tolerance,
            )
            for cut in scenes.cuts_seconds
        ]
        alignment = 30.0 + 65.0 * (sum(proximity) / len(proximity))
        synchronized = 0.75 * alignment + 0.25 * cadence
    silence_penalty = 70.0 * audio.silence_ratio
    return _score_int(synchronized - silence_penalty)


def score_text(text: TextSignals) -> int:
    """Score OCR confidence and measured display duration, not copy quality."""

    if not text.overlays:
        # Text is useful but not mandatory for every format. Absence is neutral,
        # while low-confidence/flashing overlays score below this baseline.
        return 65
    average_confidence = sum(overlay.confidence for overlay in text.overlays) / len(text.overlays)
    confidence_quality = _clamp((average_confidence - 45.0) / 45.0, 0.0, 1.0)
    duration_quality = sum(
        min(1.0, overlay.duration_seconds / 1.2) for overlay in text.overlays
    ) / len(text.overlays)
    bottom_ratio = sum(overlay.position == "bottom" for overlay in text.overlays) / len(
        text.overlays
    )
    raw = (
        20.0
        + 40.0 * text.readable_overlay_ratio
        + 25.0 * duration_quality
        + 15.0 * confidence_quality
        + (5.0 if text.has_text_in_hook else 0.0)
        - 5.0 * bottom_ratio
    )
    return _score_int(raw)


def aggregate_scores(sub_scores: SubScores) -> int:
    """Weighted mean of available measured signals only.

    ``trend`` has no weight in v1. A missing A/V score is excluded and the
    remaining weights are renormalized rather than replaced with a fake value.
    """

    values: dict[str, int | None] = {
        "hook": sub_scores.hook,
        "pacing": sub_scores.pacing,
        "av_sync": sub_scores.av_sync,
        "text": sub_scores.text,
    }
    available = {name: value for name, value in values.items() if value is not None}
    denominator = sum(MEASURED_WEIGHTS[name] for name in available)
    if denominator <= 0.0:
        raise ValueError("at least one measured sub-score is required")
    weighted = sum(float(value) * MEASURED_WEIGHTS[name] for name, value in available.items())
    return min(95, max(5, _score_int(weighted / denominator)))


def _score_confidence(pipeline: PipelineV1) -> float:
    weighted_coverage = 0.0
    total_weight = sum(MEASURED_WEIGHTS.values())
    hook_coverage = min(1.0, pipeline.hook.frames_analyzed / 6.0)
    text_coverage = min(1.0, pipeline.text.frames_analyzed / 8.0)
    scene_coverage = 1.0
    audio_coverage = 1.0 if pipeline.audio.has_audio else 0.0
    weighted_coverage += MEASURED_WEIGHTS["hook"] * hook_coverage
    weighted_coverage += MEASURED_WEIGHTS["pacing"] * scene_coverage
    weighted_coverage += MEASURED_WEIGHTS["av_sync"] * audio_coverage
    weighted_coverage += MEASURED_WEIGHTS["text"] * text_coverage
    return float(round(weighted_coverage / total_weight, 4))


def score_pipeline(pipeline: PipelineV1) -> ScoreResult:
    """Calculate the complete deterministic v1 score."""

    duration = pipeline.metadata.duration_seconds
    sub_scores = SubScores(
        hook=score_hook(pipeline.hook),
        pacing=score_pacing(pipeline.scenes, duration_seconds=duration),
        av_sync=score_av_sync(
            pipeline.audio,
            pipeline.scenes,
            duration_seconds=duration,
        ),
        text=score_text(pipeline.text),
        trend=None,
    )
    return ScoreResult(
        score=aggregate_scores(sub_scores),
        confidence=_score_confidence(pipeline),
        sub_scores=sub_scores,
    )


__all__ = [
    "MEASURED_WEIGHTS",
    "SCORE_VERSION",
    "ScoreResult",
    "SubScores",
    "aggregate_scores",
    "score_av_sync",
    "score_hook",
    "score_pacing",
    "score_pipeline",
    "score_text",
]
