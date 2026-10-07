# ReelMate implementation plan

Status: implemented locally; external provider deployment remains manual.

## Product goal

ReelMate owns the intelligence instead of forwarding creator media to a general-purpose
generative model. It provides two private, explainable workflows:

- `video_coach`: video measurements, versioned readiness scoring, and local timestamped
  coaching;
- `story_song`: image computer vision, visual-to-mood projection, and diversified song
  ranking with either balanced or no-lyrics output.

## Implemented architecture

1. Expo authenticates through a dedicated Supabase project, then gates new accounts through
   a four-step first-party music onboarding.
2. FastAPI creates a user-owned row and short-lived exact-size private R2 PUT.
3. The app uploads directly to R2 and submits the job.
4. A PostgreSQL queue and lease let a separate worker claim it safely.
5. The worker branches on `analysis_mode`:
   - video: FFmpeg/OpenCV/librosa/Tesseract extraction, deterministic scoring, local
     coaching rules;
   - image: Pillow/OpenCV validation/features, mood projection, and diversified song
     MMR ranking.
6. The worker persists reduced versioned results and queues source deletion.
7. Mobile polls, resumes, cancels, retries, renders mode-specific results and mixed history.
8. Authenticated users choose languages, moods, favorite artists/tracks, and a default sound
   format across four focused screens. The final `PUT /v1/music-preferences` marks onboarding
   complete, and Profile reopens the same flow for later edits; the row is isolated by
   Supabase RLS.

## Model ownership

The current recommendation system is fully local and versioned. The visual-only path is
reproducible for the same media and versions:

- video pipeline: `pipeline-v1`;
- video score: `score-v1`;
- video coaching: `local-coach-v2` / `coaching-rules-2026-08`;
- image pipeline: `story-vision-v1`;
- image-to-song ranker: `visual-song-mmr-v2`;
- song catalogue: `reelmate-curated-catalog-2026-08-v2`.

Story ranking combines a measured image feature vector, a fixed versioned mood projection,
cosine similarity, energy compatibility, visual/aesthetic tag matching, and MMR artist
diversification. The catalogue contains 96 entries: 32 no-lyrics, 24 English, 24 Hindi,
and 16 Punjabi. Story requests accept `vocal_preference=any` or the hard-filtered
`vocal_preference=no_lyrics`.

This v2 is an efficient deterministic content-based baseline: its visual-to-mood weights and
song labels are fixed/curated, not learned from a labeled relevance dataset. It genuinely analyzes
each image locally, but it must not be described as a trained ranking model until opt-in outcomes
have been collected, evaluated, and used to fit a later version.

First-party preferred languages, moods, favorite artists/tracks, and default vocal format
can provide a small reranking bonus; the image remains the dominant signal and the result
discloses both supplied and actually matched signals. Preferences are resolved atomically at
processing start; each result records the preference revision and update time used. Historical
preference values are not duplicated into every result, so taste-adjusted results are attributed
but are not promised to be replayable after that preference row changes. Every result includes a
feature summary, match percentage, matching moods, explanation, vocal metadata, aesthetic tags,
and model/catalogue versions.

This direct-input onboarding is the implemented replacement for Spotify history import. The
client shows one decision group at a time with `1 of 4` progress, optional skips for preference
steps, and one final save. `music_preferences.onboarding_completed_at` is set by the backend only
when `complete_onboarding=true`; it distinguishes a genuinely completed or skipped setup from a
new profile whose preference arrays happen to be empty.

Spotify listening-history personalization is intentionally excluded. The current
[Spotify Developer Policy](https://developer.spotify.com/policy) prohibits analyzing Spotify
Content or the Spotify Service to build user profiles and prohibits ingesting Spotify Content
into ML/AI systems. No Spotify credential should be created for the present design. Any future,
separately approved integration would also need to account for
[Spotify Web API quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes).

## Safety and privacy

- No GPT or external inference call.
- No public R2 objects.
- No database or R2 secret in the mobile build.
- Exact MIME and byte-length constraints at app, API, signed upload and worker layers.
- Maximum video: 100 MB / 90 seconds.
- Maximum image: 15 MB / 40 megapixels; JPEG, PNG or WebP.
- Raw OCR, frames, images, videos, temp paths and signed URLs are not persisted.
- Durable outbox cleans up after success, failure, cancellation, expiry, deletion and
  Supabase account cascade deletion.
- RLS gives authenticated clients SELECT-only access to their rows.
- The `music_preferences` table is user-owned; authenticated clients have RLS-protected
  SELECT-only access, while writes go through the authenticated FastAPI endpoint.

## Evaluation plan

Before beta:

1. Assemble an opt-in image set covering portraits, travel, food, fashion, celebrations,
   low light, nature, minimal frames and multiple skin tones.
2. Collect creator ratings for relevance, save, skip, and preferred language.
3. Split users—not images—between train/validation/test sets to avoid identity leakage.
4. Compare against popularity-only, random and mood-only baselines.
5. Track Recall@5, NDCG@5, catalogue coverage, artist diversity, language satisfaction,
   save rate and skip rate.
6. Fit a new ranker only from licensed/consented data and release a new immutable version.
7. Keep the present version available for replay and rollback.

For Video Coach, maintain golden fixture videos and assert stable signal schemas, scores,
timestamps and issue codes. Do not claim reach prediction without real outcome labels.

## Remaining manual work

- Create and migrate a new dedicated Supabase project.
- Create a new private R2 bucket and fresh scoped credentials.
- Deploy public API and private worker separately.
- Configure mobile public values and Auth redirects.
- Run physical-device/staging end-to-end tests.
- Verify new-account onboarding gating, all four save/skip paths, sign-in resumption, and the
  Profile edit path on physical iOS and Android devices.
- Human-QA the credits and all 32 no-lyrics classifications, then region-check the bundled
  catalogue before production release; structural validation does not guarantee musical labels
  or Instagram Music availability.
- Configure privacy disclosures, monitoring, backup/restore and retention operations.

See [docs/EXTERNAL_CONNECTIONS.md](docs/EXTERNAL_CONNECTIONS.md) for exact steps.
