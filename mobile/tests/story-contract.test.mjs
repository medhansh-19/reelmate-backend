import assert from 'node:assert/strict';
import test from 'node:test';

import {
  musicPreferenceSchema,
  storySongResultSchema,
} from '../src/lib/api-schemas.ts';
import { demoGetAnalysis, demoStartAnalysis } from '../src/lib/demo-api.ts';

const recommendation = (songId) => ({
  song_id: songId,
  title: `Tune ${songId}`,
  artist: `Artist ${songId}`,
  language: 'Instrumental',
  match_score: 88,
  bpm: null,
  energy: 'medium',
  vocal_type: 'none',
  has_lyrics: false,
  aesthetic_tags: ['dreamy'],
  matched_moods: ['dreamy', 'calm'],
  why: 'The measured image mood matches this no-lyrics tune.',
  search_query: `Tune ${songId} Artist ${songId}`,
});

const validStoryResult = () => ({
  schema_version: '3',
  mode: 'story_song',
  requested_vocal_preference: 'no_lyrics',
  score: 88,
  confidence: 0.82,
  image_summary: {
    width: 1080,
    height: 1920,
    brightness: 0.7,
    saturation: 0.6,
    contrast: 0.5,
    warmth: 0.7,
    colorfulness: 0.6,
    edge_density: 0.3,
    center_activity: 0.4,
    face_count: 1,
    face_prominence: 0.2,
    dominant_colors: ['gold'],
    visual_tags: ['portrait', 'warm'],
    mood_profile: {
      calm: 0.2,
      energetic: 0.3,
      romantic: 0.5,
      joyful: 0.4,
      moody: 0.1,
      dreamy: 0.45,
      bold: 0.2,
      nostalgic: 0.35,
    },
  },
  recommendations: [
    recommendation('one'),
    recommendation('two'),
    recommendation('three'),
  ],
  personalization: {
    applied: false,
    source: 'none',
    signals_provided: [],
    signals_used: [],
    profile_version: null,
    profile_revision: null,
    profile_updated_at: null,
    resolution: 'none',
    spotify_data_used: false,
  },
  versions: {
    pipeline: 'story-vision-v1',
    ranking_model: 'visual-song-mmr-v2',
    catalog: 'test-catalog',
  },
  privacy: {
    external_api_used: false,
    source_included_in_result: false,
    source_cleanup: 'durable_outbox',
  },
});

const validMusicPreference = (overrides = {}) => ({
  preferred_languages: ['English', 'Instrumental'],
  preferred_moods: ['dreamy', 'calm'],
  favorite_artists: ['The xx'],
  favorite_tracks: [],
  default_vocal_preference: 'any',
  profile_version: '1',
  revision: 1,
  updated_at: '2026-08-09T12:00:00.000Z',
  onboarding_completed_at: null,
  ...overrides,
});

test('mobile schema enforces the no-lyrics and unique-song contract', () => {
  assert.equal(
    storySongResultSchema.safeParse(validStoryResult()).success,
    true,
  );

  const lyrical = validStoryResult();
  lyrical.recommendations[0] = {
    ...lyrical.recommendations[0],
    language: 'English',
    vocal_type: 'full_lyrics',
    has_lyrics: true,
  };
  assert.equal(storySongResultSchema.safeParse(lyrical).success, false);

  const duplicate = validStoryResult();
  duplicate.recommendations[1].song_id = duplicate.recommendations[0].song_id;
  assert.equal(storySongResultSchema.safeParse(duplicate).success, false);
});

test('mobile preference schema matches backend artist limits', () => {
  const result = musicPreferenceSchema.safeParse(
    validMusicPreference({
      favorite_artists: ['a'.repeat(101)],
    }),
  );

  assert.equal(result.success, false);
});

test('mobile preference schema distinguishes pending and completed onboarding', () => {
  const pending = musicPreferenceSchema.safeParse(validMusicPreference());
  assert.equal(pending.success, true);
  assert.equal(pending.data?.onboarding_completed_at, null);

  const completedAt = '2026-08-09T12:05:00.000Z';
  const completed = musicPreferenceSchema.safeParse(
    validMusicPreference({ onboarding_completed_at: completedAt }),
  );
  assert.equal(completed.success, true);
  assert.equal(completed.data?.onboarding_completed_at, completedAt);

  const missingCompletionState = validMusicPreference();
  delete missingCompletionState.onboarding_completed_at;
  assert.equal(
    musicPreferenceSchema.safeParse(missingCompletionState).success,
    false,
  );
  assert.equal(
    musicPreferenceSchema.safeParse(
      validMusicPreference({ onboarding_completed_at: 'not-a-timestamp' }),
    ).success,
    false,
  );
});

test('demo no-lyrics jobs use a snapshot and never claim static taste was applied', async () => {
  const originalNow = Date.now;
  let now = originalNow();
  Date.now = () => now;
  try {
    const started = await demoStartAnalysis('story_song', 'no_lyrics', {
      preferred_languages: [],
      preferred_moods: [],
      favorite_artists: [],
      favorite_tracks: [],
      default_vocal_preference: 'no_lyrics',
      profile_version: '1',
      revision: 3,
      updated_at: '2026-08-09T12:00:00.000Z',
      onboarding_completed_at: '2026-08-09T11:55:00.000Z',
    });
    now += 20_000;

    const completed = await demoGetAnalysis(started.analysis_id);
    const parsed = storySongResultSchema.parse(completed.result);
    assert.equal(parsed.requested_vocal_preference, 'no_lyrics');
    assert.ok(parsed.recommendations.every((song) => !song.has_lyrics));
    assert.equal(parsed.personalization.applied, false);
    assert.deepEqual(parsed.personalization.signals_provided, []);
    assert.equal(parsed.personalization.profile_revision, 3);
  } finally {
    Date.now = originalNow;
  }
});
