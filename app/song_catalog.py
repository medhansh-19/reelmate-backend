"""Validated, immutable access to the versioned Story Song catalogue.

The bundled catalogue contains metadata and search queries only. It deliberately
does not contain audio, previews, streaming URLs, or availability assertions.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

CATALOG_PATH = Path(__file__).with_name("data") / "story_song_catalog.v2.json"
CATALOG_VERSION = "reelmate-curated-catalog-2026-08-v2"
CURATION_VERSION = "story-song-curation-2026-08-v2"

LanguageName = Literal["English", "Hindi", "Punjabi"]
VocalType = Literal["none", "vocal_texture", "sparse_lyrics", "full_lyrics"]
TempoBucket = Literal["slow", "medium", "fast"]
EraName = Literal["classical", "pre-2000", "2000s", "2010s", "2020s"]


class SongCatalogError(RuntimeError):
    """Raised when the bundled catalogue cannot be read or validated."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArtistRef(_FrozenModel):
    artist_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=120)


class MoodVector(_FrozenModel):
    calm: float = Field(ge=0, le=1)
    energetic: float = Field(ge=0, le=1)
    romantic: float = Field(ge=0, le=1)
    joyful: float = Field(ge=0, le=1)
    moody: float = Field(ge=0, le=1)
    dreamy: float = Field(ge=0, le=1)
    bold: float = Field(ge=0, le=1)
    nostalgic: float = Field(ge=0, le=1)


class PlatformRefs(_FrozenModel):
    """Optional identity references; these never imply regional availability."""

    spotify_track_id: str | None = Field(default=None, min_length=1, max_length=80)
    apple_music_id: str | None = Field(default=None, min_length=1, max_length=80)


class SongCatalogEntry(_FrozenModel):
    song_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    title: str = Field(min_length=1, max_length=180)
    artists: tuple[ArtistRef, ...] = Field(min_length=1, max_length=8)
    lyrics_languages: tuple[LanguageName, ...] = Field(max_length=3)
    vocal_type: VocalType
    bpm: int | None = Field(default=None, ge=30, le=260)
    tempo_bucket: TempoBucket
    energy_score: float = Field(ge=0, le=1)
    moods: MoodVector
    aesthetic_tags: tuple[str, ...] = Field(min_length=1, max_length=8)
    genre_tags: tuple[str, ...] = Field(min_length=1, max_length=6)
    era: EraName
    explicit: bool | None
    search_query: str = Field(min_length=3, max_length=240)
    platform_refs: PlatformRefs
    curation_version: Literal["story-song-curation-2026-08-v2"]

    @model_validator(mode="after")
    def validate_vocals_and_metadata(self) -> Self:
        if self.vocal_type == "none" and self.lyrics_languages:
            raise ValueError("no-lyrics entries cannot declare a lyrics language")
        if self.vocal_type != "none" and not self.lyrics_languages:
            raise ValueError("vocal entries must declare a lyrics language")
        if len(set(self.lyrics_languages)) != len(self.lyrics_languages):
            raise ValueError("lyrics languages must be unique")
        if len({artist.artist_id for artist in self.artists}) != len(self.artists):
            raise ValueError("artist IDs must be unique within each song")
        if len({tag.casefold() for tag in self.aesthetic_tags}) != len(self.aesthetic_tags):
            raise ValueError("aesthetic tags must be unique within each song")
        if len({tag.casefold() for tag in self.genre_tags}) != len(self.genre_tags):
            raise ValueError("genre tags must be unique within each song")
        return self


class StorySongCatalog(_FrozenModel):
    catalog_version: Literal["reelmate-curated-catalog-2026-08-v2"]
    description: str = Field(min_length=1, max_length=500)
    contains_audio: Literal[False]
    asserts_platform_availability: Literal[False]
    songs: tuple[SongCatalogEntry, ...]

    @model_validator(mode="after")
    def validate_catalog(self) -> Self:
        if len(self.songs) != 96:
            raise ValueError("v2 catalogue must contain exactly 96 songs")

        song_ids = [song.song_id for song in self.songs]
        if len(set(song_ids)) != len(song_ids):
            raise ValueError("song IDs must be globally unique")

        identities_by_id: dict[str, str] = {}
        identities_by_name: dict[str, str] = {}
        platform_ids: set[tuple[str, str]] = set()
        for song in self.songs:
            for artist in song.artists:
                prior_name = identities_by_id.setdefault(artist.artist_id, artist.name)
                if prior_name != artist.name:
                    raise ValueError(f"artist ID {artist.artist_id!r} maps to multiple names")
                normalized_name = artist.name.casefold().strip()
                prior_id = identities_by_name.setdefault(normalized_name, artist.artist_id)
                if prior_id != artist.artist_id:
                    raise ValueError(f"artist name {artist.name!r} maps to multiple IDs")
            for provider, value in (
                ("spotify", song.platform_refs.spotify_track_id),
                ("apple_music", song.platform_refs.apple_music_id),
            ):
                if value is None:
                    continue
                identity = (provider, value)
                if identity in platform_ids:
                    raise ValueError(f"duplicate {provider} track ID {value!r}")
                platform_ids.add(identity)

        no_lyrics = sum(song.vocal_type == "none" for song in self.songs)
        language_counts = {
            language: sum(
                song.vocal_type != "none" and language in song.lyrics_languages
                for song in self.songs
            )
            for language in ("English", "Hindi", "Punjabi")
        }
        if no_lyrics != 32:
            raise ValueError("v2 catalogue must contain exactly 32 no-lyrics tracks")
        if language_counts != {"English": 24, "Hindi": 24, "Punjabi": 16}:
            raise ValueError("v2 vocal coverage must be English=24, Hindi=24, and Punjabi=16")
        return self


@cache
def load_story_song_catalog() -> StorySongCatalog:
    """Load and validate the bundled catalogue once per worker process."""

    try:
        payload = CATALOG_PATH.read_bytes()
    except OSError as exc:
        raise SongCatalogError(f"could not read story song catalogue: {CATALOG_PATH}") from exc
    try:
        return StorySongCatalog.model_validate_json(payload)
    except ValidationError as exc:
        raise SongCatalogError(f"invalid story song catalogue: {exc}") from exc


# Importing this module fails immediately if the packaged data is missing or invalid.
STORY_SONG_CATALOG = load_story_song_catalog()
STORY_SONGS: tuple[SongCatalogEntry, ...] = STORY_SONG_CATALOG.songs


__all__ = [
    "CATALOG_VERSION",
    "CURATION_VERSION",
    "STORY_SONGS",
    "STORY_SONG_CATALOG",
    "ArtistRef",
    "MoodVector",
    "PlatformRefs",
    "SongCatalogEntry",
    "SongCatalogError",
    "StorySongCatalog",
    "load_story_song_catalog",
]
