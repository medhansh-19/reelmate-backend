# ReelMate external connections

This is the canonical production connection checklist. Every checkbox starts incomplete.
Repository code and tests do not create or verify production accounts.

## Strict isolation rule

Create every required project, bucket, token, password, and deployment specifically for
ReelMate. Never copy a database URL, API credential, user table, OAuth client, storage
token, or billing setup from another application.

No GPT/OpenAI credential is used or needed. ReelMate performs video coaching and image
song ranking inside its own worker.

## Environment variables

Create a new `.env` from `.env.example` instead of reusing another project's file:

```dotenv
APP_ENV=development
LOG_LEVEL=INFO
CORS_ORIGINS=http://localhost:3000

DATABASE_URL=
SUPABASE_URL=
SUPABASE_JWT_AUDIENCE=authenticated
SUPABASE_JWT_ISSUER=

R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=reelmate-videos
R2_KEY_PREFIX=reelmate/analyses
R2_UPLOAD_EXPIRY_SECONDS=900

WORKER_ID=reelmate-worker-1
WORKER_POLL_SECONDS=2
WORKER_LEASE_SECONDS=600
WORKER_JOB_TIMEOUT_SECONDS=600
WORKER_MAX_ATTEMPTS=3

MAX_VIDEO_BYTES=100000000
MAX_VIDEO_DURATION_SECONDS=90
MAX_IMAGE_BYTES=15000000
SOURCE_RETENTION_HOURS=24
```

Backend-only secrets are `DATABASE_URL`, `R2_ACCESS_KEY_ID`, and
`R2_SECRET_ACCESS_KEY`. Never put them in Expo `EXPO_PUBLIC_` variables.

## 1. New Supabase project

Official references:

- [Supabase CLI migration workflow](https://supabase.com/docs/guides/local-development/cli-workflows)
- [Database connection modes](https://supabase.com/docs/guides/database/connecting-to-postgres)
- [JWT signing keys and JWKS](https://supabase.com/docs/guides/auth/signing-keys)
- [Mobile redirect URLs](https://supabase.com/docs/guides/auth/redirect-urls)

Create an empty project named for ReelMate and the environment, for example
`reelmate-staging`. Generate a new database password and record the new project ref.

Initialize the local Supabase folder only if `supabase/config.toml` is absent:

```bash
test -f supabase/config.toml || supabase init
supabase login
supabase link --project-ref <NEW_REELMATE_REF>
supabase projects list
supabase db push --dry-run
supabase db push
```

Verify the target project reference immediately before `db push`. Never use `db pull` to
import another application's schema and never use `db reset --linked` on production.

After migration, inspect:

- `public.analyses`, `public.user_profiles`, `public.music_preferences`, and
  `public.source_deletion_outbox`;
- both `video_coach` and `story_song` values in `analysis_mode`;
- both `any` and `no_lyrics` values in `story_vocal_preference` and the rule that video
  analyses must use `any`;
- MIME/size constraints for videos and images;
- RLS on every table;
- own-row SELECT policies for analysis/profile/music-preference rows; preference writes go
  through the authenticated FastAPI endpoint;
- nullable `music_preferences.onboarding_completed_at`; clients can request completion through
  the API but cannot forge its server timestamp directly;
- no anonymous privileges and no client access to the deletion outbox.

Use the new project's Connect panel for `DATABASE_URL`. Prefer direct Postgres when the
hosting network supports it; otherwise use Supavisor session mode for persistent API and
worker containers. Require TLS and check the connection limit across all replicas.

Configure asymmetric Auth signing keys so this endpoint returns RS256 or ES256 public
keys:

```text
https://<NEW_REELMATE_REF>.supabase.co/auth/v1/.well-known/jwks.json
```

The backend derives the issuer from `SUPABASE_URL`, verifies audience/issuer/expiry/user
role, and rejects tokens issued by a different Supabase project.

The mobile app needs only the new project's public URL and publishable/anon key. Configure
email Auth and, if desired, create a fresh ReelMate Google OAuth client with the app's
development/production deep-link redirects.

## 2. New private Cloudflare R2 bucket

Official references:

- [Create R2 buckets](https://developers.cloudflare.com/r2/buckets/create-buckets/)
- [R2 API credentials](https://developers.cloudflare.com/r2/api/tokens/)
- [Presigned URLs](https://developers.cloudflare.com/r2/api/s3/presigned-urls/)
- [Bucket CORS](https://developers.cloudflare.com/r2/buckets/cors/)
- [Object lifecycle rules](https://developers.cloudflare.com/r2/buckets/object-lifecycles/)

Create a dedicated private bucket such as `reelmate-videos`. Keep public development URLs
and public custom-domain access disabled.

Create a new S3-compatible token with Object Read & Write permission scoped only to this
bucket. The API signs exact-size PUT requests; the worker must read and delete the objects.
Store both credential values only in API/worker secret stores.

For Expo web, set exact CORS origins. Native iOS/Android clients do not enforce browser
CORS. Example:

```json
[
  {
    "AllowedOrigins": ["http://localhost:3000", "https://app.example.com"],
    "AllowedMethods": ["PUT"],
    "AllowedHeaders": ["Content-Type"],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3600
  }
]
```

Replace or remove placeholder origins. Do not use `*` for production creator uploads.

Add a lifecycle expiration under `reelmate/analyses/` as a safety net. The application
already uses a durable PostgreSQL deletion outbox after completion, cancellation,
expiration, row deletion, and account cascade deletion. Test forced R2 failures and verify
the outbox retries before relying on it.

## 3. API and worker deployment

Build one reviewed Docker image and run it as two services:

```bash
# public HTTPS service
python -m app.server

# private background service
python -m app.worker
```

Requirements:

- API is the only publicly reachable service.
- Worker has outbound access to Postgres and R2 only; no model API is required.
- Image includes FFmpeg/ffprobe, Tesseract, libsndfile, Pillow, NumPy, OpenCV and librosa.
- Every worker replica has a unique `WORKER_ID`.
- API and worker use the same dedicated database, bucket, prefix and media limits.
- Health checks use `/v1/health/live` and `/v1/health/ready`.
- Logs exclude bearer tokens, signed URLs, filenames, raw OCR, images and videos.

Start with one worker per CPU allocation and measure queue time, video processing latency,
image-ranking latency, memory, local compute cost and deletion-outbox age before scaling.

## 4. Mobile connection

Create `mobile/.env` from the mobile template:

```dotenv
EXPO_PUBLIC_SUPABASE_URL=https://<NEW_REELMATE_REF>.supabase.co
EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<NEW_PUBLIC_KEY>
EXPO_PUBLIC_API_URL=https://<REELMATE_API_HOST>
EXPO_PUBLIC_DEMO_MODE=false
```

These values are public at build time. Mobile must never contain the database password,
service-role key, R2 token, or any unrelated project credential.

Confirm the bundle identifiers and deep-link scheme in `mobile/app.json` are available
before registering app-store/OAuth settings.

Test on physical iOS and Android devices:

- email/Google login and redirect return;
- other-project token rejection;
- MP4/MOV upload, backgrounding, submit/poll/resume, cancellation and retry;
- JPEG/PNG/WebP selection, 9:16 editing, upload and song-match result;
- balanced and hard-filtered no-lyrics story recommendations;
- loading, saving, and reusing the authenticated user's first-party music preferences;
- new-account gating through all four onboarding screens, completion after the final save,
  resumption after sign-in, and reopening the same flow from Profile;
- exact content type/length on R2 PUT;
- completed mixed-mode history and deletion;
- no secret or source-media content in logs/crash reports.

## Music catalogue and Spotify policy boundary

The current song recommender works without Spotify, Instagram or another music API. It
uses the local `reelmate-curated-catalog-2026-08-v2` catalogue with 96 metadata entries:
32 no-lyrics, 24 English, 24 Hindi, and 16 Punjabi. It returns an exact search query because
song availability differs by region and account.

Spotify listening-history import or personalization is deliberately not implemented. The
current [Spotify Developer Policy](https://developer.spotify.com/policy) prohibits analyzing
Spotify Content or the Spotify Service to build user profiles and prohibits ingesting Spotify
Content into an ML/AI model or system. Do not create a Spotify app, OAuth client, client secret,
or user-token storage for ReelMate's recommendation profile under the current design.

If Spotify grants explicit written approval for a materially different future integration,
review the policy again and separately account for
[Spotify Web API quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)
before writing code or collecting tokens. Approval and a new policy/legal review are prerequisites,
not launch tasks.

The implemented alternative is an authenticated first-party profile. A four-step mobile
onboarding asks users for (1) languages, (2) moods, (3) favorite artists/tracks, and (4) their
default `any` or `no_lyrics` format. It uses `GET /v1/music-preferences` and one final
`PUT /v1/music-preferences` with `complete_onboarding=true`; Profile provides the edit path.
These preferences are stored in `public.music_preferences` with user-owned RLS and only lightly
rerank the image-first result. The server-owned `onboarding_completed_at` timestamp drives the
new-account gate. Each update increments an atomic revision; completed results record the
revision and timestamp resolved at processing start without duplicating the full taste profile.

This onboarding adds no external provider, SDK, OAuth scope, API key, or billable API call. It
uses the existing ReelMate API, dedicated Supabase Postgres database, and Supabase Auth session.

Optional future improvements—not required for launch—are:

- a properly licensed regional music catalogue;
- a maintained trend feed;
- opt-in save/skip feedback used to train the next ranking weights.

Instagram/Meta does not need to be connected for the current flow because ReelMate does
not publish stories or fetch account data.

## Manual checklist

### Isolation and credentials

- [ ] New empty Supabase project created only for ReelMate.
- [ ] No credentials, schema, users or billing project copied from another app.
- [ ] New private R2 bucket created only for ReelMate.
- [ ] Fresh bucket-scoped R2 credentials stored in deployment secret stores.
- [ ] Any previously exposed GitHub PAT or provider secret was revoked, not reused.

### Supabase

- [ ] CLI link verified against `<NEW_REELMATE_REF>`.
- [ ] Dry run showed only the expected ReelMate migration.
- [ ] Migration applied and schema/RLS/constraints inspected.
- [ ] `music_preferences` own-row reads and authenticated API writes verified with two users.
- [ ] `onboarding_completed_at` starts null, is server-stamped after completion, and cannot be
      written directly through Supabase by a mobile client.
- [ ] Asymmetric Auth signing keys and JWKS verified.
- [ ] Email and optional Google Auth redirects configured.
- [ ] API and worker tested against the new database over TLS.
- [ ] Token from another Supabase project returns HTTP 401.

### R2

- [ ] Public access disabled.
- [ ] Credentials scoped only to the ReelMate bucket.
- [ ] Exact-origin browser CORS configured where needed.
- [ ] Video and image signed PUTs enforce size/type and expire.
- [ ] Lifecycle backstop configured and tested.
- [ ] Durable cleanup tested for complete/cancel/delete/expiry/account deletion.

### Deployment and app

- [ ] API and worker deployed separately from the same reviewed image.
- [ ] Each worker has a unique ID.
- [ ] Mobile points only to the new Supabase project and ReelMate API.
- [ ] Both product modes pass physical-device end-to-end tests.
- [ ] Story mode passes both `any` and `no_lyrics`, and saved first-party preferences
      affect only the owning user's results.
- [ ] New users cannot enter the main tabs before onboarding completion; completing or skipping
      the flow persists once, and Profile edits do not clear the completion timestamp.
- [ ] Credits and all 32 no-lyrics classifications were human-reviewed, and search availability
      was checked in every launch region.
- [ ] Source deletion and log redaction verified after success and failure.
- [ ] Queue, worker, pipeline and deletion alerts are active.
- [ ] Backup/restore and credential rotation were tested.

### Explicitly not required

- No OpenAI/GPT API key.
- No Instagram/Meta API credential.
- No Spotify credential; listening-history personalization is deliberately excluded under
  the current Spotify Developer Policy.
- No separate onboarding, survey, recommendation-profile, or analytics API credential.
- No Supabase service-role key.
