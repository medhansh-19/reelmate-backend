"""Private on-worker computer-vision and content-based song recommendation.

The ranker does not call an LLM or music API. It extracts measurable image
features, projects them into an eight-dimensional mood space, and performs a
diversified nearest-neighbour search over a versioned song catalogue.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Self, cast

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.song_catalog import CATALOG_VERSION, STORY_SONGS, SongCatalogEntry

STORY_PIPELINE_VERSION = "story-vision-v1"
STORY_RANKER_VERSION = "visual-song-mmr-v2"
SONG_CATALOG_VERSION = CATALOG_VERSION
MAX_IMAGE_BYTES = 15_000_000
MAX_IMAGE_PIXELS = 40_000_000

MoodName = Literal[
    "calm",
    "energetic",
    "romantic",
    "joyful",
    "moody",
    "dreamy",
    "bold",
    "nostalgic",
]
PreferenceSignal = Literal[
    "preferred_languages",
    "preferred_moods",
    "favorite_artists",
    "favorite_tracks",
]
MOODS: tuple[MoodName, ...] = (
    "calm",
    "energetic",
    "romantic",
    "joyful",
    "moody",
    "dreamy",
    "bold",
    "nostalgic",
)


class StoryPipelineError(RuntimeError):
    code = "IMAGE_PIPELINE_FAILED"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code or self.code


class StoryImageSignals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: int = Field(gt=0)
    height: int = Field(gt=0)
    brightness: float = Field(ge=0, le=1)
    saturation: float = Field(ge=0, le=1)
    contrast: float = Field(ge=0, le=1)
    warmth: float = Field(ge=0, le=1)
    colorfulness: float = Field(ge=0, le=1)
    edge_density: float = Field(ge=0, le=1)
    center_activity: float = Field(ge=0, le=1)
    face_count: int = Field(ge=0)
    face_prominence: float = Field(ge=0, le=1)
    dominant_colors: list[str] = Field(min_length=1, max_length=3)
    visual_tags: list[str] = Field(min_length=1, max_length=6)
    mood_profile: dict[MoodName, float]


class SongRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    song_id: str
    title: str
    artist: str
    language: str
    match_score: int = Field(ge=0, le=100)
    bpm: int | None = Field(default=None, gt=0)
    energy: Literal["low", "medium", "high"]
    vocal_type: Literal["none", "vocal_texture", "sparse_lyrics", "full_lyrics"]
    has_lyrics: bool
    aesthetic_tags: list[str] = Field(min_length=1, max_length=4)
    matched_moods: list[MoodName] = Field(min_length=1, max_length=3)
    why: str
    search_query: str

    @model_validator(mode="after")
    def vocal_metadata_is_consistent(self) -> Self:
        expected_has_lyrics = self.vocal_type != "none"
        if self.has_lyrics != expected_has_lyrics:
            raise ValueError("has_lyrics must agree with vocal_type")
        if (self.vocal_type == "none") != (self.language == "Instrumental"):
            raise ValueError("Instrumental language must agree with vocal_type")
        return self


class StoryPersonalization(BaseModel):
    """Disclosure for the small, first-party-only ranking adjustment."""

    model_config = ConfigDict(extra="forbid")

    applied: bool
    source: Literal["first_party", "none"]
    signals_provided: list[PreferenceSignal]
    signals_used: list[PreferenceSignal]
    profile_version: str | None
    profile_revision: int | None = Field(default=None, ge=1)
    profile_updated_at: datetime | None = None
    resolution: Literal["processing_start", "none"]
    spotify_data_used: Literal[False] = False


class StoryPrivacy(BaseModel):
    """Stable privacy facts that do not claim asynchronous deletion has finished."""

    model_config = ConfigDict(extra="forbid")

    external_api_used: Literal[False] = False
    source_included_in_result: Literal[False] = False
    source_cleanup: Literal["durable_outbox"] = "durable_outbox"


class StoryRecommendationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["3"] = "3"
    mode: Literal["story_song"] = "story_song"
    requested_vocal_preference: Literal["any", "no_lyrics"]
    score: int = Field(ge=5, le=95)
    confidence: float = Field(ge=0, le=1)
    image_summary: StoryImageSignals
    recommendations: list[SongRecommendation] = Field(min_length=3, max_length=5)
    personalization: StoryPersonalization
    versions: dict[str, str]
    privacy: StoryPrivacy

    @model_validator(mode="after")
    def recommendation_contract_is_consistent(self) -> Self:
        song_ids = [recommendation.song_id for recommendation in self.recommendations]
        if len(song_ids) != len(set(song_ids)):
            raise ValueError("recommendations must contain unique song IDs")
        if self.requested_vocal_preference == "no_lyrics" and any(
            recommendation.has_lyrics for recommendation in self.recommendations
        ):
            raise ValueError("no_lyrics results cannot contain lyrical recommendations")
        if self.personalization.applied != bool(self.personalization.signals_used):
            raise ValueError("personalization applied must agree with signals_used")
        if not set(self.personalization.signals_used).issubset(
            self.personalization.signals_provided
        ):
            raise ValueError("signals_used must be a subset of signals_provided")
        return self


class StoryTasteProfile(BaseModel):
    """First-party preferences entered directly by the ReelMate user."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    preferred_languages: list[Literal["English", "Hindi", "Punjabi", "Instrumental"]] = Field(
        default_factory=list, max_length=4
    )
    preferred_moods: list[MoodName] = Field(default_factory=list, max_length=8)
    favorite_artists: list[str] = Field(default_factory=list, max_length=12)
    favorite_tracks: list[str] = Field(default_factory=list, max_length=12)
    profile_version: str = "1"
    profile_revision: int | None = Field(default=None, ge=1)
    profile_updated_at: datetime | None = None


def analyze_story_image(
    image_path: str | Path,
    *,
    limit: int = 5,
    vocal_preference: Literal["any", "no_lyrics"] = "any",
    taste_profile: StoryTasteProfile | None = None,
) -> StoryRecommendationResult:
    if not 3 <= limit <= 5:
        raise ValueError("limit must be between 3 and 5")
    if vocal_preference not in {"any", "no_lyrics"}:
        raise ValueError("vocal_preference must be any or no_lyrics")
    path = Path(image_path)
    if not path.is_file():
        raise StoryPipelineError("The uploaded image is unavailable.", code="IMAGE_FILE_MISSING")
    size = path.stat().st_size
    if not 0 < size <= MAX_IMAGE_BYTES:
        raise StoryPipelineError("Image must be 15 MB or smaller.", code="IMAGE_TOO_LARGE")

    try:
        from PIL import Image, ImageOps, UnidentifiedImageError

        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
        with Image.open(path) as opened:
            if opened.format not in {"JPEG", "PNG", "WEBP"}:
                raise StoryPipelineError(
                    "Image must be JPEG, PNG, or WebP.", code="IMAGE_FORMAT_UNSUPPORTED"
                )
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.load()
    except StoryPipelineError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise StoryPipelineError("The image could not be decoded.", code="IMAGE_INVALID") from exc

    if image.width * image.height > MAX_IMAGE_PIXELS:
        raise StoryPipelineError(
            "Image dimensions are too large.", code="IMAGE_DIMENSIONS_TOO_LARGE"
        )
    original_width, original_height = image.size
    image.thumbnail((768, 768))
    rgb = np.asarray(image, dtype=np.uint8)
    signals = _extract_signals(rgb, original_width, original_height)
    recommendations, raw_scores, personalization = _rank_songs(
        signals,
        limit=limit,
        vocal_preference=vocal_preference,
        taste_profile=taste_profile,
    )
    top_score = raw_scores[0]
    margin = max(0.0, top_score - raw_scores[min(2, len(raw_scores) - 1)])
    quality = min(1.0, math.log2(max(2, original_width * original_height)) / 22.0)
    confidence = round(min(0.96, 0.48 + 0.30 * top_score + 0.45 * margin + 0.12 * quality), 4)
    public_score = min(95, max(5, round(52 + 43 * top_score)))
    return StoryRecommendationResult(
        requested_vocal_preference=vocal_preference,
        score=public_score,
        confidence=confidence,
        image_summary=signals,
        recommendations=recommendations,
        personalization=personalization,
        versions={
            "pipeline": STORY_PIPELINE_VERSION,
            "ranking_model": STORY_RANKER_VERSION,
            "catalog": SONG_CATALOG_VERSION,
        },
        privacy=StoryPrivacy(),
    )


def _extract_signals(rgb: np.ndarray, width: int, height: int) -> StoryImageSignals:
    try:
        import cv2
    except ImportError as exc:
        raise StoryPipelineError(
            "The image worker dependency is unavailable.", code="IMAGE_DEPENDENCY_MISSING"
        ) from exc

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    brightness = float(hsv[..., 2].mean() / 255.0)
    saturation = float(hsv[..., 1].mean() / 255.0)
    contrast = float(min(1.0, gray.std() / 96.0))
    red_mean = float(rgb[..., 0].mean())
    blue_mean = float(rgb[..., 2].mean())
    warmth = float(np.clip(0.5 + (red_mean - blue_mean) / 255.0, 0.0, 1.0))
    rg = rgb[..., 0].astype(np.float32) - rgb[..., 1].astype(np.float32)
    yb = 0.5 * (rgb[..., 0].astype(np.float32) + rgb[..., 1].astype(np.float32)) - rgb[..., 2]
    colorfulness = float(
        np.clip(
            (np.hypot(rg.std(), yb.std()) + 0.3 * np.hypot(rg.mean(), yb.mean())) / 110.0, 0.0, 1.0
        )
    )
    edges = cv2.Canny(gray, 80, 180)
    edge_density = float(np.clip(np.count_nonzero(edges) / edges.size * 4.0, 0.0, 1.0))
    row_start, row_end = gray.shape[0] // 4, gray.shape[0] * 3 // 4
    col_start, col_end = gray.shape[1] // 4, gray.shape[1] * 3 // 4
    center = edges[row_start:row_end, col_start:col_end]
    center_activity = float(np.clip(np.count_nonzero(center) / max(1, center.size) * 4.0, 0.0, 1.0))
    face_count, face_prominence = _faces(gray)
    mood_values = _project_moods(
        brightness=brightness,
        saturation=saturation,
        contrast=contrast,
        warmth=warmth,
        colorfulness=colorfulness,
        edge_density=edge_density,
        face_prominence=face_prominence,
    )
    tags = _visual_tags(
        width=width,
        height=height,
        brightness=brightness,
        saturation=saturation,
        contrast=contrast,
        warmth=warmth,
        edge_density=edge_density,
        face_count=face_count,
    )
    return StoryImageSignals(
        width=width,
        height=height,
        brightness=round(brightness, 4),
        saturation=round(saturation, 4),
        contrast=round(contrast, 4),
        warmth=round(warmth, 4),
        colorfulness=round(colorfulness, 4),
        edge_density=round(edge_density, 4),
        center_activity=round(center_activity, 4),
        face_count=face_count,
        face_prominence=round(face_prominence, 4),
        dominant_colors=_dominant_color_names(rgb),
        visual_tags=tags,
        mood_profile={
            mood: round(value, 4) for mood, value in zip(MOODS, mood_values, strict=True)
        },
    )


def _project_moods(**features: float) -> np.ndarray:
    # Fixed, versioned visual-to-mood projection. The next model version can be
    # fitted from opt-in save/skip events while preserving this replayable v1.
    x = np.array(
        [
            features["brightness"],
            features["saturation"],
            features["contrast"],
            features["warmth"],
            features["colorfulness"],
            features["edge_density"],
            features["face_prominence"],
        ],
        dtype=np.float64,
    )
    weights = np.array(
        [
            [0.6, -0.8, -0.4, 0.2, -0.5, -1.0, 0.2],
            [0.3, 1.0, 0.8, 0.0, 0.7, 1.2, 0.1],
            [0.2, 0.2, -0.2, 1.0, 0.1, -0.3, 1.1],
            [1.1, 0.8, -0.2, 0.5, 0.8, 0.1, 0.4],
            [-1.1, -0.2, 0.9, -0.2, -0.3, 0.5, 0.1],
            [0.1, 0.2, -0.1, 0.3, 0.5, -0.8, 0.2],
            [0.1, 0.8, 1.1, 0.2, 0.6, 0.8, 0.3],
            [-0.2, -0.4, 0.2, 0.8, -0.2, -0.5, 0.5],
        ],
        dtype=np.float64,
    )
    bias = np.array([0.3, -0.6, -0.5, -0.4, 0.2, 0.1, -0.7, 0.0])
    raw = weights @ x + bias
    projected = 1.0 / (1.0 + np.exp(-raw))
    norm = np.linalg.norm(projected)
    result = projected if norm == 0 else projected / norm
    return cast(np.ndarray, result)


def _faces(gray: np.ndarray) -> tuple[int, float]:
    try:
        import cv2 as cv2_module

        cv2: Any = cv2_module
        classifier = cv2.CascadeClassifier(
            str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")
        )
        if classifier.empty():
            return 0, 0.0
        faces = classifier.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(28, 28))
    except Exception:
        return 0, 0.0
    image_area = max(1, gray.shape[0] * gray.shape[1])
    prominence = min(1.0, sum(int(w) * int(h) for _, _, w, h in faces) / image_area * 3.0)
    return len(faces), float(prominence)


def _dominant_color_names(rgb: np.ndarray) -> list[str]:
    pixels = rgb.reshape(-1, 3)[:: max(1, rgb.size // 30_000)]
    bins = (pixels // 64).astype(np.int16)
    keys, counts = np.unique(bins, axis=0, return_counts=True)
    ordered = keys[np.argsort(counts)[::-1][:3]]
    names: list[str] = []
    for bucket in ordered:
        red, green, blue = (int(value * 64 + 32) for value in bucket)
        color = _color_name((red, green, blue))
        if color not in names:
            names.append(color)
    return names or ["neutral"]


def _color_name(rgb: tuple[int, int, int]) -> str:
    red, green, blue = rgb
    maximum, minimum = max(rgb), min(rgb)
    if maximum < 65:
        return "black"
    if minimum > 205:
        return "white"
    if maximum - minimum < 25:
        return "gray"
    if red > green * 1.25 and red > blue * 1.25:
        return "red" if green < 120 else "orange"
    if blue > red * 1.2 and blue > green * 1.1:
        return "blue"
    if green > red * 1.15 and green > blue * 1.05:
        return "green"
    if red > 150 and blue > 120:
        return "purple"
    if red > 150 and green > 140:
        return "gold"
    return "teal"


def _visual_tags(**values: float | int) -> list[str]:
    tags: list[str] = []
    if int(values["face_count"]) > 0:
        tags.append("portrait")
    if float(values["brightness"]) < 0.34:
        tags.append("night")
    elif float(values["brightness"]) > 0.68:
        tags.append("bright")
    if float(values["saturation"]) > 0.52:
        tags.append("colorful")
    if float(values["contrast"]) > 0.58:
        tags.append("cinematic")
    if float(values["warmth"]) > 0.6:
        tags.append("warm")
    elif float(values["warmth"]) < 0.4:
        tags.append("cool")
    if float(values["edge_density"]) < 0.18:
        tags.append("minimal")
    if int(values["height"]) > int(values["width"]):
        tags.append("vertical")
    return tags[:6] or ["balanced"]


def _normalized_text(value: str) -> str:
    return " ".join(value.casefold().split())


_CATALOG_TITLE_COUNTS = Counter(_normalized_text(song.title) for song in STORY_SONGS)


def _song_mood_vector(song: SongCatalogEntry) -> np.ndarray:
    return np.array(
        [getattr(song.moods, mood) for mood in MOODS],
        dtype=np.float64,
    )


def _preference_bonus(
    song: SongCatalogEntry,
    taste_profile: StoryTasteProfile | None,
) -> tuple[float, list[PreferenceSignal]]:
    if taste_profile is None:
        return 0.0, []

    signals: list[PreferenceSignal] = []
    bonus = 0.0
    languages = set(taste_profile.preferred_languages)
    if (song.vocal_type == "none" and "Instrumental" in languages) or languages.intersection(
        song.lyrics_languages
    ):
        bonus += 0.015
        signals.append("preferred_languages")

    if taste_profile.preferred_moods:
        mood_fit = sum(getattr(song.moods, mood) for mood in taste_profile.preferred_moods) / len(
            taste_profile.preferred_moods
        )
        bonus += 0.025 * mood_fit
        if mood_fit > 0:
            signals.append("preferred_moods")

    favorite_artists = {_normalized_text(value) for value in taste_profile.favorite_artists}
    if favorite_artists.intersection(_normalized_text(artist.name) for artist in song.artists):
        bonus += 0.04
        signals.append("favorite_artists")

    favorite_tracks = {_normalized_text(value) for value in taste_profile.favorite_tracks}
    song_title = _normalized_text(song.title)
    song_identity = _normalized_text(
        f"{song.title} {' '.join(artist.name for artist in song.artists)}"
    )
    title_is_unambiguous_favorite = (
        song_title in favorite_tracks and _CATALOG_TITLE_COUNTS[song_title] == 1
    )
    if title_is_unambiguous_favorite or song_identity in favorite_tracks:
        bonus += 0.05
        signals.append("favorite_tracks")

    return min(0.08, bonus), signals


def _mood_similarity(left: SongCatalogEntry, right: SongCatalogEntry) -> float:
    left_vector = _song_mood_vector(left)
    right_vector = _song_mood_vector(right)
    left_vector /= max(float(np.linalg.norm(left_vector)), 1e-9)
    right_vector /= max(float(np.linalg.norm(right_vector)), 1e-9)
    return float(np.dot(left_vector, right_vector))


def _rank_songs(
    signals: StoryImageSignals,
    *,
    limit: int,
    vocal_preference: Literal["any", "no_lyrics"],
    taste_profile: StoryTasteProfile | None,
) -> tuple[list[SongRecommendation], list[float], StoryPersonalization]:
    image_vector = np.array([signals.mood_profile[mood] for mood in MOODS], dtype=np.float64)
    image_vector /= max(float(np.linalg.norm(image_vector)), 1e-9)
    image_tags = {_normalized_text(tag) for tag in signals.visual_tags}
    target_energy = min(
        1.0,
        1.2 * (signals.mood_profile["energetic"] + signals.mood_profile["bold"]),
    )

    scored: list[tuple[float, float, float, SongCatalogEntry, tuple[PreferenceSignal, ...]]] = []
    for song in STORY_SONGS:
        if vocal_preference == "no_lyrics" and song.vocal_type != "none":
            continue
        song_vector = _song_mood_vector(song)
        song_vector /= max(float(np.linalg.norm(song_vector)), 1e-9)
        cosine = float(np.dot(image_vector, song_vector))
        energy_fit = 1.0 - min(1.0, abs(target_energy - song.energy_score))
        tag_overlap = len(image_tags.intersection(map(_normalized_text, song.aesthetic_tags)))
        tag_fit = 0.4 + 0.6 * (tag_overlap / max(1, len(image_tags)))
        visual_score = 0.75 * cosine + 0.15 * energy_fit + 0.10 * tag_fit
        preference_bonus, preference_matches = _preference_bonus(song, taste_profile)
        final_score = visual_score + preference_bonus
        scored.append(
            (
                final_score,
                visual_score,
                preference_bonus,
                song,
                tuple(preference_matches),
            )
        )
    scored.sort(key=lambda item: (-item[0], item[3].song_id))

    selected: list[tuple[float, float, float, SongCatalogEntry, tuple[PreferenceSignal, ...]]] = []
    selected_artist_ids: set[str] = set()
    remaining = list(scored)
    while remaining and len(selected) < limit:
        candidates: list[
            tuple[
                float,
                tuple[
                    float,
                    float,
                    float,
                    SongCatalogEntry,
                    tuple[PreferenceSignal, ...],
                ],
            ]
        ] = []
        for item in remaining:
            artist_ids = {artist.artist_id for artist in item[3].artists}
            if artist_ids.intersection(selected_artist_ids):
                continue
            redundancy = (
                max(_mood_similarity(item[3], prior[3]) for prior in selected) if selected else 0.0
            )
            utility = item[0] - 0.08 * redundancy
            candidates.append((utility, item))
        if not candidates:
            break
        _, chosen = min(
            candidates,
            key=lambda candidate: (-candidate[0], candidate[1][3].song_id),
        )
        selected.append(chosen)
        selected_artist_ids.update(artist.artist_id for artist in chosen[3].artists)
        remaining.remove(chosen)

    # A balanced slate exposes an aesthetic no-lyrics option when it remains
    # reasonably close to the visual relevance of the normal top five.
    if (
        vocal_preference == "any"
        and selected
        and not any(item[3].vocal_type == "none" for item in selected)
    ):
        cutoff = scored[min(limit - 1, len(scored) - 1)][0] - 0.08
        retained_artist_ids = {
            artist.artist_id for item in selected[:-1] for artist in item[3].artists
        }
        instrumental = next(
            (
                item
                for item in scored
                if item[3].vocal_type == "none"
                and item[0] >= cutoff
                and not retained_artist_ids.intersection(
                    artist.artist_id for artist in item[3].artists
                )
            ),
            None,
        )
        if instrumental is not None:
            selected[-1] = instrumental

    selected.sort(key=lambda item: (-item[0], item[3].song_id))
    recommendations: list[SongRecommendation] = []
    for score, _visual_score, preference_bonus, song, matched_preference_signals in selected:
        matched = sorted(
            MOODS,
            key=lambda mood: image_vector[MOODS.index(mood)] * getattr(song.moods, mood),
            reverse=True,
        )[:2]
        energy: Literal["low", "medium", "high"] = (
            "high" if song.energy_score >= 0.72 else "medium" if song.energy_score >= 0.4 else "low"
        )
        visual_cues = ", ".join(signals.visual_tags[:2])
        artist = " & ".join(item.name for item in song.artists)
        language = (
            "Instrumental" if song.vocal_type == "none" else " / ".join(song.lyrics_languages)
        )
        public_match = round(45 + 52 * float(np.clip((score - 0.45) / 0.55, 0.0, 1.0)))
        format_sentence = (
            " It has no lyrics, leaving space for the image." if song.vocal_type == "none" else ""
        )
        taste_sentence = (
            " It also reflects your saved ReelMate music taste."
            if preference_bonus > 0 and matched_preference_signals
            else ""
        )
        recommendations.append(
            SongRecommendation(
                song_id=song.song_id,
                title=song.title,
                artist=artist,
                language=language,
                match_score=min(99, max(1, public_match)),
                bpm=song.bpm,
                energy=energy,
                vocal_type=song.vocal_type,
                has_lyrics=song.vocal_type != "none",
                aesthetic_tags=list(song.aesthetic_tags[:4]),
                matched_moods=matched,
                why=(
                    f"Matches the image's {matched[0]} and {matched[1]} profile, "
                    f"supported by its {visual_cues} visual signals."
                    f"{format_sentence}{taste_sentence}"
                ),
                search_query=song.search_query,
            )
        )

    signals_provided: list[PreferenceSignal] = []
    if taste_profile is not None:
        if taste_profile.preferred_languages:
            signals_provided.append("preferred_languages")
        if taste_profile.preferred_moods:
            signals_provided.append("preferred_moods")
        if taste_profile.favorite_artists:
            signals_provided.append("favorite_artists")
        if taste_profile.favorite_tracks:
            signals_provided.append("favorite_tracks")
    selected_signal_set = {signal for item in selected if item[2] > 0 for signal in item[4]}
    signals_used = [signal for signal in signals_provided if signal in selected_signal_set]
    personalization = StoryPersonalization(
        applied=bool(signals_used),
        source="first_party" if signals_provided else "none",
        signals_provided=signals_provided,
        signals_used=signals_used,
        profile_version=taste_profile.profile_version if taste_profile is not None else None,
        profile_revision=(taste_profile.profile_revision if taste_profile is not None else None),
        profile_updated_at=(
            taste_profile.profile_updated_at if taste_profile is not None else None
        ),
        resolution="processing_start" if taste_profile is not None else "none",
        spotify_data_used=False,
    )
    return recommendations, [item[0] for item in selected], personalization


__all__ = [
    "MAX_IMAGE_BYTES",
    "SONG_CATALOG_VERSION",
    "STORY_PIPELINE_VERSION",
    "STORY_RANKER_VERSION",
    "SongRecommendation",
    "StoryImageSignals",
    "StoryPersonalization",
    "StoryPipelineError",
    "StoryPrivacy",
    "StoryRecommendationResult",
    "StoryTasteProfile",
    "analyze_story_image",
]
