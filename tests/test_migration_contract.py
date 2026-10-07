from pathlib import Path

MIGRATION = Path("supabase/migrations/202608090001_initial_schema.sql")


def test_account_cascade_preserves_private_source_cleanup() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").casefold()

    assert "before delete on public.analyses" in sql
    assert "insert into public.source_deletion_outbox" in sql
    assert "greatest(now(), old.upload_expires_at)" in sql
    assert "on conflict (object_key) do nothing" in sql


def test_client_tables_keep_rls_and_internal_outbox_private() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").casefold()

    assert "alter table public.analyses enable row level security" in sql
    assert "alter table public.user_profiles enable row level security" in sql
    assert "alter table public.music_preferences enable row level security" in sql
    assert "revoke all on table public.source_deletion_outbox from anon, authenticated" in sql


def test_both_product_modes_have_database_constraints() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").casefold()

    assert "create type public.analysis_mode" in sql
    assert "'video_coach'" in sql
    assert "'story_song'" in sql
    assert "image/jpeg" in sql
    assert "declared_size_bytes <= 15000000" in sql
    assert "create type public.story_vocal_preference" in sql
    assert "'no_lyrics'" in sql


def test_music_preferences_are_first_party_owned_and_bounded() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").casefold()

    assert "create table public.music_preferences" in sql
    assert "references auth.users (id) on delete cascade" in sql
    assert "cardinality(favorite_artists) <= 12" in sql
    assert "revision bigint not null default 1" in sql
    assert "onboarding_completed_at timestamptz" in sql
    assert "create policy music_preferences_select_own" in sql
    assert "revoke all on table public.music_preferences from anon, authenticated" in sql
    assert "spotify_connections" not in sql
