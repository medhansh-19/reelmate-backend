# ReelMate

ReelMate is a private creator-media analysis product with two modes:

1. **Video Coach** measures a reel's hook, scenes, pacing, motion, faces, OCR timing,
   audio energy, silence, tempo, and cut-to-beat alignment. It returns a stable Reel
   Readiness Score and timestamped edits from ReelMate's local coaching engine.
2. **Story Song Match** measures an image's light, color, warmth, contrast, texture,
   composition, orientation, and faces. It projects those signals into a mood profile
   and ranks matching songs with a local, diversified MMR recommender. Users can request
   either the best overall match or aesthetic music with no lyrics.

No GPT or generative recommendation API is used. The source image/video is processed
by ReelMate's worker and queued for deletion after processing.

## Architecture

```text
Expo app
  |-- Supabase Auth access token
  |-- POST analysis metadata
  |-- direct private PUT to R2
  `-- submit/poll/cancel/retry/history

FastAPI API
  |-- verifies Supabase JWT from JWKS
  |-- owns all database mutations
  `-- creates short-lived, exact-size R2 uploads

PostgreSQL / Supabase
  |-- analysis rows and durable worker leases
  |-- video_coach and story_song modes
  |-- user-owned first-party music preferences
  `-- durable source-deletion outbox + RLS

Worker
  |-- video: FFmpeg/OpenCV/librosa/Tesseract -> scores -> local coaching
  |-- image: Pillow/OpenCV -> mood projection -> song MMR ranker
  `-- deletes private source through the durable outbox
```

The API and worker are separate processes built from the same image. The worker never
exposes a public listener.

## Product contracts

### Video Coach

- MP4 or MOV
- Maximum 100 MB
- Maximum 90 seconds
- Full video remains inside ReelMate-controlled storage/worker infrastructure
- OCR text and extracted frames are temporary and are not persisted
- Scores and coaching are reproducible for the same versioned pipeline

The Reel Readiness Score is an experimental editing-quality signal, not a promise of
views or virality. Live trend prediction is excluded until a real data source exists.

### Story Song Match

- JPEG, PNG, or WebP
- Maximum 15 MB
- Image is cropped to story aspect ratio by the mobile picker where supported
- OpenCV's trained face detector plus classical computer-vision signals build the
  visual feature vector
- A versioned visual-to-mood projection and diversified nearest-neighbour search rank
  the local song catalogue
- The bundled v2 catalogue contains 96 tracks: 32 no-lyrics, 24 English, 24 Hindi,
  and 16 Punjabi entries
- `vocal_preference` supports `any` and the hard-filtered `no_lyrics` mode
- Optional first-party preferences for languages, moods, artists, tracks, and the default
  vocal format lightly rerank candidates while the image remains the primary signal
- A four-step, first-party onboarding collects those preferences directly: languages,
  moods, favorite artists/tracks, then the default lyrical or no-lyrics format
- Each preference update receives a monotonic revision; results disclose the revision resolved
  at processing start and distinguish supplied preferences from signals that actually matched
- Every song includes a match score, matching moods, optional BPM, language, evidence,
  vocal metadata, aesthetic tags, and an exact Instagram Music search query

The bundled catalogue is stable, not a claim that a song is currently trending or
available in every account/region. Live catalogue availability is an optional future
connection. The current ranker is a deterministic content-based baseline with curated song
labels, not yet a model trained on ReelMate relevance outcomes.

## Local setup

Requirements:

- Python 3.12 or 3.13
- PostgreSQL/Supabase
- FFmpeg and ffprobe
- Tesseract
- libsndfile
- Node.js 24 and pnpm 11 for `mobile/`

```bash
python3.13 -m venv venv
venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
```

Use only credentials created for a new ReelMate Supabase project and a dedicated
private ReelMate R2 bucket. Never copy another application's database URL, token, or
storage credential.

Run the API:

```bash
python -m app.server
```

Run the worker separately:

```bash
python -m app.worker
```

Health endpoints:

- `GET /v1/health/live`
- `GET /v1/health/ready`

## API sequence

Create one analysis with a stable `Idempotency-Key`:

```http
POST /v1/analyses
Authorization: Bearer <supabase-access-token>
Idempotency-Key: <8-128-character-key>
Content-Type: application/json

{
  "mode": "story_song",
  "filename": "sunset.jpg",
  "content_type": "image/jpeg",
  "file_size_bytes": 2450000,
  "vocal_preference": "no_lyrics"
}
```

For a balanced story result use `"vocal_preference": "any"`. For video, use
`mode=video_coach` with `video/mp4` or `video/quicktime`; video analyses always use
`vocal_preference=any`.

Then:

1. PUT exact bytes to the returned private `upload.url` using its returned headers.
2. `POST /v1/analyses/{analysis_id}/submit`.
3. Poll `GET /v1/analyses/{analysis_id}` until terminal.
4. Use `POST .../cancel`, `POST .../retry`, or `DELETE ...` as appropriate.
5. Use `GET /v1/analyses?limit=20&cursor=...` for mixed-mode history.

Authenticated users can read or replace their first-party recommendation profile with
`GET /v1/music-preferences` and `PUT /v1/music-preferences`. The onboarding's final write
includes `"complete_onboarding": true`; the response exposes the server-owned nullable
`onboarding_completed_at` timestamp used by the mobile route gate. Later edits use the same
four focused screens from Profile without resetting that completion state.

## Database

Apply [the initial migration](supabase/migrations/202608090001_initial_schema.sql)
only to a new dedicated ReelMate Supabase project. It creates:

- `analysis_mode`, `analysis_status`, `analysis_stage`, and `story_vocal_preference` enums
- `analyses`
- `user_profiles`
- `music_preferences`, including its server-owned onboarding completion timestamp
- `source_deletion_outbox`
- constraints, indexes, RLS and user-owned policies
- an account-deletion trigger that preserves R2 cleanup work before cascade deletion

The backend does not require a Supabase service-role key. It verifies user access tokens
with the project's public JWKS and connects directly to the dedicated Postgres database.

## Mobile app

The Expo SDK 57 app is in `mobile/`.

```bash
cd mobile
cp .env.example .env
pnpm install --frozen-lockfile
pnpm start
```

Only the Supabase project URL, public publishable key, and public API URL belong in the
mobile environment. Database and R2 credentials must never ship in the app.

After authentication, new users complete a compact four-step music-taste onboarding before
entering the main tabs. It uses progressive disclosure, visible progress, strong selection
controls, and a single final save. Users can reopen the same flow from Profile at any time.

## Validation

```bash
make check
cd mobile && pnpm run check
```

The CI workflow runs backend tests/static checks, mobile frozen install/checks, Expo
Doctor, platform exports, package build checks, and a Docker build.

## Deployment and remaining connections

Read [External connections](docs/EXTERNAL_CONNECTIONS.md) before adding any real
credential. The only required providers are:

- a new dedicated Supabase project;
- a new private Cloudflare R2 bucket with fresh scoped credentials;
- separate API and worker deployments.

No OpenAI, GPT, Instagram/Meta, Spotify, onboarding service, or Supabase service-role
credential is required for the current implementation. Onboarding is first-party UI backed
by the existing ReelMate API and PostgreSQL row.

Spotify listening-history personalization is deliberately not implemented. The current
[Spotify Developer Policy](https://developer.spotify.com/policy) prohibits using Spotify
Content or the Spotify Service to build user profiles and prohibits ingesting Spotify
Content into ML/AI systems. Do not create Spotify credentials for this feature. See
[Spotify Web API quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)
for additional restrictions that would apply to any separately approved future integration.
