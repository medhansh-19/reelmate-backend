from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError

from app.song_catalog import CATALOG_VERSION, STORY_SONGS
from app.story_recommender import (
    STORY_RANKER_VERSION,
    StoryPipelineError,
    StoryTasteProfile,
    _preference_bonus,
    analyze_story_image,
)


def _write_image(path: Path, rgb: tuple[int, int, int]) -> None:
    pixels = np.zeros((480, 270, 3), dtype=np.uint8)
    pixels[:, :] = rgb
    pixels[120:360, 75:195] = np.clip(np.array(rgb) + 35, 0, 255)
    Image.fromarray(pixels).save(path, format="JPEG", quality=92)


def test_story_ranker_is_deterministic_private_and_diversified(tmp_path: Path) -> None:
    image = tmp_path / "warm-story.jpg"
    _write_image(image, (205, 132, 72))

    first = analyze_story_image(image)
    second = analyze_story_image(image)

    assert first == second
    assert first.mode == "story_song"
    assert first.privacy.model_dump() == {
        "external_api_used": False,
        "source_included_in_result": False,
        "source_cleanup": "durable_outbox",
    }
    assert len(first.recommendations) == 5
    assert len({song.artist for song in first.recommendations}) == 5
    assert all(0 <= song.match_score <= 100 for song in first.recommendations)
    assert all(song.why and song.search_query for song in first.recommendations)
    assert "warm" in first.image_summary.visual_tags
    assert first.schema_version == "3"
    assert first.versions["catalog"] == CATALOG_VERSION
    assert first.versions["ranking_model"] == STORY_RANKER_VERSION
    assert first.personalization.spotify_data_used is False


def test_different_visual_moods_change_the_ranking(tmp_path: Path) -> None:
    warm = tmp_path / "warm.jpg"
    dark = tmp_path / "dark.jpg"
    _write_image(warm, (230, 165, 90))
    _write_image(dark, (24, 30, 55))

    warm_result = analyze_story_image(warm)
    dark_result = analyze_story_image(dark)

    assert warm_result.image_summary.brightness > dark_result.image_summary.brightness
    assert [item.song_id for item in warm_result.recommendations] != [
        item.song_id for item in dark_result.recommendations
    ]


def test_invalid_story_image_is_rejected(tmp_path: Path) -> None:
    invalid = tmp_path / "fake.jpg"
    invalid.write_bytes(b"not an image")

    with pytest.raises(StoryPipelineError) as raised:
        analyze_story_image(invalid)

    assert raised.value.code == "IMAGE_INVALID"


def test_no_lyrics_mode_is_a_hard_catalog_filter(tmp_path: Path) -> None:
    image = tmp_path / "aesthetic.jpg"
    _write_image(image, (75, 86, 118))

    result = analyze_story_image(image, vocal_preference="no_lyrics")

    assert result.requested_vocal_preference == "no_lyrics"
    assert len(result.recommendations) == 5
    assert len({song.artist for song in result.recommendations}) == 5
    assert all(song.vocal_type == "none" for song in result.recommendations)
    assert all(song.has_lyrics is False for song in result.recommendations)
    assert all(song.language == "Instrumental" for song in result.recommendations)


def test_first_party_taste_is_capped_and_disclosed_without_spotify(tmp_path: Path) -> None:
    image = tmp_path / "personalized.jpg"
    _write_image(image, (198, 125, 78))
    taste = StoryTasteProfile(
        preferred_languages=["Hindi", "Instrumental"],
        preferred_moods=["romantic", "dreamy"],
        favorite_artists=["Anuv Jain"],
        favorite_tracks=["Experience"],
    )

    result = analyze_story_image(image, taste_profile=taste)

    assert result.personalization.model_dump() == {
        "applied": True,
        "source": "first_party",
        "signals_provided": [
            "preferred_languages",
            "preferred_moods",
            "favorite_artists",
            "favorite_tracks",
        ],
        "signals_used": [
            "preferred_languages",
            "preferred_moods",
            "favorite_tracks",
        ],
        "profile_version": "1",
        "profile_revision": None,
        "profile_updated_at": None,
        "resolution": "processing_start",
        "spotify_data_used": False,
    }
    assert all("Spotify" not in song.why for song in result.recommendations)


def test_unmatched_first_party_values_are_disclosed_but_not_claimed_as_applied(
    tmp_path: Path,
) -> None:
    image = tmp_path / "unmatched-taste.jpg"
    _write_image(image, (132, 142, 160))

    result = analyze_story_image(
        image,
        taste_profile=StoryTasteProfile(favorite_artists=["Unknown Artist 404"]),
    )

    assert result.personalization.applied is False
    assert result.personalization.source == "first_party"
    assert result.personalization.signals_provided == ["favorite_artists"]
    assert result.personalization.signals_used == []
    assert result.personalization.resolution == "processing_start"


def test_catalog_v2_has_requested_coverage_and_no_platform_claims() -> None:
    assert len(STORY_SONGS) == 96
    assert sum(song.vocal_type == "none" for song in STORY_SONGS) == 32
    assert (
        sum(
            song.vocal_type != "none" and "English" in song.lyrics_languages for song in STORY_SONGS
        )
        == 24
    )
    assert (
        sum(song.vocal_type != "none" and "Hindi" in song.lyrics_languages for song in STORY_SONGS)
        == 24
    )
    assert (
        sum(
            song.vocal_type != "none" and "Punjabi" in song.lyrics_languages for song in STORY_SONGS
        )
        == 16
    )
    assert all(song.platform_refs.spotify_track_id is None for song in STORY_SONGS)


def test_ambiguous_track_title_requires_artist_identity() -> None:
    lover_tracks = [song for song in STORY_SONGS if song.title == "Lover"]
    assert len(lover_tracks) == 2

    ambiguous = StoryTasteProfile(favorite_tracks=["Lover"])
    assert all(
        "favorite_tracks" not in _preference_bonus(song, ambiguous)[1] for song in lover_tracks
    )

    specific = StoryTasteProfile(favorite_tracks=["Lover Taylor Swift"])
    matches = {
        song.song_id: "favorite_tracks" in _preference_bonus(song, specific)[1]
        for song in lover_tracks
    }
    assert matches == {"lover-taylor-swift": True, "lover-diljit-dosanjh": False}


def test_first_party_bonus_is_hard_capped() -> None:
    experience = next(song for song in STORY_SONGS if song.song_id == "experience-ludovico-einaudi")
    taste = StoryTasteProfile(
        preferred_languages=["Instrumental"],
        preferred_moods=["calm", "dreamy"],
        favorite_artists=["Ludovico Einaudi"],
        favorite_tracks=["Experience"],
    )

    bonus, matches = _preference_bonus(experience, taste)

    assert bonus == 0.08
    assert set(matches) == {
        "preferred_languages",
        "preferred_moods",
        "favorite_artists",
        "favorite_tracks",
    }


def test_result_model_enforces_no_lyrics_and_unique_song_contract(tmp_path: Path) -> None:
    image = tmp_path / "contract.jpg"
    _write_image(image, (80, 90, 120))
    result = analyze_story_image(image)
    payload = result.model_dump(mode="json")
    payload["requested_vocal_preference"] = "no_lyrics"

    with pytest.raises(ValidationError, match="no_lyrics"):
        type(result).model_validate(payload)

    payload = result.model_dump(mode="json")
    payload["recommendations"][1]["song_id"] = payload["recommendations"][0]["song_id"]
    with pytest.raises(ValidationError, match="unique song IDs"):
        type(result).model_validate(payload)
