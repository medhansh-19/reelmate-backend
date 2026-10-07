-- ReelMate initial schema.
-- Apply this migration only to the dedicated ReelMate Supabase project.
-- No credentials, project references, or cross-project foreign data are embedded.

create extension if not exists pgcrypto with schema extensions;

create type public.analysis_status as enum (
  'awaiting_upload',
  'queued',
  'processing',
  'completed',
  'failed',
  'cancelled',
  'expired'
);

create type public.analysis_mode as enum (
  'video_coach',
  'story_song'
);

create type public.story_vocal_preference as enum (
  'any',
  'no_lyrics'
);

create type public.analysis_stage as enum (
  'awaiting_upload',
  'queued',
  'validating',
  'extracting',
  'scoring',
  'generating_feedback',
  'completed',
  'failed',
  'cancelled',
  'expired'
);

create table public.analyses (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  idempotency_key text not null,
  object_key text not null,
  mode public.analysis_mode not null default 'video_coach',
  vocal_preference public.story_vocal_preference not null default 'any',

  status public.analysis_status not null default 'awaiting_upload',
  stage public.analysis_stage not null default 'awaiting_upload',

  declared_size_bytes bigint not null,
  actual_size_bytes bigint,
  mime_type text not null,
  duration_seconds numeric(8, 3),
  content_sha256 text,

  score integer,
  hook_score integer,
  pacing_score integer,
  av_sync_score integer,
  text_score integer,
  trend_score integer,
  confidence numeric(5, 4),
  result_json jsonb,
  metrics_json jsonb,

  failure_code text,
  failure_detail text,
  failure_retryable boolean not null default false,
  retry_count integer not null default 0,
  worker_attempt_count integer not null default 0,

  schema_version text not null default '1',
  pipeline_version text,
  score_version text,
  prompt_version text,
  model_id text,
  model_input_tokens integer not null default 0,
  model_output_tokens integer not null default 0,
  estimated_model_cost_usd numeric(12, 6),
  estimated_total_cost_usd numeric(12, 6),
  source_deleted_at timestamptz,

  worker_lease_owner text,
  worker_lease_expires_at timestamptz,

  created_at timestamptz not null default now(),
  upload_expires_at timestamptz not null default (now() + interval '15 minutes'),
  queued_at timestamptz,
  started_at timestamptz,
  completed_at timestamptz,
  failed_at timestamptz,
  cancelled_at timestamptz,
  updated_at timestamptz not null default now(),

  constraint uq_analyses_user_idempotency unique (user_id, idempotency_key),
  constraint uq_analyses_object_key unique (object_key),
  constraint ck_analyses_idempotency_key
    check (char_length(idempotency_key) between 1 and 255),
  constraint ck_analyses_object_key
    check (char_length(object_key) between 1 and 1024),
  constraint ck_analyses_mime_type
    check (
      (mode = 'video_coach' and mime_type in ('video/mp4', 'video/quicktime'))
      or (mode = 'story_song' and mime_type in ('image/jpeg', 'image/png', 'image/webp'))
    ),
  constraint ck_analyses_vocal_preference
    check (mode = 'story_song' or vocal_preference = 'any'),
  constraint ck_analyses_declared_size
    check (
      declared_size_bytes > 0
      and (
        (mode = 'video_coach' and declared_size_bytes <= 100000000)
        or (mode = 'story_song' and declared_size_bytes <= 15000000)
      )
    ),
  constraint ck_analyses_actual_size
    check (
      actual_size_bytes is null
      or (
        actual_size_bytes > 0
        and (
          (mode = 'video_coach' and actual_size_bytes <= 100000000)
          or (mode = 'story_song' and actual_size_bytes <= 15000000)
        )
      )
    ),
  constraint ck_analyses_duration
    check (
      duration_seconds is null
      or (duration_seconds > 0 and duration_seconds <= 90)
    ),
  constraint ck_analyses_content_hash
    check (content_sha256 is null or content_sha256 ~ '^[0-9a-f]{64}$'),
  constraint ck_analyses_score
    check (score is null or score between 5 and 95),
  constraint ck_analyses_hook_score
    check (hook_score is null or hook_score between 0 and 100),
  constraint ck_analyses_pacing_score
    check (pacing_score is null or pacing_score between 0 and 100),
  constraint ck_analyses_av_sync_score
    check (av_sync_score is null or av_sync_score between 0 and 100),
  constraint ck_analyses_text_score
    check (text_score is null or text_score between 0 and 100),
  constraint ck_analyses_trend_score
    check (trend_score is null or trend_score between 0 and 100),
  constraint ck_analyses_confidence
    check (confidence is null or confidence between 0 and 1),
  constraint ck_analyses_retry_count check (retry_count >= 0),
  constraint ck_analyses_worker_attempt_count check (worker_attempt_count >= 0),
  constraint ck_analyses_token_usage
    check (model_input_tokens >= 0 and model_output_tokens >= 0),
  constraint ck_analyses_cost
    check (
      (estimated_model_cost_usd is null or estimated_model_cost_usd >= 0)
      and (
        estimated_total_cost_usd is null
        or (
          estimated_model_cost_usd is not null
          and estimated_total_cost_usd >= estimated_model_cost_usd
        )
      )
    ),
  constraint ck_analyses_failure_code
    check (failure_code is null or failure_code ~ '^[A-Z][A-Z0-9_]{1,63}$'),
  constraint ck_analyses_status_stage
    check (
      (status = 'awaiting_upload' and stage = 'awaiting_upload')
      or (status = 'queued' and stage = 'queued')
      or (
        status = 'processing'
        and stage in ('validating', 'extracting', 'scoring', 'generating_feedback')
      )
      or (status = 'completed' and stage = 'completed')
      or (status = 'failed' and stage = 'failed')
      or (status = 'cancelled' and stage = 'cancelled')
      or (status = 'expired' and stage = 'expired')
    ),
  constraint ck_analyses_processing_lease
    check (
      status <> 'processing'
      or (
        worker_lease_owner is not null
        and worker_lease_expires_at is not null
        and started_at is not null
      )
    ),
  constraint ck_analyses_queue_timestamp
    check (status <> 'queued' or queued_at is not null),
  constraint ck_analyses_completed_payload
    check (
      status <> 'completed'
      or (
        completed_at is not null
        and score is not null
        and result_json is not null
        and pipeline_version is not null
        and score_version is not null
        and prompt_version is not null
        and model_id is not null
      )
    ),
  constraint ck_analyses_failed_payload
    check (
      status <> 'failed'
      or (failed_at is not null and failure_code is not null)
    ),
  constraint ck_analyses_cancelled_payload
    check (
      status <> 'cancelled'
      or cancelled_at is not null
    )
);

-- This table intentionally has no foreign key to analyses/auth.users. Deleting
-- either parent must not erase the only durable R2 object key before cleanup.
create table public.source_deletion_outbox (
  id uuid primary key default gen_random_uuid(),
  analysis_id uuid,
  object_key text not null,
  reason text not null,
  attempt_count integer not null default 0,
  available_at timestamptz not null default now(),
  lease_owner text,
  lease_expires_at timestamptz,
  last_attempt_at timestamptz,
  last_error_code text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint uq_source_deletion_outbox_object_key unique (object_key),
  constraint ck_source_deletion_outbox_object_key
    check (char_length(object_key) between 1 and 1024),
  constraint ck_source_deletion_outbox_reason
    check (char_length(reason) between 1 and 64),
  constraint ck_source_deletion_outbox_attempt_count check (attempt_count >= 0),
  constraint ck_source_deletion_outbox_error_code
    check (last_error_code is null or last_error_code ~ '^[A-Z][A-Z0-9_]{1,63}$')
);

create table public.user_profiles (
  user_id uuid primary key references auth.users (id) on delete cascade,
  submission_count integer not null default 0,
  niche text,
  niche_confidence numeric(5, 4),
  editing_style text,
  editing_style_confidence numeric(5, 4),
  typical_energy text,
  typical_energy_confidence numeric(5, 4),
  recurring_issue_codes text[] not null default '{}',
  profile_version text not null default '1',
  created_at timestamptz not null default now(),
  last_updated timestamptz not null default now(),

  constraint ck_user_profiles_submission_count check (submission_count >= 0),
  constraint ck_user_profiles_niche_confidence
    check (niche_confidence is null or niche_confidence between 0 and 1),
  constraint ck_user_profiles_editing_style_confidence
    check (
      editing_style_confidence is null or editing_style_confidence between 0 and 1
    ),
  constraint ck_user_profiles_typical_energy_confidence
    check (
      typical_energy_confidence is null or typical_energy_confidence between 0 and 1
    )
);

-- Explicit preferences are entered by the ReelMate user. They are not inferred
-- from Spotify or another third-party listening service.
create table public.music_preferences (
  user_id uuid primary key references auth.users (id) on delete cascade,
  preferred_languages text[] not null default '{}',
  preferred_moods text[] not null default '{}',
  favorite_artists varchar(100)[] not null default '{}',
  favorite_tracks varchar(150)[] not null default '{}',
  default_vocal_preference public.story_vocal_preference not null default 'any',
  profile_version text not null default '1',
  revision bigint not null default 1,
  onboarding_completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint ck_music_preferences_languages_count
    check (cardinality(preferred_languages) <= 4),
  constraint ck_music_preferences_moods_count
    check (cardinality(preferred_moods) <= 8),
  constraint ck_music_preferences_artists_count
    check (cardinality(favorite_artists) <= 12),
  constraint ck_music_preferences_tracks_count
    check (cardinality(favorite_tracks) <= 12),
  constraint ck_music_preferences_revision
    check (revision >= 1),
  constraint ck_music_preferences_language_values
    check (
      preferred_languages <@ array['English', 'Hindi', 'Punjabi', 'Instrumental']::text[]
    ),
  constraint ck_music_preferences_mood_values
    check (
      preferred_moods <@ array[
        'calm', 'energetic', 'romantic', 'joyful',
        'moody', 'dreamy', 'bold', 'nostalgic'
      ]::text[]
    )
);

create index ix_analyses_user_created
  on public.analyses (user_id, created_at desc, id desc);
create index ix_analyses_user_mode_created
  on public.analyses (user_id, mode, created_at desc, id desc);
create index ix_analyses_user_status
  on public.analyses (user_id, status, created_at desc);
create index ix_analyses_claimable
  on public.analyses (queued_at, created_at)
  where status = 'queued';
create index ix_analyses_expired_leases
  on public.analyses (worker_lease_expires_at)
  where status = 'processing';
create index ix_analyses_expired_uploads
  on public.analyses (upload_expires_at)
  where status = 'awaiting_upload';
create index ix_analyses_user_hash
  on public.analyses (user_id, content_sha256)
  where content_sha256 is not null;
create unique index uq_analyses_one_active_per_user
  on public.analyses (user_id)
  where status in ('awaiting_upload', 'queued', 'processing');
create index ix_source_deletion_outbox_claimable
  on public.source_deletion_outbox (available_at, lease_expires_at);

create or replace function public.reelmate_set_updated_at()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger analyses_set_updated_at
before update on public.analyses
for each row execute function public.reelmate_set_updated_at();

create trigger music_preferences_set_updated_at
before update on public.music_preferences
for each row execute function public.reelmate_set_updated_at();

-- A direct auth.users deletion cascades into analyses without passing through
-- FastAPI. Preserve every still-private object key in the durable outbox before
-- that row disappears so account deletion cannot orphan creator media in R2.
create or replace function public.reelmate_enqueue_source_delete_on_row_delete()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if old.source_deleted_at is null then
    insert into public.source_deletion_outbox (
      analysis_id,
      object_key,
      reason,
      available_at
    )
    values (
      old.id,
      old.object_key,
      'analysis_row_deleted',
      greatest(now(), old.upload_expires_at)
    )
    on conflict (object_key) do nothing;
  end if;
  return old;
end;
$$;

create trigger analyses_enqueue_source_delete_on_row_delete
before delete on public.analyses
for each row execute function public.reelmate_enqueue_source_delete_on_row_delete();

-- Mobile clients may only read their own rows through Supabase's data API.
-- Creation and all mutations go through the FastAPI backend so users cannot
-- forge results, alter queue state, or leave R2 objects orphaned.
alter table public.analyses enable row level security;
alter table public.user_profiles enable row level security;
alter table public.music_preferences enable row level security;
alter table public.source_deletion_outbox enable row level security;

create policy analyses_select_own
on public.analyses
for select
to authenticated
using ((select auth.uid()) = user_id);

create policy user_profiles_select_own
on public.user_profiles
for select
to authenticated
using ((select auth.uid()) = user_id);

create policy music_preferences_select_own
on public.music_preferences
for select
to authenticated
using ((select auth.uid()) = user_id);

revoke all on table public.analyses from anon, authenticated;
revoke all on table public.user_profiles from anon, authenticated;
revoke all on table public.music_preferences from anon, authenticated;
revoke all on table public.source_deletion_outbox from anon, authenticated;
grant select on table public.analyses to authenticated;
grant select on table public.user_profiles to authenticated;
grant select on table public.music_preferences to authenticated;

comment on table public.analyses is
  'Private, user-owned ReelMate video coaching and story-song recommendation jobs.';
comment on column public.analyses.object_key is
  'Private R2 object key; never a public URL.';
comment on column public.analyses.metrics_json is
  'Reduced derived metrics only; raw OCR text should not be persisted.';
comment on table public.user_profiles is
  'Passive structured personalization derived from completed analyses.';
comment on table public.music_preferences is
  'First-party music taste explicitly supplied by the ReelMate user.';
comment on column public.music_preferences.onboarding_completed_at is
  'Set once when the user finishes or skips first-party music taste onboarding.';
comment on table public.source_deletion_outbox is
  'Internal durable work queue for deleting private R2 source objects.';
