"""Local, explainable coaching generated from ReelMate's measured signals.

This module deliberately has no network client and no generative-model dependency.
Every recommendation is selected from versioned coaching strategies using the
deterministic video pipeline and score. Replaying the same inputs produces the
same coaching.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.pipeline import PipelineV1
from app.scoring import ScoreResult

FeedbackType = Literal["hook", "pacing", "audio", "text", "strength"]
FeedbackSeverity = Literal["high", "medium", "low"]
FeedbackSource = Literal["local_signal_engine"]
PricingStatus = Literal["no_model_call"]

COACHING_MODEL_VERSION = "local-coach-v2"
COACHING_RULESET_VERSION = "coaching-rules-2026-08"


class FeedbackItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: FeedbackType
    issue_code: str = Field(default="measured_signal", min_length=2, max_length=64)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    message: str = Field(min_length=4, max_length=240)
    action: str = Field(min_length=4, max_length=240)
    evidence: str = Field(min_length=4, max_length=300)
    severity: FeedbackSeverity

    @model_validator(mode="after")
    def valid_interval(self) -> FeedbackItem:
        if self.end_seconds < self.start_seconds:
            raise ValueError("end_seconds must be greater than or equal to start_seconds")
        return self


class FeedbackResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback: list[FeedbackItem] = Field(min_length=3, max_length=5)
    source: FeedbackSource = "local_signal_engine"
    model_id: str = COACHING_MODEL_VERSION
    prompt_version: str = COACHING_RULESET_VERSION
    input_tokens: Literal[0] = 0
    output_tokens: Literal[0] = 0
    fallback_reason: None = None
    inferred_niche: None = None
    niche_confidence: None = None
    estimated_model_cost_usd: Decimal = Decimal("0")
    pricing_status: PricingStatus = "no_model_call"
    pricing_version: str = "local-compute"
    cost_limit_exceeded: Literal[False] = False

    @model_validator(mode="after")
    def includes_strength(self) -> FeedbackResult:
        if not any(item.type == "strength" for item in self.feedback):
            raise ValueError("feedback must include at least one strength")
        return self


class FeedbackService:
    """Select coaching from local measurements; retained as a service boundary."""

    async def generate(
        self,
        pipeline: PipelineV1,
        score: ScoreResult,
    ) -> FeedbackResult:
        return FeedbackResult(feedback=_coaching_items(pipeline, score))

    async def aclose(self) -> None:
        return None


def _coaching_items(pipeline: PipelineV1, score: ScoreResult) -> list[FeedbackItem]:
    duration = pipeline.metadata.duration_seconds
    sub_scores = score.sub_scores.model_dump(mode="python")
    measured = {key: value for key, value in sub_scores.items() if isinstance(value, int)}
    strongest, strongest_score = max(measured.items(), key=lambda item: (item[1], item[0]))
    strongest_label = _label(strongest)
    items: list[FeedbackItem] = [
        FeedbackItem(
            type="strength",
            issue_code=f"keep_{strongest}",
            start_seconds=0,
            end_seconds=min(3.0, duration),
            message=f"Your strongest measured area is {strongest_label}.",
            action=f"Keep the current {strongest_label} approach while testing the next edit.",
            evidence=f"ReelMate measured {strongest_label} at {strongest_score}/100.",
            severity="low",
        )
    ]

    if not pipeline.hook.has_motion or score.sub_scores.hook < 55:
        items.append(
            FeedbackItem(
                type="hook",
                issue_code="weak_opening_motion",
                start_seconds=0,
                end_seconds=min(3.0, duration),
                message="The opening needs a faster visual reason to keep watching.",
                action="Start on the first clear movement, reveal, or before-and-after change.",
                evidence=(
                    f"Opening motion measured {pipeline.hook.motion_score:.3f}; "
                    f"the hook score is {score.sub_scores.hook}/100."
                ),
                severity="high" if score.sub_scores.hook < 45 else "medium",
            )
        )

    if pipeline.scenes.dead_air_segments:
        longest = max(pipeline.scenes.dead_air_segments, key=lambda item: item.duration_seconds)
        items.append(
            FeedbackItem(
                type="pacing",
                issue_code="long_clip",
                start_seconds=longest.start_seconds,
                end_seconds=min(duration, longest.end_seconds),
                message="This is the longest low-change section in the edit.",
                action="Trim it or introduce a purposeful crop, angle, or demonstration step.",
                evidence=f"The scene detector measured a {longest.duration_seconds:.1f}s hold.",
                severity="high" if longest.duration_seconds >= 5 else "medium",
            )
        )
    elif score.sub_scores.pacing < 65:
        items.append(
            FeedbackItem(
                type="pacing",
                issue_code="uneven_pacing",
                start_seconds=0,
                end_seconds=min(duration, pipeline.scenes.average_clip_length_seconds),
                message="The overall cut cadence is outside the strongest measured range.",
                action="Use the longest clip as the first trim, then compare the pacing again.",
                evidence=(
                    f"Average clip length is {pipeline.scenes.average_clip_length_seconds:.1f}s; "
                    f"the pacing score is {score.sub_scores.pacing}/100."
                ),
                severity="medium",
            )
        )

    if pipeline.audio.has_audio and pipeline.audio.silence_gaps:
        longest_silence = max(pipeline.audio.silence_gaps, key=lambda item: item.duration_seconds)
        items.append(
            FeedbackItem(
                type="audio",
                issue_code="audio_gap",
                start_seconds=longest_silence.start_seconds,
                end_seconds=min(duration, longest_silence.end_seconds),
                message="The soundtrack loses momentum in this section.",
                action=(
                    "Tighten the gap or make the silence clearly intentional with a visual beat."
                ),
                evidence=(
                    f"Audio analysis found {longest_silence.duration_seconds:.1f}s of silence."
                ),
                severity="medium",
            )
        )
    elif score.sub_scores.av_sync is not None and score.sub_scores.av_sync < 60:
        items.append(
            FeedbackItem(
                type="audio",
                issue_code="cut_beat_mismatch",
                start_seconds=0,
                end_seconds=min(3.0, duration),
                message="The visual cut rhythm is not consistently landing on the detected beat.",
                action="Move the strongest scene changes onto a beat or spoken emphasis.",
                evidence=f"Measured audio-visual sync is {score.sub_scores.av_sync}/100.",
                severity="medium",
            )
        )

    flagged = next((overlay for overlay in pipeline.text.overlays if overlay.flagged), None)
    if flagged is not None:
        items.append(
            FeedbackItem(
                type="text",
                issue_code="text_too_fast",
                start_seconds=flagged.timestamp_seconds,
                end_seconds=min(duration, flagged.timestamp_seconds + flagged.duration_seconds),
                message="This overlay may disappear before it can be read comfortably.",
                action="Keep it visible longer or shorten the copy without changing its meaning.",
                evidence=f"OCR timing measured only {flagged.duration_seconds:.1f}s on screen.",
                severity="medium",
            )
        )

    present = {item.type for item in items}
    ranked = sorted(measured.items(), key=lambda item: (item[1], item[0]))
    for category, value in ranked:
        feedback_type = _feedback_type(category)
        if len(items) >= 3 or feedback_type in present:
            continue
        items.append(_score_based_item(feedback_type, value, duration))
        present.add(feedback_type)

    defaults: tuple[tuple[FeedbackType, str, str], ...] = (
        ("hook", "hook_review", "Test a clearer visual promise in the opening."),
        ("pacing", "pacing_review", "Trim the longest hold and compare the result."),
        ("text", "text_review", "Keep the main overlay concise and away from UI edges."),
    )
    for item_type, code, action in defaults:
        if len(items) >= 3:
            break
        if item_type in present:
            continue
        items.append(
            FeedbackItem(
                type=item_type,
                issue_code=code,
                start_seconds=0,
                end_seconds=min(3.0, duration),
                message=f"The {item_type} signal is the next useful review point.",
                action=action,
                evidence="This recommendation comes from ReelMate's measured signal coverage.",
                severity="medium",
            )
        )
        present.add(item_type)
    return items[:5]


def _feedback_type(category: str) -> Literal["hook", "pacing", "audio", "text"]:
    if category == "av_sync":
        return "audio"
    if category == "hook":
        return "hook"
    if category == "text":
        return "text"
    return "pacing"


def _label(category: str) -> str:
    return "audio-visual sync" if category == "av_sync" else category.replace("_", " ")


def _score_based_item(
    feedback_type: Literal["hook", "pacing", "audio", "text"],
    score: int,
    duration: float,
) -> FeedbackItem:
    actions = {
        "hook": "Test an immediate movement or clearer opening promise.",
        "pacing": "Trim the longest hold first and compare the new cadence.",
        "audio": "Align a visible cut with a strong beat or spoken emphasis.",
        "text": "Shorten the main overlay and keep it visible long enough to read.",
    }
    return FeedbackItem(
        type=feedback_type,
        issue_code=f"low_{feedback_type}_score",
        start_seconds=0,
        end_seconds=min(3.0, duration),
        message=f"The measured {_label(feedback_type)} result has room to improve.",
        action=actions[feedback_type],
        evidence=f"ReelMate measured {_label(feedback_type)} at {score}/100.",
        severity="high" if score < 45 else "medium",
    )


__all__ = [
    "COACHING_MODEL_VERSION",
    "COACHING_RULESET_VERSION",
    "FeedbackItem",
    "FeedbackResult",
    "FeedbackService",
]
