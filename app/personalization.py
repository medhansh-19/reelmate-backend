from __future__ import annotations

from collections import Counter
from typing import Any

from pydantic import BaseModel, Field


class ProfileSnapshot(BaseModel):
    submission_count: int = 0
    inferred_niche: str | None = None
    niche_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    editing_style: str | None = None
    editing_style_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    typical_energy: str | None = None
    typical_energy_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    recurring_issue_codes: list[str] = Field(default_factory=list)
    profile_version: str = "1"


def _result(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        raw = record.get("result_json") or record.get("result") or record
    else:
        raw = getattr(record, "result_json", None) or {}
    return raw if isinstance(raw, dict) else {}


def derive_profile(history: list[Any]) -> ProfileSnapshot:
    """Derive a passive profile from completed analyses only.

    An issue becomes recurring only after appearing in at least three distinct
    completed analyses. Model prose is never used as an issue identifier.
    """

    results = [_result(item) for item in history]
    results = [item for item in results if item]

    energies: Counter[str] = Counter()
    niches: Counter[str] = Counter()
    styles: Counter[str] = Counter()
    issues: Counter[str] = Counter()

    for result in results:
        pipeline = result.get("pipeline") or result.get("pipeline_summary") or {}
        if isinstance(pipeline, dict):
            energy = pipeline.get("energy") or (pipeline.get("audio") or {}).get("energy")
            if isinstance(energy, str) and energy in {"low", "medium", "high"}:
                energies[energy] += 1

            niche = pipeline.get("niche") or pipeline.get("niche_detected")
            if isinstance(niche, str) and niche:
                niches[niche] += 1

            avg_clip = pipeline.get("avg_clip_length")
            if avg_clip is None and isinstance(pipeline.get("scenes"), dict):
                avg_clip = pipeline["scenes"].get(
                    "average_clip_length_seconds",
                    pipeline["scenes"].get("average_clip_length"),
                )
            if isinstance(avg_clip, int | float):
                hook = pipeline.get("hook")
                has_face = isinstance(hook, dict) and hook.get("has_face") is True
                if has_face and avg_clip >= 2.0:
                    styles["talking-head"] += 1
                elif avg_clip <= 1.5:
                    styles["fast-cut"] += 1
                elif avg_clip >= 4.0:
                    styles["slow-cinematic"] += 1
                else:
                    styles["montage"] += 1

        seen_in_analysis: set[str] = set()
        for item in result.get("feedback", []):
            if not isinstance(item, dict) or item.get("type") == "strength":
                continue
            issue_code = item.get("issue_code") or item.get("type")
            if isinstance(issue_code, str) and issue_code:
                seen_in_analysis.add(issue_code)
        issues.update(seen_in_analysis)

    niche, niche_confidence = _most_common_with_confidence(niches)
    style, style_confidence = _most_common_with_confidence(styles)
    energy, energy_confidence = _most_common_with_confidence(energies)
    return ProfileSnapshot(
        submission_count=len(results),
        inferred_niche=niche,
        niche_confidence=niche_confidence,
        editing_style=style,
        editing_style_confidence=style_confidence,
        typical_energy=energy,
        typical_energy_confidence=energy_confidence,
        recurring_issue_codes=sorted(code for code, count in issues.items() if count >= 3),
    )


def _most_common_with_confidence(counter: Counter[str]) -> tuple[str | None, float | None]:
    if not counter:
        return None, None
    value, count = counter.most_common(1)[0]
    return value, round(count / counter.total(), 4)
