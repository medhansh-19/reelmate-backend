"""Authenticated first-party music taste settings.

These values are entered directly by the user. ReelMate deliberately does not
derive them from Spotify or another listening service.
"""

from __future__ import annotations

from fastapi import APIRouter

from app import repository
from app.db import MusicPreference, StoryVocalPreference
from app.dependencies import SessionDep, UserDep
from app.schemas import MusicPreferenceResponse, MusicPreferenceUpdateRequest

router = APIRouter(prefix="/music-preferences", tags=["music-preferences"])


def _response(preference: MusicPreference | None) -> MusicPreferenceResponse:
    if preference is None:
        return MusicPreferenceResponse()
    return MusicPreferenceResponse(
        preferred_languages=preference.preferred_languages,
        preferred_moods=preference.preferred_moods,
        favorite_artists=preference.favorite_artists,
        favorite_tracks=preference.favorite_tracks,
        default_vocal_preference=preference.default_vocal_preference.value,
        profile_version=preference.profile_version,
        revision=preference.revision,
        updated_at=preference.updated_at,
        onboarding_completed_at=preference.onboarding_completed_at,
    )


@router.get("", response_model=MusicPreferenceResponse)
async def get_music_preferences(
    user: UserDep,
    session: SessionDep,
) -> MusicPreferenceResponse:
    preference = await repository.get_music_preference(session, user_id=user.id)
    return _response(preference)


@router.put("", response_model=MusicPreferenceResponse)
async def update_music_preferences(
    body: MusicPreferenceUpdateRequest,
    user: UserDep,
    session: SessionDep,
) -> MusicPreferenceResponse:
    preference = await repository.upsert_music_preference(
        session,
        user_id=user.id,
        preferred_languages=body.preferred_languages,
        preferred_moods=body.preferred_moods,
        favorite_artists=body.favorite_artists,
        favorite_tracks=body.favorite_tracks,
        default_vocal_preference=StoryVocalPreference(body.default_vocal_preference),
        complete_onboarding=body.complete_onboarding,
    )
    return _response(preference)
