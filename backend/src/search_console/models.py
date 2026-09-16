import enum
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .config import get_settings
from .db import Base

SCHEMA = get_settings().search_schema


def now_utc() -> datetime:
    return datetime.now(UTC)


class AccountType(str, enum.Enum):
    PREEMBEDDED = "一跳预埋户"
    EMPTY = "一跳空户"
    SECOND_HOP = "二跳账户"


class Role(str, enum.Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class OperationStatus(str, enum.Enum):
    DRAFT = "draft"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class KeywordTier(str, enum.Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = {"schema": SCHEMA}
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class AccountManager(Base):
    __tablename__ = "account_managers"
    __table_args__ = (UniqueConstraint("project_id", "login_name"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"), index=True)
    baidu_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    login_name: Mapped[str] = mapped_column(String(150))
    display_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    balance_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            f"{SCHEMA}.accounts.id",
            use_alter=True,
            name="fk_account_manager_balance_account",
        ),
        nullable=True,
    )
    rebate_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    balance_warning_threshold: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    recharge_account: Mapped[str | None] = mapped_column(String(200), nullable=True)
    financial_settings_mode: Mapped[str] = mapped_column(
        String(30), default="manager_shared", server_default="manager_shared"
    )
    auth_status: Mapped[str] = mapped_column(String(30), default="unchecked")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    project: Mapped[Project] = relationship()


class AccountDraft(Base):
    """A locally prepared account binding that is not yet a Baidu account."""

    __tablename__ = "account_drafts"
    __table_args__ = (UniqueConstraint("project_id", "login_name"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"), index=True)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.account_managers.id"), nullable=True)
    login_name: Mapped[str] = mapped_column(String(150))
    account_type: Mapped[str] = mapped_column(String(30), default="二跳账户")
    category_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    landing_url_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    manager: Mapped[AccountManager | None] = relationship(foreign_keys=[manager_id])


class AccountCategory(Base):
    __tablename__ = "account_categories"
    __table_args__ = (UniqueConstraint("project_id", "name"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"))
    name: Mapped[str] = mapped_column(String(100))
    page_type: Mapped[str] = mapped_column(String(30), default="科普")


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (Index("ix_accounts_manager_target", "manager_login_name", "baidu_account_id"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"))
    manager_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.account_managers.id"), nullable=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.account_categories.id"))
    baidu_account_id: Mapped[int] = mapped_column(unique=True)
    login_name: Mapped[str] = mapped_column(String(150))
    account_subject: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lifecycle_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    lifecycle_override: Mapped[str | None] = mapped_column(String(50), nullable=True)
    active_keyword_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lifecycle_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    eliminated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    elimination_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    elimination_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    refund_notification_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    operator_name: Mapped[str | None] = mapped_column(String(30), nullable=True)
    manager_login_name: Mapped[str] = mapped_column(String(150))
    account_type: Mapped[AccountType] = mapped_column(Enum(AccountType, name="account_type", schema=SCHEMA))
    landing_url_template: Mapped[str | None] = mapped_column(Text)
    page_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    promotion_page: Mapped[str | None] = mapped_column(String(200), nullable=True)
    rebate_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    recharge_account: Mapped[str | None] = mapped_column(String(200), nullable=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    current_budget: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    budget_type: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_snapshot_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    remote_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remote_status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    campaign_cache_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    campaign_cache_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ocpc_cache_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ocpc_cache_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    permission_status: Mapped[str] = mapped_column(String(30), default="unchecked")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    category: Mapped[AccountCategory | None] = relationship()
    manager: Mapped[AccountManager | None] = relationship(foreign_keys=[manager_id])


class CampaignCache(Base):
    """Latest known Baidu campaign state, isolated by project and target account."""

    __tablename__ = "campaign_cache"
    __table_args__ = (
        UniqueConstraint("account_id", "baidu_campaign_id"),
        Index("ix_campaign_cache_project_account_active", "project_id", "account_id", "is_active"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.accounts.id"), index=True)
    baidu_campaign_id: Mapped[int] = mapped_column(BigInteger)
    campaign_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    pause: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    schedule: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    remote_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ad_type: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class OcpcProjectCache(Base):
    """Latest verified oCPC projects for one project-owned Baidu account."""

    __tablename__ = "ocpc_project_cache"
    __table_args__ = (
        UniqueConstraint("account_id", "baidu_ocpc_project_id"),
        Index("ix_ocpc_project_cache_project_account_active", "project_id", "account_id", "is_active"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.accounts.id"), index=True)
    baidu_ocpc_project_id: Mapped[int] = mapped_column(BigInteger)
    project_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    ocpc_bid: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    bid_type: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remote_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scope: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class CampaignBatchSetting(Base):
    """Latest settings submitted by this system for one campaign scope."""

    __tablename__ = "campaign_batch_settings"
    __table_args__ = (
        UniqueConstraint("project_id", "account_type", "page_type"),
        Index("ix_campaign_batch_settings_scope", "project_id", "account_type", "page_type"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"), index=True)
    account_type: Mapped[str] = mapped_column(String(30))
    page_type: Mapped[str] = mapped_column(String(30))
    online_schedule: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    online_weekdays: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    online_start_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    online_end_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schedule_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    schedule_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    schedule_account_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schedule_plan_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schedule_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pause: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    pause_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    pause_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    pause_account_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pause_plan_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pause_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "username"),
        Index("ix_project_ad_build_access_project_operator", "project_id", "operator_name"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"), index=True)
    username: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(100))
    operator_name: Mapped[str] = mapped_column(String(30))
    supervisor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.project_members.id", ondelete="SET NULL"), nullable=True
    )
    data_scope: Mapped[str] = mapped_column(String(20), default="self", server_default="self")
    permissions: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    can_build_ads: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[str] = mapped_column(String(100), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


# Compatibility alias while existing ad-build call sites migrate to project members.
ProjectAdBuildAccess = ProjectMember


class ReferenceTemplateVersion(Base):
    __tablename__ = "reference_template_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "source_account_id", "version"),
        Index("ix_reference_template_project_active", "project_id", "is_active"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"), index=True)
    source_account_id: Mapped[int] = mapped_column(BigInteger)
    source_login_name: Mapped[str] = mapped_column(String(160))
    manager_login_name: Mapped[str] = mapped_column(String(160))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="ready")
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    hierarchy_counts: Mapped[dict] = mapped_column(JSONB, default=dict)
    template_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    analysis: Mapped[dict] = mapped_column(JSONB, default=dict)
    raw_data_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(100), default="reference-template-worker")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ProjectNegativeKeyword(Base):
    """Project-level negative keywords used by every future ad build."""

    __tablename__ = "project_negative_keywords"
    __table_args__ = (
        UniqueConstraint("project_id", "match_type", "normalized_keyword_text"),
        Index("ix_project_negative_keywords_scope", "project_id", "match_type"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"), index=True)
    match_type: Mapped[str] = mapped_column(String(20))
    keyword_text: Mapped[str] = mapped_column(String(500))
    normalized_keyword_text: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(40), default="manual")
    reference_template_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.reference_template_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Material(Base):
    __tablename__ = "materials"
    __table_args__ = (UniqueConstraint("project_id", "name"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="active")
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class MaterialVersion(Base):
    __tablename__ = "material_versions"
    __table_args__ = (UniqueConstraint("material_id", "version"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    material_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.materials.id"))
    version: Mapped[int] = mapped_column(Integer)
    file_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class MaterialKeyword(Base):
    __tablename__ = "material_keywords"
    __table_args__ = (
        UniqueConstraint("material_version_id", "row_number"),
        UniqueConstraint("project_id", "keyword_text"),
        Index("ix_material_keywords_project_id", "project_id"),
        Index("ix_material_keywords_campaign_keyword", "campaign_name", "keyword_text"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"))
    material_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.material_versions.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    campaign_name: Mapped[str] = mapped_column(String(200))
    keyword_text: Mapped[str] = mapped_column(String(500))
    keyword_utf8_encoded: Mapped[str] = mapped_column(Text)
    keyword_encoding_version: Mapped[str] = mapped_column(
        String(32),
        default="utf8-rfc3986-v1",
        server_default="utf8-rfc3986-v1",
    )
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, default=False)
    blacklist_reason: Mapped[str | None] = mapped_column(Text)
    blacklisted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blacklisted_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class CreativeSegment(Base):
    __tablename__ = "creative_segments"
    __table_args__ = (
        UniqueConstraint("project_id", "segment_type", "content"),
        Index("ix_creative_segments_project_type", "project_id", "segment_type"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"), index=True)
    segment_type: Mapped[str] = mapped_column(String(30))
    content: Mapped[str] = mapped_column(String(200))
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, default=False)
    rejection_count: Mapped[int] = mapped_column(Integer, default=0)
    blacklist_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class CreativeCombination(Base):
    __tablename__ = "creative_combinations"
    __table_args__ = (
        UniqueConstraint("project_id", "combination_hash"),
        Index("ix_creative_combinations_project_blacklist", "project_id", "is_blacklisted"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"), index=True)
    title_segment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.creative_segments.id"))
    description1_segment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.creative_segments.id"))
    description2_segment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.creative_segments.id"), nullable=True)
    combination_hash: Mapped[str] = mapped_column(String(64))
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, default=False)
    rejection_count: Mapped[int] = mapped_column(Integer, default=0)
    blacklist_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    blacklisted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class CreativeAssignment(Base):
    __tablename__ = "creative_assignments"
    __table_args__ = (
        UniqueConstraint("job_id", "account_id", "slot_number", "generation"),
        UniqueConstraint("account_id", "baidu_creative_id"),
        Index("ix_creative_assignments_review", "project_id", "status", "review_checked_at"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.ad_build_jobs.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.accounts.id"), index=True)
    combination_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.creative_combinations.id"), index=True)
    slot_number: Mapped[int] = mapped_column(Integer)
    generation: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(40), default="planned")
    baidu_creative_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    main_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    detail_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_recorded: Mapped[bool] = mapped_column(Boolean, default=False)
    creative_payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    review_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class KeywordTierTemplate(Base):
    __tablename__ = "keyword_tier_templates"
    __table_args__ = (UniqueConstraint("project_id", "name"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"))
    name: Mapped[str] = mapped_column(String(100), default="默认关键词分级")
    a_unit_count: Mapped[int] = mapped_column(Integer, default=5)
    allocation_mode: Mapped[str] = mapped_column(String(30), default="stable_random")
    abc_target_percent: Mapped[int] = mapped_column(Integer, default=60)
    unit_capacity: Mapped[int] = mapped_column(Integer, default=5000)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class KeywordDeploymentPlan(Base):
    __tablename__ = "keyword_deployment_plans"
    __table_args__ = {"schema": SCHEMA}
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"))
    campaign_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="preview")
    input_summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    allocation_plan: Mapped[dict] = mapped_column(JSONB)
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class AdBuildJob(Base):
    __tablename__ = "ad_build_jobs"
    __table_args__ = (Index("ix_ad_build_jobs_project_created", "project_id", "created_at"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"), index=True)
    selection_mode: Mapped[str] = mapped_column(String(40))
    execution_mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(40), default="planned")
    first_scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    batch_size: Mapped[int] = mapped_column(Integer)
    batch_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    account_count: Mapped[int] = mapped_column(Integer)
    batch_count: Mapped[int] = mapped_column(Integer)
    selection_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    preflight_result: Mapped[dict] = mapped_column(JSONB, default=dict)
    workflow_version: Mapped[str] = mapped_column(String(40), default="weight-loss-account-flow-v1")
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class AdBuildBatch(Base):
    __tablename__ = "ad_build_batches"
    __table_args__ = (
        UniqueConstraint("job_id", "batch_number"),
        Index("ix_ad_build_batches_due", "status", "scheduled_at"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.ad_build_jobs.id", ondelete="CASCADE"), index=True)
    batch_number: Mapped[int] = mapped_column(Integer)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), default="scheduled")
    account_ids: Mapped[list] = mapped_column(JSONB, default=list)
    operation_ids: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PerformanceDaily(Base):
    __tablename__ = "performance_daily"
    __table_args__ = (UniqueConstraint("report_date", "account_id"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_date: Mapped[date] = mapped_column(Date)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.accounts.id"))
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    spend: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    uv: Mapped[int] = mapped_column(Integer, default=0)
    copies: Mapped[int] = mapped_column(Integer, default=0)
    adds: Mapped[int] = mapped_column(Integer, default=0)
    arrivals: Mapped[int] = mapped_column(Integer, default=0)
    source_watermark: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class FinancePaymentRecord(Base):
    """Audited Baidu payment/pending-fund row for a manager's recharge account."""

    __tablename__ = "finance_payment_records"
    __table_args__ = (
        UniqueConstraint("project_id", "manager_id", "fund_type", "remote_record_id"),
        Index("ix_finance_payment_project_date", "project_id", "pay_date"),
        Index("ix_finance_payment_manager_date", "manager_id", "pay_date"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"), index=True)
    manager_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.account_managers.id"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.accounts.id"), index=True)
    fund_type: Mapped[int] = mapped_column(Integer)
    remote_record_id: Mapped[int] = mapped_column(BigInteger)
    pay_date: Mapped[date] = mapped_column(Date)
    pay_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actual_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    movement_type: Mapped[str] = mapped_column(String(20))
    account_currency: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0)
    cash_amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0)
    bonus_amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0)
    pay_method_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    pending_type_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payment_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payment_status_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    order_row: Mapped[str | None] = mapped_column(String(200), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    source_watermark: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reconciled_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class FinanceProfitInput(Base):
    """Manual reported spend for one project/date and selected operator scope."""

    __tablename__ = "finance_profit_inputs"
    __table_args__ = (
        UniqueConstraint("project_id", "report_date", "operator_scope"),
        Index("ix_finance_profit_project_date", "project_id", "report_date"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"), index=True)
    report_date: Mapped[date] = mapped_column(Date)
    operator_scope: Mapped[str] = mapped_column(String(500), default="__all__")
    reported_spend: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0)
    updated_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class KeywordPerformanceDaily(Base):
    __tablename__ = "keyword_performance_daily"
    __table_args__ = (
        UniqueConstraint("report_date", "account_id", "campaign_name", "keyword_text"),
        Index("ix_keyword_performance_lookup", "campaign_name", "keyword_text", "report_date"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_date: Mapped[date] = mapped_column(Date)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.accounts.id"))
    campaign_name: Mapped[str] = mapped_column(String(200))
    keyword_text: Mapped[str] = mapped_column(String(500))
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    spend: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    uv: Mapped[int] = mapped_column(Integer, default=0)
    copies: Mapped[int] = mapped_column(Integer, default=0)
    adds: Mapped[int] = mapped_column(Integer, default=0)
    source_watermark: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class MaterialKeywordPerformanceYearly(Base):
    __tablename__ = "material_keyword_performance_yearly"
    __table_args__ = (
        UniqueConstraint("project_id", "material_keyword_id", "report_year"),
        Index(
            "ix_material_keyword_performance_yearly_project_year",
            "project_id",
            "report_year",
        ),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.projects.id"), index=True
    )
    material_keyword_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.material_keywords.id", ondelete="CASCADE"), index=True
    )
    report_year: Mapped[int] = mapped_column(Integer)
    impressions: Mapped[int] = mapped_column(BigInteger, default=0)
    clicks: Mapped[int] = mapped_column(BigInteger, default=0)
    spend: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    uv: Mapped[int] = mapped_column(BigInteger, default=0)
    copies: Mapped[int] = mapped_column(BigInteger, default=0)
    adds: Mapped[int] = mapped_column(BigInteger, default=0)
    source_sha256: Mapped[str] = mapped_column(String(64))
    source_rows: Mapped[int] = mapped_column(Integer, default=1)
    imported_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )


class UnmatchedKeywordPerformanceDaily(Base):
    __tablename__ = "unmatched_keyword_performance_daily"
    __table_args__ = (
        UniqueConstraint("report_date", "account_id", "campaign_name", "keyword_text"),
        Index(
            "ix_unmatched_keyword_performance_lookup",
            "account_id",
            "report_date",
            "keyword_text",
        ),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    report_date: Mapped[date] = mapped_column(Date)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.accounts.id")
    )
    campaign_name: Mapped[str] = mapped_column(String(200))
    keyword_text: Mapped[str] = mapped_column(String(500))
    raw_keyword_text: Mapped[str] = mapped_column(String(520))
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    spend: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    reason: Mapped[str] = mapped_column(
        String(60), default="not_in_material_center"
    )
    source_watermark: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc
    )


class HduofenEvent(Base):
    __tablename__ = "hduofen_events"
    __table_args__ = (
        UniqueConstraint("project_id", "source_type", "source_event_id"),
        Index("ix_hduofen_events_project_date_account", "project_id", "event_date", "account_id"),
        Index("ix_hduofen_events_project_keyword", "project_id", "tracking_keyword"),
        Index("ix_hduofen_events_material_keyword_id", "material_keyword_id"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"))
    capture_task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.background_tasks.id", ondelete="SET NULL"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(30))
    source_event_id: Mapped[str] = mapped_column(String(120))
    metric_key: Mapped[str] = mapped_column(String(120))
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_date: Mapped[date] = mapped_column(Date)
    baidu_account_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.accounts.id"), nullable=True
    )
    tracking_keyword: Mapped[str | None] = mapped_column(String(500), nullable=True)
    material_keyword_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.material_keywords.id"), nullable=True
    )
    url_keyword: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metric_included: Mapped[bool] = mapped_column(Boolean, default=False)
    exclusion_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    raw_data_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class HduofenAccountMapping(Base):
    __tablename__ = "hduofen_account_mappings"
    __table_args__ = (
        UniqueConstraint("project_id", "custom_id"),
        Index("ix_hduofen_account_mappings_account", "project_id", "account_id"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"))
    custom_id: Mapped[str] = mapped_column(String(120))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.accounts.id"))
    source_file: Mapped[str] = mapped_column(Text)
    source_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )

    account: Mapped[Account] = relationship()


class HduofenAccountRemarkMapping(Base):
    __tablename__ = "hduofen_account_remark_mappings"
    __table_args__ = (
        UniqueConstraint("project_id", "normalized_remark"),
        Index("ix_hduofen_account_remark_mappings_account", "project_id", "account_id"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"))
    remark: Mapped[str] = mapped_column(String(240))
    normalized_remark: Mapped[str] = mapped_column(String(240))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.accounts.id"))
    source_file: Mapped[str] = mapped_column(Text)
    source_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )

    account: Mapped[Account] = relationship()


class Operation(Base):
    __tablename__ = "operations"
    __table_args__ = (UniqueConstraint("idempotency_key"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operation_type: Mapped[str] = mapped_column(String(60))
    target_account_id: Mapped[int] = mapped_column()
    idempotency_key: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict] = mapped_column(JSONB)
    preflight_result: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[OperationStatus] = mapped_column(Enum(OperationStatus, name="operation_status", schema=SCHEMA), default=OperationStatus.AWAITING_CONFIRMATION)
    requested_by: Mapped[str] = mapped_column(String(100))
    confirmed_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BackgroundTask(Base):
    __tablename__ = "background_tasks"
    __table_args__ = (Index("ix_tasks_status_heartbeat", "status", "heartbeat_at"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.projects.id"), nullable=True, index=True
    )
    operation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.operations.id"))
    strategy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.strategy_versions.id"), nullable=True, index=True
    )
    task_type: Mapped[str] = mapped_column(String(60))
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus, name="task_status", schema=SCHEMA), default=TaskStatus.PENDING)
    current_node: Mapped[str] = mapped_column(String(100), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("dedupe_key"),
        Index("ix_notifications_project_created", "project_id", "created_at"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.projects.id"), index=True
    )
    category: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(20), default="info")
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(240))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class NotificationRead(Base):
    __tablename__ = "notification_reads"
    __table_args__ = (
        UniqueConstraint("notification_id", "username"),
        Index("ix_notification_reads_user", "username", "read_at"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    notification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.notifications.id", ondelete="CASCADE"), index=True
    )
    username: Mapped[str] = mapped_column(String(100))
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class NotificationCursor(Base):
    __tablename__ = "notification_cursors"
    __table_args__ = (UniqueConstraint("project_id"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.projects.id"), index=True
    )
    task_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = {"schema": SCHEMA}
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.accounts.id"))
    alert_type: Mapped[str] = mapped_column(String(60))
    severity: Mapped[str] = mapped_column(String(20), default="warning")
    title: Mapped[str] = mapped_column(String(200))
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="open")
    resolved_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class SyncWatermark(Base):
    __tablename__ = "sync_watermarks"
    __table_args__ = (UniqueConstraint("source", "scope"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(40))
    scope: Mapped[str] = mapped_column(String(100))
    source_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snapshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="unknown")
    message: Mapped[str | None] = mapped_column(Text)


class DailyDataStatus(Base):
    __tablename__ = "daily_data_status"
    __table_args__ = (
        UniqueConstraint("project_id", "report_date"),
        Index("ix_daily_data_status_project_date", "project_id", "report_date"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"))
    report_date: Mapped[date] = mapped_column(Date)
    baidu_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hduofen_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    keyword_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    final_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )


class ProjectPreference(Base):
    __tablename__ = "project_preferences"
    __table_args__ = (UniqueConstraint("project_id", "key"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"), index=True)
    key: Mapped[str] = mapped_column(String(80))
    value: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_by: Mapped[str] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class StrategyPolicy(Base):
    __tablename__ = "strategy_policies"
    __table_args__ = (
        UniqueConstraint("project_id", "strategy_key", name="uq_strategy_policy_project_key"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"), index=True)
    strategy_key: Mapped[str] = mapped_column(String(50))
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class StrategyVersion(Base):
    __tablename__ = "strategy_versions"
    __table_args__ = (
        UniqueConstraint("policy_id", "version_number", name="uq_strategy_version_number"),
        Index("ix_strategy_version_policy_status", "policy_id", "status"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    policy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.strategy_policies.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    base_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    draft_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    config_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(100))
    published_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StrategyEvaluation(Base):
    __tablename__ = "strategy_evaluations"
    __table_args__ = (Index("ix_strategy_evaluation_policy_created", "policy_id", "created_at"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    policy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.strategy_policies.id"), index=True)
    version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.strategy_versions.id"), nullable=True)
    config_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    evaluated_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class StrategyScheduleRun(Base):
    __tablename__ = "strategy_schedule_runs"
    __table_args__ = (
        UniqueConstraint("project_id", "strategy_key", "scheduled_for", name="uq_strategy_schedule_slot"),
        Index("ix_strategy_schedule_status", "status", "scheduled_for"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"), index=True)
    strategy_key: Mapped[str] = mapped_column(String(50))
    strategy_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.strategy_versions.id"))
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.background_tasks.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_project_created", "project_id", "created_at"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.projects.id"), index=True)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(80))
    target_type: Mapped[str] = mapped_column(String(60))
    target_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    summary: Mapped[str] = mapped_column(String(300))
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
