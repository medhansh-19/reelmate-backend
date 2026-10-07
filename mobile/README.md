# ReelMate mobile

ReelMate is an Expo SDK 57 / React Native client for private video coaching and story-image song
matching. It supports iOS, Android, and web from one typed codebase and connects to the ReelMate
FastAPI API plus a dedicated Supabase Auth project.

The implemented flow is:

1. Sign in or create an account with Supabase Auth.
2. Complete a four-step music-taste onboarding for languages, moods, favorite artists/tracks,
   and the default best-overall or no-lyrics sound format.
3. Choose Video Coach with an MP4/MOV reel, or Story Song Match with a JPEG/PNG/WebP image.
   Story mode supports Best overall (`any`) and Aesthetic · no lyrics (`no_lyrics`).
4. Upload it directly to a private, short-lived R2 target returned by the backend.
5. Follow durable processing stages while the app is open or after returning later.
6. Review either timestamped reel coaching or ranked songs with visual evidence, mood matches,
   language, optional BPM, vocal/aesthetic metadata, confidence, and exact Instagram Music
   search text.
7. Reopen the same focused onboarding from Profile whenever music taste changes. Saved choices
   lightly personalize the image-first ranking.

The onboarding presents one choice group per screen, shows `1 of 4` progress, permits optional
steps to be skipped, and writes the profile once at the end. New authenticated accounts are gated
to it until the backend returns `onboarding_completed_at`; editing later preserves that completion
state. This is ReelMate's first-party replacement for Spotify listening-history import and needs
no additional external connection.

The bundled v2 catalogue has 96 metadata entries: 32 no-lyrics, 24 English, 24 Hindi, and
16 Punjabi. The recommender is `visual-song-mmr-v2`; it does not use GPT or another external
inference API.

## Run locally

Use Node 24 and pnpm 11, then from this directory:

```bash
pnpm install
cp .env.example .env
pnpm start
```

Choose iOS, Android, or web from the Expo CLI. Development automatically enters a clearly labelled
preview mode when the required public configuration is absent. To test the real integration,
populate `.env` with values from newly created ReelMate projects:

```dotenv
EXPO_PUBLIC_SUPABASE_URL=https://<NEW_REELMATE_REF>.supabase.co
EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<NEW_REELMATE_PUBLIC_KEY>
EXPO_PUBLIC_API_URL=https://<REELMATE_API_HOST>
EXPO_PUBLIC_DEMO_MODE=false
```

These values are intentionally public. Never add a database URL, Supabase service-role/secret key,
or R2 access key to an Expo environment variable or mobile build. ReelMate does not use an
OpenAI/GPT credential.
See [the external-connections runbook](../docs/EXTERNAL_CONNECTIONS.md) for the full provider setup.

Spotify listening history is not imported. The current
[Spotify Developer Policy](https://developer.spotify.com/policy) prohibits analyzing Spotify
Content or the Spotify Service to build user profiles and prohibits ingesting Spotify Content
into ML/AI systems, so no Spotify credential should be created for this feature. See
[Spotify Web API quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)
for additional constraints on any separately approved future integration.

The direct preference flow uses the existing authenticated `GET /v1/music-preferences` and
`PUT /v1/music-preferences` endpoints. Its final request includes `complete_onboarding=true`;
the database stores the server-generated completion timestamp in the dedicated ReelMate
Supabase project.

## Quality checks

```bash
pnpm typecheck
pnpm lint
pnpm format:check
npx expo export --platform web
npx expo-doctor
```

## Structure

- `src/app/` — Expo Router route tree and native tab shells
- `src/screens/` — auth, four-step onboarding, coach, upload, processing/result, library, and
  profile experiences
- `src/lib/` — validated API contract, streaming file upload, Supabase client, and preview adapter
- `src/hooks/` — React Query polling, history pagination, music preferences, retry, deletion,
  and cache ownership
- `src/providers/` — auth, network-aware query, and app-level providers
- `src/components/` and `src/theme/` — accessible ReelMate design system with adaptive light/dark UI

The iOS bundle identifier and Android package are currently `app.reelmate.coach`; confirm ownership
before store submission. The deep-link scheme is `reelmate://` and must be allowed in Supabase Auth
redirect settings.
