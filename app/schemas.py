from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AllowedVideoType = Literal["video/mp4", "video/quicktime"]
AllowedImageType = Literal["image/jpeg", "image/png", "image/webp"]
AllowedMediaType = AllowedVideoType | AllowedImageType
AnalysisModeValue = Literal["video_coach", "story_song"]
StoryVocalPreferenceValue = Literal["any", "no_lyrics"]
MusicLanguageValue = Literal["English", "Hindi", "Punjabi", "Instrumental"]
MusicMoodValue = Literal[
    "calm",
    "energetic",
    "romantic",
    "joyful",
    "moody",
    "dreamy",
    "bold",
    "nostalgic",
]


class AnalysisCreateRequest(BaseModel):
    mode: AnalysisModeValue = "video_coach"
    vocal_preference: StoryVocalPreferenceValue = "any"
    filename: str = Field(min_length=1, max_length=255)
    content_type: AllowedMediaType
    file_size_bytes: int = Field(gt=0, le=100_000_000)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value: str) -> str:
        normalized = value.strip().replace("\\", "/").rsplit("/", 1)[-1]
        if not normalized or normalized in {".", ".."}:
            raise ValueError("filename is invalid")
        return normalized

    @model_validator(mode="after")
    def media_matches_mode(self) -> AnalysisCreateRequest:
        suffix = self.filename.lower()
        if self.mode == "video_coach":
            if self.vocal_preference != "any":
                raise ValueError("vocal_preference is only available for story_song")
            if self.content_type not in {"video/mp4", "video/quicktime"}:
                raise ValueError("video_coach requires an MP4 or MOV video")
            if not suffix.endswith((".mp4", ".mov")):
                raise ValueError("video filename must end in .mp4 or .mov")
        else:
            if self.content_type not in {"image/jpeg", "image/png", "image/webp"}:
                raise ValueError("story_song requires a JPEG, PNG, or WebP image")
            if not suffix.endswith((".jpg", ".jpeg", ".png", ".webp")):
                raise ValueError("image filename must end in .jpg, .jpeg, .png, or .webp")
        return self


class MusicPreferenceFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    preferred_languages: list[MusicLanguageValue] = Field(default_factory=list, max_length=4)
    preferred_moods: list[MusicMoodValue] = Field(default_factory=list, max_length=8)
    favorite_artists: list[str] = Field(default_factory=list, max_length=12)
    favorite_tracks: list[str] = Field(default_factory=list, max_length=12)
    default_vocal_preference: StoryVocalPreferenceValue = "any"

    @field_validator(
        "preferred_languages",
        "preferred_moods",
        "favorite_artists",
        "favorite_tracks",
    )
    @classmethod
    def unique_values(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = " ".join(value.split())
            key = normalized.casefold()
            if not normalized or key in seen:
                continue
            result.append(normalized)
            seen.add(key)
        return result

    @field_validator("favorite_artists")
    @classmethod
    def artist_names_fit_database(cls, values: list[str]) -> list[str]:
        if any(len(value) > 100 for value in values):
            raise ValueError("favorite artist names must be 100 characters or shorter")
        return values

    @field_validator("favorite_tracks")
    @classmethod
    def track_names_fit_database(cls, values: list[str]) -> list[str]:
        if any(len(value) > 150 for value in values):
            raise ValueError("favorite track names must be 150 characters or shorter")
        return values


class MusicPreferenceUpdateRequest(MusicPreferenceFields):
    complete_onboarding: bool = False


class MusicPreferenceResponse(MusicPreferenceFields):
    profile_version: str = "1"
    revision: int = Field(default=0, ge=0)
    updated_at: datetime | None = None
    onboarding_completed_at: datetime | None = None


class UploadTarget(BaseModel):
    url: str
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str]
    expires_at: datetime


class AnalysisCreatedResponse(BaseModel):
    analysis_id: UUID
    mode: AnalysisModeValue
    vocal_preference: StoryVocalPreferenceValue
    status: str
    upload: UploadTarget


class AnalysisSubmitResponse(BaseModel):
    analysis_id: UUID
    mode: AnalysisModeValue
    vocal_preference: StoryVocalPreferenceValue
    status: str
    stage: str


class AnalysisCancelResponse(BaseModel):
    analysis_id: UUID
    mode: AnalysisModeValue
    vocal_preference: StoryVocalPreferenceValue
    status: Literal["cancelled"] = "cancelled"
    stage: Literal["cancelled"] = "cancelled"


class AnalysisStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: UUID
    mode: AnalysisModeValue
    vocal_preference: StoryVocalPreferenceValue
    status: str
    stage: str
    retryable: bool = False
    failure_code: str | None = None
    result: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class AnalysisListItem(BaseModel):
    analysis_id: UUID
    mode: AnalysisModeValue
    vocal_preference: StoryVocalPreferenceValue
    status: str
    stage: str
    score: int | None = None
    niche_detected: str | None = None
    created_at: datetime


class AnalysisListResponse(BaseModel):
    analyses: list[AnalysisListItem]
    next_cursor: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "not_ready"]
    service: str = "reelmate-api"
    checks: dict[str, bool] | None = None
