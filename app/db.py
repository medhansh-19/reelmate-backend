"""Async PostgreSQL primitives and ORM models for ReelMate.

The database URL is deliberately passed to :class:`Database`; this module never
reads process environment variables.  That keeps a ReelMate deployment tied to
the Supabase project selected by the application settings instead of silently
reusing credentials from another local project.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class AnalysisStatus(StrEnum):
    """Coarse lifecycle exposed to API clients."""

    AWAITING_UPLOAD = "awaiting_upload"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class AnalysisMode(StrEnum):
    """Product workflow selected before upload."""

    VIDEO_COACH = "video_coach"
    STORY_SONG = "story_song"


class StoryVocalPreference(StrEnum):
    """Requested vocal mix for story-song recommendations."""

    ANY = "any"
    NO_LYRICS = "no_lyrics"


class AnalysisStage(StrEnum):
    """Fine-grained progress that can be safely shown in the app."""

    AWAITING_UPLOAD = "awaiting_upload"
    QUEUED = "queued"
    VALIDATING = "validating"
    EXTRACTING = "extracting"
    SCORING = "scoring"
    GENERATING_FEEDBACK = "generating_feedback"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class SourceDeletionReason(StrEnum):
    """Stable reasons for durable private-source deletion work."""

    COMPLETED = "completed"
    INVALID_MEDIA = "invalid_media"
    CANCELLED = "cancelled"
    ANALYSIS_DELETED = "analysis_deleted"
    UPLOAD_EXPIRED = "upload_expired"
    RETRY_EXPIRED = "retry_expired"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"


def _enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_type]


analysis_status_enum = PGEnum(
    AnalysisStatus,
    name="analysis_status",
    create_type=False,
    values_callable=_enum_values,
)
analysis_mode_enum = PGEnum(
    AnalysisMode,
    name="analysis_mode",
    create_type=False,
    values_callable=_enum_values,
)
story_vocal_preference_enum = PGEnum(
    StoryVocalPreference,
    name="story_vocal_preference",
    create_type=False,
    values_callable=_enum_values,
)
analysis_stage_enum = PGEnum(
    AnalysisStage,
    name="analysis_stage",
    create_type=False,
    values_callable=_enum_values,
)


class Base(DeclarativeBase):
    pass


class Analysis(Base):
    """One private upload and its versioned analysis result."""

    __tablename__ = "analyses"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_analyses_user_idempotency",
        ),
        UniqueConstraint("object_key", name="uq_analyses_object_key"),
        CheckConstraint(
            "declared_size_bytes > 0 AND "
            "((mode = 'video_coach' AND declared_size_bytes <= 100000000) OR "
            "(mode = 'story_song' AND declared_size_bytes <= 15000000))",
            name="ck_analyses_declared_size",
        ),
        CheckConstraint(
            "actual_size_bytes IS NULL OR "
            "(actual_size_bytes > 0 AND "
            "((mode = 'video_coach' AND actual_size_bytes <= 100000000) OR "
            "(mode = 'story_song' AND actual_size_bytes <= 15000000)))",
            name="ck_analyses_actual_size",
        ),
        CheckConstraint(
            "mode = 'story_song' OR vocal_preference = 'any'",
            name="ck_analyses_vocal_preference",
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR (duration_seconds > 0 AND duration_seconds <= 90)",
            name="ck_analyses_duration",
        ),
        CheckConstraint(
            "score IS NULL OR (score BETWEEN 5 AND 95)",
            name="ck_analyses_score",
        ),
        CheckConstraint("retry_count >= 0", name="ck_analyses_retry_count"),
        CheckConstraint("worker_attempt_count >= 0", name="ck_analyses_worker_attempts"),
        Index("ix_analyses_user_created", "user_id", "created_at", "id"),
        Index("ix_analyses_user_mode_created", "user_id", "mode", "created_at", "id"),
        Index("ix_analyses_user_status", "user_id", "status"),
        Index("ix_analyses_status_lease", "status", "worker_lease_expires_at"),
        Index(
            "uq_analyses_one_active_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('awaiting_upload', 'queued', 'processing')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[AnalysisMode] = mapped_column(
        analysis_mode_enum,
        nullable=False,
        default=AnalysisMode.VIDEO_COACH,
        server_default=text("'video_coach'::analysis_mode"),
    )
    vocal_preference: Mapped[StoryVocalPreference] = mapped_column(
        story_vocal_preference_enum,
        nullable=False,
        default=StoryVocalPreference.ANY,
        server_default=text("'any'::story_vocal_preference"),
    )

    status: Mapped[AnalysisStatus] = mapped_column(
        analysis_status_enum,
        nullable=False,
        default=AnalysisStatus.AWAITING_UPLOAD,
        server_default=text("'awaiting_upload'::analysis_status"),
    )
    stage: Mapped[AnalysisStage] = mapped_column(
        analysis_stage_enum,
        nullable=False,
        default=AnalysisStage.AWAITING_UPLOAD,
        server_default=text("'awaiting_upload'::analysis_stage"),
    )

    declared_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actual_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    content_sha256: Mapped[str | None] = mapped_column(String(64))

    score: Mapped[int | None] = mapped_column(Integer)
    hook_score: Mapped[int | None] = mapped_column(Integer)
    pacing_score: Mapped[int | None] = mapped_column(Integer)
    av_sync_score: Mapped[int | None] = mapped_column(Integer)
    text_score: Mapped[int | None] = mapped_column(Integer)
    trend_score: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    metrics_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    failure_code: Mapped[str | None] = mapped_column(String(64))
    failure_detail: Mapped[str | None] = mapped_column(Text)
    failure_retryable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    worker_attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    schema_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="1", server_default=text("'1'")
    )
    pipeline_version: Mapped[str | None] = mapped_column(String(64))
    score_version: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    model_id: Mapped[str | None] = mapped_column(String(128))
    model_input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    model_output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    estimated_model_cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6),
        nullable=True,
    )
    estimated_total_cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6),
        nullable=True,
    )

    source_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    worker_lease_owner: Mapped[str | None] = mapped_column(String(255))
    worker_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    upload_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now() + interval '15 minutes'"),
    )
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    @property
    def analysis_id(self) -> UUID:
        """API-friendly alias used by response models."""

        return self.id

    @property
    def result(self) -> dict[str, Any] | None:
        return self.result_json

    @property
    def retryable(self) -> bool:
        return self.failure_retryable


class SourceDeletionJob(Base):
    """Durable outbox row for deleting one private R2 source object."""

    __tablename__ = "source_deletion_outbox"
    __table_args__ = (
        UniqueConstraint("object_key", name="uq_source_deletion_outbox_object_key"),
        CheckConstraint(
            "char_length(object_key) BETWEEN 1 AND 1024",
            name="ck_source_deletion_outbox_object_key",
        ),
        CheckConstraint(
            "char_length(reason) BETWEEN 1 AND 64",
            name="ck_source_deletion_outbox_reason",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_source_deletion_outbox_attempt_count",
        ),
        CheckConstraint(
            "last_error_code IS NULL OR last_error_code ~ '^[A-Z][A-Z0-9_]{1,63}$'",
            name="ck_source_deletion_outbox_error_code",
        ),
        Index(
            "ix_source_deletion_outbox_claimable",
            "available_at",
            "lease_expires_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # This is deliberately not a foreign key: analysis/account deletion must not
    # erase the only durable copy of the object key before R2 cleanup succeeds.
    analysis_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class UserProfile(Base):
    """Passive, structured personalization derived from completed analyses."""

    __tablename__ = "user_profiles"
    __table_args__ = (
        CheckConstraint("submission_count >= 0", name="ck_user_profiles_submissions"),
        CheckConstraint(
            "niche_confidence IS NULL OR niche_confidence BETWEEN 0 AND 1",
            name="ck_user_profiles_niche_confidence",
        ),
        CheckConstraint(
            "editing_style_confidence IS NULL OR editing_style_confidence BETWEEN 0 AND 1",
            name="ck_user_profiles_style_confidence",
        ),
        CheckConstraint(
            "typical_energy_confidence IS NULL OR typical_energy_confidence BETWEEN 0 AND 1",
            name="ck_user_profiles_energy_confidence",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    submission_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    niche: Mapped[str | None] = mapped_column(String(100))
    niche_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    editing_style: Mapped[str | None] = mapped_column(String(100))
    editing_style_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    typical_energy: Mapped[str | None] = mapped_column(String(32))
    typical_energy_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    recurring_issue_codes: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)),
        nullable=False,
        default=list,
        server_default=text("'{}'::text[]"),
    )
    profile_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="1", server_default=text("'1'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class MusicPreference(Base):
    """First-party taste settings supplied directly by the ReelMate user."""

    __tablename__ = "music_preferences"
    __table_args__ = (
        CheckConstraint(
            "cardinality(preferred_languages) <= 4",
            name="ck_music_preferences_languages_count",
        ),
        CheckConstraint(
            "cardinality(preferred_moods) <= 8",
            name="ck_music_preferences_moods_count",
        ),
        CheckConstraint(
            "cardinality(favorite_artists) <= 12",
            name="ck_music_preferences_artists_count",
        ),
        CheckConstraint(
            "cardinality(favorite_tracks) <= 12",
            name="ck_music_preferences_tracks_count",
        ),
        CheckConstraint("revision >= 1", name="ck_music_preferences_revision"),
    )

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    preferred_languages: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    preferred_moods: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    favorite_artists: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    favorite_tracks: Mapped[list[str]] = mapped_column(
        ARRAY(String(150)), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    default_vocal_preference: Mapped[StoryVocalPreference] = mapped_column(
        story_vocal_preference_enum,
        nullable=False,
        default=StoryVocalPreference.ANY,
        server_default=text("'any'::story_vocal_preference"),
    )
    profile_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="1", server_default=text("'1'")
    )
    revision: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default=text("1")
    )
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


def normalize_async_database_url(database_url: str) -> str:
    """Return a SQLAlchemy asyncpg URL without discovering any credentials.

    Supabase shows standard ``postgresql://`` connection strings in its
    dashboard, while SQLAlchemy's async engine needs ``postgresql+asyncpg``.
    ``sslmode=require`` is also translated to asyncpg's ``ssl=require`` query
    parameter.
    """

    if not database_url or not database_url.strip():
        raise ValueError("A project-specific PostgreSQL database URL is required")

    url: URL = make_url(database_url.strip())
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+asyncpg")
    elif url.drivername != "postgresql+asyncpg":
        raise ValueError("DATABASE_URL must use PostgreSQL with the asyncpg driver")

    query = dict(url.query)
    if "sslmode" in query and "ssl" not in query:
        query["ssl"] = query.pop("sslmode")
        url = url.set(query=query)

    return url.render_as_string(hide_password=False)


def create_database_engine(
    database_url: str,
    *,
    echo: bool = False,
    pool_size: int = 5,
    max_overflow: int = 5,
) -> AsyncEngine:
    """Build a pooled async engine for a Supabase Postgres connection string."""

    return create_async_engine(
        normalize_async_database_url(database_url),
        echo=echo,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=pool_size,
        max_overflow=max_overflow,
    )


class Database:
    """Application-owned async engine and transaction-scoped sessions."""

    def __init__(
        self,
        database_url: str,
        *,
        echo: bool = False,
        pool_size: int = 5,
        max_overflow: int = 5,
    ) -> None:
        self.engine = create_database_engine(
            database_url,
            echo=echo,
            pool_size=pool_size,
            max_overflow=max_overflow,
        )
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            autoflush=False,
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield one transaction and commit only after successful work."""

        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    async def dispose(self) -> None:
        await self.engine.dispose()


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency using ``app.state.database`` configured at startup."""

    database = getattr(request.app.state, "database", None)
    if not isinstance(database, Database):
        raise RuntimeError("Database has not been configured on app.state.database")
    async with database.session() as session:
        yield session
