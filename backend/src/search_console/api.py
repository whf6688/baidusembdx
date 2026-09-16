import asyncio
import csv
import hashlib
import io
import json
import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import String, and_, cast, desc, func, literal, or_, select, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from .config import get_settings
from .code_sync import (
    active_code_sync_task,
    code_sync_status,
    create_code_sync_task,
)
from .account_lifecycle import (
    EMPTY,
    TESTING,
    elimination_reason,
)
from .account_judgment import (
    ACCOUNT_JUDGMENT_PREFERENCE_KEY,
    ACCOUNT_STATUS_ALL_PAUSED,
    ACCOUNT_STATUS_BUDGET_LOW,
    ACCOUNT_STATUS_ONLINE,
    IN_USE_ACCOUNT_STATUSES,
    account_status_expression,
    cost_judgment_expressions,
    default_account_judgment_preference,
    judgment_facts,
    load_account_statuses,
    load_account_judgment_preference,
    normalize_account_judgment_preference,
)
from .account_settings_import import (
    MAX_FILE_BYTES,
    attachment_header,
    build_account_settings_template,
    parse_account_settings_workbook,
)
from .account_workspace import _comparison_trends, account_ocpc_project_cache_data, account_workspace_data, account_workspace_facets
from .account_management import account_management_data, account_selection_ids
from .ad_builds import (
    WORKFLOW_VERSION,
    account_workflow_overrides,
    account_workflow_steps,
    build_ad_build_preview,
    build_ocpc_project_name,
    build_plan_pause_schedule,
    build_plan_pause_schedule_from_windows,
)
from .ad_build_settings import (
    AD_BUILD_PLAN_REPEATS_DRAFT_KEY,
    AD_BUILD_PLAN_REPEATS_KEY,
    default_plan_repeat_count,
    load_plan_repeat_counts,
    load_plan_repeat_counts_for_key,
)
from .ad_build_rules import AD_BUILD_RULE_VERSION, ad_build_rule_summary, current_ad_build_rules
from .regions import (
    AD_BUILD_REGION_PREFERENCE_KEY,
    REGION_CATALOG_VERSION,
    baidu_region_catalog,
    baidu_region_ids,
    default_ad_build_region_preference,
)
from .creatives import (
    CREATIVE_COUNT_PER_ACCOUNT,
    CREATIVE_SEGMENT_REJECTION_THRESHOLD,
    SECOND_HOP_REJECTION_THRESHOLD,
    creative_pool_summary,
    select_random_creative_combinations,
)
from .budgets import (
    budget_snapshot_coverage,
    is_budget_append_candidate,
    needs_budget_reset,
    snapshot_is_fresh,
)
from .creative_persistence import ensure_creative_center_combination
from .db import get_db
from .imports import filter_new_material_rows, parse_material_workbook, preview_workbook
from .keyword_encoding import KEYWORD_ENCODING_VERSION, encode_keyword_utf8
from .keyword_tiers import TIER_RANK, classify_keyword
from .keyword_planner import KeywordPlanConfig, KeywordPlanError, TieredKeyword, build_keyword_plan
from .manager_balance import resolve_manager_recharge_account
from .metrics import calculate_cash_spend, calculate_report_metrics, safe_divide
from .report_export import build_daily_report_xlsx
from .notifications import (
    BalanceGroupHealth,
    balance_group_key,
    create_refund_notifications,
    load_balance_group_health,
)
from .models import (
    Account,
    AccountDraft,
    AccountManager,
    AccountType,
    AdBuildBatch,
    AdBuildJob,
    ProjectAdBuildAccess,
    Alert,
    AuditEvent,
    BackgroundTask,
    CampaignCache,
    CampaignBatchSetting,
    OcpcProjectCache,
    CreativeAssignment,
    CreativeCombination,
    CreativeSegment,
    HduofenEvent,
    HduofenAccountMapping,
    KeywordDeploymentPlan,
    KeywordPerformanceDaily,
    Material,
    MaterialKeyword,
    MaterialKeywordPerformanceYearly,
    MaterialVersion,
    Notification,
    NotificationRead,
    Operation,
    OperationStatus,
    PerformanceDaily,
    Project,
    ProjectPreference,
    ProjectNegativeKeyword,
    ReferenceTemplateVersion,
    Role,
    StrategyEvaluation,
    StrategyPolicy,
    StrategyVersion,
    SyncWatermark,
    TaskStatus,
)
from .schemas import (
    AccountDraftCreate,
    AccountBatchSettings,
    AccountUpdate,
    AdBuildCreateRequest,
    AdBuildAccessUpdate,
    AdBuildPreviewRequest,
    AdBuildPlanSettingsUpdate,
    CreativeAssignmentBind,
    CreativeBlacklistUpdate,
    CreativeCombinationPreviewRequest,
    CreativeSegmentBulkCreate,
    CampaignBatchUpdateRequest,
    CampaignSettingsScopeRequest,
    Envelope,
    HduofenCaptureRequest,
    HduofenCustomIdCreate,
    HduofenCustomIdBatchCreate,
    KeywordPlanRequest,
    KeywordBlacklistUpdate,
    KeywordTierDryRunRequest,
    KeywordTierRuleConfig,
    FinanceProfitUpdate,
    FinanceReconciliationUpdate,
    ManagerCreate,
    ManagerSettingsUpdate,
    ManualKeywordBlacklistCreate,
    NegativeKeywordBulkCreate,
    NegativeKeywordTemplateCopy,
    OperationCreate,
    PreferenceUpdate,
    ProjectCreate,
    ProjectMemberCreate,
    ProjectMemberUpdate,
    ProjectUpdate,
    StrategyDraftUpdate,
    StrategyPublishRequest,
    StrategyRestoreDraftRequest,
    SystemOwnerCredentialUpdate,
    WebLoginRequest,
)
from .negative_keywords import (
    normalized_negative_keyword,
    reference_template_negative_keyword_fingerprint,
    reference_template_negative_keywords,
    project_negative_keyword_snapshot,
    sync_reference_template_negative_keywords,
)
from .security import (
    SESSION_COOKIE_NAME,
    Actor,
    create_access_token,
    current_actor,
    owner_usernames,
    require_roles,
    system_owner_username,
)
from .web_auth import (
    clear_login_failures,
    login_is_rate_limited,
    record_login_failure,
    update_system_owner_credential,
    update_web_credential,
    verify_web_credentials,
)
from .permissions import (
    DEFAULT_MEMBER_PERMISSIONS,
    MODULES,
    access_payload,
    ad_build_operator_names,
    get_project_member,
    is_system_owner,
    normalize_permissions,
    project_access,
    require_account_scope,
    require_project_permission,
)
from .finance_reports import (
    profit_report,
    recharge_reconciliation_report,
    save_profit_inputs,
    set_reconciliation_status,
)
from .services import confirm_operation, dashboard_summary, preflight_operation
from .strategies import (
    DEFAULT_STRATEGY_CONFIGS,
    StrategyConfigError,
    active_strategy_version,
    config_hash,
    ensure_strategy_policies,
    normalize_budget_append_round_amounts,
    save_draft,
    serialize_version,
    strategy_payload,
    validate_strategy_config,
)

router = APIRouter(prefix="/api/v1")
settings = get_settings()
PROJECT_MATERIAL_LIBRARY_NAME = "项目公共物料库"
KEYWORD_TIER_PREFERENCE_KEY = "keyword_tiers"


def envelope(request: Request, data=None, **kwargs) -> Envelope:
    return Envelope(request_id=request.state.request_id, data=data, data_at=datetime.now(UTC), **kwargs)


@router.post("/auth/login")
def web_login(payload: WebLoginRequest, request: Request, response: Response):
    if not settings.web_login_enabled:
        raise HTTPException(status_code=404, detail="网页登录未启用")
    client_ip = request.client.host if request.client else "unknown"
    if login_is_rate_limited(settings, client_ip, payload.username):
        raise HTTPException(
            status_code=429,
            detail={
                "code": "LOGIN_RATE_LIMITED",
                "message": "登录尝试次数过多，请稍后再试",
            },
        )
    if not verify_web_credentials(settings, payload.username, payload.password):
        record_login_failure(settings, client_ip, payload.username)
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_CREDENTIALS", "message": "账号或密码不正确"},
        )
    clear_login_failures(settings, client_ip, payload.username)
    role = Role.ADMIN if payload.username in owner_usernames() else Role.OPERATOR
    max_age = settings.auth_session_hours * 60 * 60
    token = create_access_token(payload.username, role, settings.app_secret, max_age)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=settings.app_env != "local",
        samesite="strict",
        path="/",
    )
    return envelope(request, {"username": payload.username})


@router.post("/auth/logout")
def web_logout(request: Request, response: Response):
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=settings.app_env != "local",
        samesite="strict",
        path="/",
    )
    return envelope(request, {"logged_out": True})


@router.get("/health")
def health(request: Request):
    return envelope(request, {
        "service": "search-console",
        "writes_enabled": settings.baidu_writes_enabled,
        "account_auto_elimination_enabled": settings.account_auto_elimination_enabled,
        "creative_auto_rebuild_enabled": settings.creative_auto_rebuild_enabled,
        "app_code": settings.baidu_app_code,
        "baidu_app_configured": bool(settings.baidu_app_id and settings.baidu_app_secret),
        "authorization_center": "project_postgresql",
    })


@router.get("/session")
def session(
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    owner = is_system_owner(actor)
    allowed_roles = [Role.ADMIN.value] if owner else [Role.OPERATOR.value]
    member = None if owner else db.scalar(select(ProjectAdBuildAccess).where(
        ProjectAdBuildAccess.username == actor.username,
        ProjectAdBuildAccess.is_active.is_(True),
    ).limit(1))
    display_name = "系统管理员" if owner else (member.display_name if member else actor.username)
    return envelope(request, {
        "username": actor.username,
        "display_name": display_name,
        "role": Role.ADMIN.value if owner else Role.OPERATOR.value,
        "is_system_owner": owner,
        "allowed_roles": allowed_roles,
        "environment": settings.app_env,
        "auth_mode": "web" if settings.web_login_enabled else (
            "proxy" if settings.trust_proxy_auth else "local"
        ),
    })


RUNTIME_JOB_DEFINITIONS = (
    ("initial_budget_reset", "初始预算复位", ("budget_reset_automation",)),
    (
        "realtime_closure",
        "实时闭环",
        (
            "baidu_account_hourly_refresh",
            "hduofen_capture",
            "baidu_budget_snapshot",
            "creative_review_sync",
        ),
    ),
    ("account_balance_status", "账户余额/状态", ("baidu_budget_snapshot",)),
    (
        "historical_spend_backfill",
        "历史消耗补齐",
        ("baidu_account_backfill", "baidu_account_final_archive"),
    ),
)


def _runtime_job_view(task: BackgroundTask | None, *, key: str, label: str, can_refresh: bool) -> dict:
    if task is None:
        return {
            "key": key,
            "label": label,
            "status": "waiting",
            "status_text": "暂无记录",
            "detail": "等待后台首次调度",
            "updated_at": None,
            "can_refresh": can_refresh,
        }
    status_value = task.status.value
    if status_value in {"pending", "running"}:
        status, status_text = "running", "运行中"
    elif status_value == "succeeded":
        status, status_text = "normal", "正常"
    elif status_value in {"failed", "blocked"}:
        status, status_text = "error", "异常"
    else:
        status, status_text = "warning", "待观察"
    observed_at = task.updated_at or task.heartbeat_at or task.created_at
    local_time = observed_at.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%m-%d %H:%M:%S")
    detail = task.last_error if status == "error" and task.last_error else local_time
    return {
        "key": key,
        "label": label,
        "status": status,
        "status_text": status_text,
        "detail": detail,
        "updated_at": observed_at,
        "can_refresh": can_refresh,
    }


@router.get("/runtime-jobs")
def runtime_jobs(request: Request, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    project_query = select(Project.id).where(Project.enabled.is_(True))
    if not is_system_owner(actor):
        project_query = project_query.join(
            ProjectAdBuildAccess,
            and_(
                ProjectAdBuildAccess.project_id == Project.id,
                ProjectAdBuildAccess.username == actor.username,
                ProjectAdBuildAccess.is_active.is_(True),
            ),
        )
    project_ids = list(db.scalars(project_query).all())
    can_refresh = is_system_owner(actor)
    jobs = []
    for key, label, task_types in RUNTIME_JOB_DEFINITIONS:
        latest = None
        if project_ids:
            latest = db.scalar(
                select(BackgroundTask)
                .where(
                    BackgroundTask.project_id.in_(project_ids),
                    BackgroundTask.task_type.in_(task_types),
                )
                .order_by(desc(BackgroundTask.updated_at), desc(BackgroundTask.created_at))
                .limit(1)
            )
        jobs.append(_runtime_job_view(latest, key=key, label=label, can_refresh=can_refresh))
    statuses = {job["status"] for job in jobs}
    overall_status = (
        "error" if "error" in statuses
        else "running" if "running" in statuses
        else "waiting" if "waiting" in statuses
        else "warning" if "warning" in statuses
        else "normal"
    )
    return envelope(request, {"overall_status": overall_status, "jobs": jobs})


@router.post("/runtime-jobs/{job_key}/refresh", status_code=202)
def refresh_runtime_job(
    job_key: str,
    request: Request,
    actor: Actor = Depends(require_roles(Role.ADMIN)),
):
    if not is_system_owner(actor):
        raise HTTPException(status_code=403, detail="只有系统管理员可以刷新后台常驻任务")
    valid_keys = {definition[0] for definition in RUNTIME_JOB_DEFINITIONS}
    if job_key not in valid_keys:
        raise HTTPException(status_code=404, detail="后台常驻任务不存在")
    from .worker import (
        queue_due_budget_snapshot_syncs,
        queue_final_daily_archive,
        queue_hourly_data_refresh,
    )
    if job_key == "initial_budget_reset":
        queued = queue_due_budget_snapshot_syncs.delay("midnight_reset")
    elif job_key == "realtime_closure":
        queued = queue_hourly_data_refresh.delay()
    elif job_key == "account_balance_status":
        queued = queue_due_budget_snapshot_syncs.delay("manual_home_refresh")
    else:
        queued = queue_final_daily_archive.delay()
    return envelope(request, {"status": "queued", "job_key": job_key, "dispatch_id": str(queued.id)})


@router.get("/system/code-sync/status")
def get_code_sync_status(
    request: Request,
    db: Session = Depends(get_db),
    _: Actor = Depends(current_actor),
):
    return envelope(request, code_sync_status(db, settings))


@router.post("/system/code-sync/run", status_code=202)
def run_code_sync_now(
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN)),
):
    if not is_system_owner(actor):
        raise HTTPException(status_code=403, detail="只有系统管理员可以执行代码同步")
    if not settings.code_sync_enabled:
        raise HTTPException(status_code=409, detail="代码同步功能未启用")
    active = active_code_sync_task(db)
    if active is None:
        active = create_code_sync_task(db, requested_by=actor.username, trigger="manual")
        from .worker import run_code_sync

        run_code_sync.delay(str(active.id))
    return envelope(request, code_sync_status(db, settings))


@router.get("/projects")
def list_projects(request: Request, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    query = select(Project).order_by(Project.created_at)
    if not is_system_owner(actor):
        query = query.join(
            ProjectAdBuildAccess,
            and_(
                ProjectAdBuildAccess.project_id == Project.id,
                ProjectAdBuildAccess.username == actor.username,
                ProjectAdBuildAccess.is_active.is_(True),
            ),
        )
    rows = db.scalars(query).all()
    return envelope(request, [serialize_project(db, row, actor) for row in rows])


def serialize_project(db: Session, row: Project, actor: Actor | None = None) -> dict:
    allowed_operator_names = None
    if actor is not None:
        allowed_operator_names = project_access(db, row.id, actor).operator_names
    scope_filters = (
        [Account.operator_name.in_(allowed_operator_names)]
        if allowed_operator_names is not None
        else []
    )
    return {
        "id": str(row.id), "code": row.code, "name": row.name, "enabled": row.enabled,
        "manager_count": db.scalar(select(func.count()).select_from(AccountManager).where(
            AccountManager.project_id == row.id,
            AccountManager.is_active.is_(True),
            AccountManager.auth_status != "archived",
            *( [AccountManager.id.in_(select(Account.manager_id).where(
                Account.project_id == row.id,
                *scope_filters,
            ))] if allowed_operator_names is not None else [] ),
        )) or 0,
        "account_count": db.scalar(select(func.count()).select_from(Account).where(
            Account.project_id == row.id,
            *scope_filters,
            Account.is_active.is_(True),
            or_(
                Account.manager_id.is_(None),
                Account.manager.has(AccountManager.is_active.is_(True)),
            ),
        )) or 0,
    }


@router.post("/projects", status_code=201)
def create_project(
    payload: ProjectCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN)),
):
    if not is_system_owner(actor):
        raise HTTPException(status_code=403, detail="只有系统管理员可以创建项目")
    project = Project(code=payload.code, name=payload.name, enabled=True)
    db.add(project)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="项目编码已存在") from exc
    db.refresh(project)
    return envelope(request, serialize_project(db, project, actor))


@router.patch("/projects/{project_id}")
def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    project = require_project(db, project_id)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("enabled") is False and project.enabled:
        enabled_count = db.scalar(select(func.count()).select_from(Project).where(Project.enabled.is_(True))) or 0
        if enabled_count <= 1:
            raise HTTPException(status_code=400, detail="至少保留一个启用项目")
    for field, value in changes.items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return envelope(request, serialize_project(db, project, actor))


def require_project(db: Session, project_id: uuid.UUID) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def add_audit(
    db: Session,
    project_id: uuid.UUID,
    actor: Actor,
    action: str,
    target_type: str,
    summary: str,
    target_id: str | None = None,
    details: dict | None = None,
) -> None:
    db.add(AuditEvent(
        project_id=project_id,
        actor=actor.username,
        action=action,
        target_type=target_type,
        target_id=target_id,
        summary=summary,
        details=details or {},
    ))


def serialize_account(
    row: Account,
    lifetime_spend: Decimal | None = None,
    balance_health: BalanceGroupHealth | None = None,
    account_status: str | None = None,
) -> dict:
    effective_lifecycle = row.lifecycle_override or row.lifecycle_stage
    return {
        "id": str(row.id), "project_id": str(row.project_id),
        "manager_id": str(row.manager_id) if row.manager_id else None,
        "baidu_account_id": row.baidu_account_id, "login_name": row.login_name,
        "account_subject": row.account_subject, "lifecycle_stage": effective_lifecycle,
        "account_status": account_status,
        "automatic_lifecycle_stage": row.lifecycle_stage,
        "lifecycle_override": row.lifecycle_override,
        "lifecycle_source": "manual" if row.lifecycle_override is not None else "automatic",
        "active_keyword_count": row.active_keyword_count,
        "lifetime_spend": str(lifetime_spend) if lifetime_spend is not None else None,
        "lifecycle_evaluated_at": row.lifecycle_evaluated_at,
        "eliminated_at": row.eliminated_at,
        "elimination_reason": row.elimination_reason,
        "operator_name": row.operator_name,
        "manager_login_name": row.manager.login_name if row.manager else row.manager_login_name,
        "account_type": row.account_type.value,
        "landing_url_template": row.landing_url_template,
        "page_type": row.page_type,
        "promotion_page": row.promotion_page,
        "rebate_rate": str(row.rebate_rate) if row.rebate_rate is not None else None,
        "recharge_account": row.recharge_account,
        "balance": str(row.balance), "balance_snapshot_at": row.budget_snapshot_at,
        "balance_alert": bool(balance_health and balance_health.needs_recharge),
        "cash_group_balance": (
            str(balance_health.total_balance.quantize(Decimal("0.01")))
            if balance_health else None
        ),
        "average_daily_spend_7d": (
            str(balance_health.average_daily_spend.quantize(Decimal("0.01")))
            if balance_health else None
        ),
        "balance_days_remaining": (
            str(balance_health.balance_days.quantize(Decimal("0.01")))
            if balance_health and balance_health.balance_days is not None
            else None
        ),
        "balance_group_account_count": balance_health.account_count if balance_health else None,
        "balance_group_fresh": bool(balance_health and balance_health.is_fresh),
        "balance_metric_date_from": balance_health.metric_start if balance_health else None,
        "balance_metric_date_to": balance_health.metric_end if balance_health else None,
        "permission_status": row.permission_status,
        "is_active": row.is_active, "last_synced_at": row.last_synced_at,
    }


def refresh_project_account_lifecycles(
    db: Session,
    project_id: uuid.UUID,
    *,
    commit: bool = True,
) -> list[tuple[Account, Decimal]]:
    """Return account rows without recalculating event-driven lifecycle state."""
    spend_totals = (
        select(
            PerformanceDaily.account_id.label("account_id"),
            func.coalesce(func.sum(PerformanceDaily.spend), 0).label("lifetime_spend"),
        )
        .group_by(PerformanceDaily.account_id)
        .subquery()
    )
    rows = db.execute(
        select(
            Account,
            func.coalesce(spend_totals.c.lifetime_spend, 0),
        )
        .outerjoin(spend_totals, spend_totals.c.account_id == Account.id)
        .where(Account.project_id == project_id)
        .order_by(Account.login_name)
    ).all()
    # `commit` remains in the signature for compatibility with existing
    # callers.  Listing accounts, syncing keywords and importing settings are
    # intentionally read-only with respect to automatic lifecycle state.
    _ = commit
    return [(account, Decimal(lifetime_spend)) for account, lifetime_spend in rows]


@router.get("/dashboard/summary")
def get_summary(request: Request, db: Session = Depends(get_db), _: Actor = Depends(current_actor)):
    summary = dashboard_summary(db)
    return envelope(request, summary.model_dump(), snapshot_watermark=summary.data_freshness.get("baidu"))


@router.get("/projects/{project_id}/dashboard/summary")
def get_project_summary(project_id: uuid.UUID, request: Request, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    require_project(db, project_id)
    access = project_access(db, project_id, actor)
    summary = dashboard_summary(db, project_id, allowed_operator_names=access.operator_names)
    return envelope(request, summary.model_dump(), snapshot_watermark=summary.data_freshness.get("baidu"))


@router.get("/projects/{project_id}/managers")
def list_project_managers(project_id: uuid.UUID, request: Request, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    require_project(db, project_id)
    access = project_access(db, project_id, actor)
    scope_filters = (
        [Account.operator_name.in_(access.operator_names)]
        if access.operator_names is not None
        else []
    )
    rows = db.scalars(select(AccountManager).where(
        AccountManager.project_id == project_id,
        AccountManager.auth_status != "archived",
        *( [AccountManager.id.in_(select(Account.manager_id).where(
            Account.project_id == project_id,
            *scope_filters,
        ))] if access.operator_names is not None else [] ),
    ).order_by(AccountManager.login_name)).all()
    result = []
    for row in rows:
        account_count = db.scalar(select(func.count()).select_from(Account).where(
            Account.manager_id == row.id,
            *scope_filters,
        )) or 0
        representative = resolve_manager_recharge_account(db, row)
        balance = (
            Decimal(representative.balance)
            if representative is not None and representative.budget_snapshot_at is not None
            else None
        )
        balance_warning_active = bool(
            row.is_active
            and row.balance_warning_threshold is not None
            and balance is not None
            and balance < row.balance_warning_threshold
        )
        result.append({
            "id": str(row.id), "project_id": str(row.project_id), "baidu_user_id": row.baidu_user_id,
            "login_name": row.login_name, "display_name": row.display_name,
            "auth_status": row.auth_status, "is_active": row.is_active,
            "last_synced_at": row.last_synced_at,
            "account_count": account_count,
            "balance": str(balance) if balance is not None else None,
            "balance_account_name": representative.login_name if representative is not None else None,
            "balance_snapshot_at": representative.budget_snapshot_at if representative is not None else None,
            "rebate_rate": str(row.rebate_rate) if row.rebate_rate is not None else None,
            "balance_warning_threshold": (
                str(row.balance_warning_threshold)
                if row.balance_warning_threshold is not None else None
            ),
            "balance_warning_active": balance_warning_active,
            "recharge_account": row.recharge_account,
        })
    return envelope(request, result)


def apply_manager_financial_settings(
    db: Session,
    *,
    manager_id: uuid.UUID,
    rebate_rate: Decimal | None = None,
    recharge_account: str | None = None,
) -> int:
    """Keep manager-owned financial settings identical on every child account."""

    manager = db.get(AccountManager, manager_id)
    if manager is None:
        return 0
    if manager.financial_settings_mode == "legacy_per_account":
        return 0
    if rebate_rate is not None:
        manager.rebate_rate = rebate_rate
    if recharge_account is not None:
        manager.recharge_account = recharge_account
    accounts = db.scalars(select(Account).where(Account.manager_id == manager_id)).all()
    for account in accounts:
        if rebate_rate is not None:
            account.rebate_rate = rebate_rate
        if recharge_account is not None:
            account.recharge_account = recharge_account
    if recharge_account is not None:
        resolve_manager_recharge_account(db, manager, update_binding=True)
    return len(accounts)


@router.patch("/projects/{project_id}/managers/{manager_id}/settings")
def update_project_manager_settings(
    project_id: uuid.UUID,
    manager_id: uuid.UUID,
    payload: ManagerSettingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    manager = db.scalar(
        select(AccountManager)
        .where(AccountManager.id == manager_id)
        .with_for_update()
    )
    if not manager or manager.project_id != project_id or manager.auth_status == "archived":
        raise HTTPException(status_code=404, detail="项目或账户管家不存在")

    changes = payload.model_dump(exclude_unset=True)
    old_values = {
        key: str(getattr(manager, key)) if getattr(manager, key) is not None else None
        for key in changes
    }
    affected_accounts = 0
    if "rebate_rate" in changes:
        manager.rebate_rate = changes["rebate_rate"]
        accounts = db.scalars(select(Account).where(Account.manager_id == manager.id)).all()
        for account in accounts:
            account.rebate_rate = changes["rebate_rate"]
        affected_accounts = len(accounts)
    if "balance_warning_threshold" in changes:
        manager.balance_warning_threshold = changes["balance_warning_threshold"]

    new_values = {
        key: str(value) if value is not None else None
        for key, value in changes.items()
    }
    add_audit(
        db,
        project_id,
        actor,
        "manager.settings.update",
        "account_manager",
        "修改账户管家设置",
        target_id=str(manager.id),
        details={
            "old_values": old_values,
            "new_values": new_values,
            "affected_accounts": affected_accounts,
        },
    )
    db.commit()
    return envelope(request, {
        "manager_id": str(manager.id),
        "rebate_rate": str(manager.rebate_rate) if manager.rebate_rate is not None else None,
        "balance_warning_threshold": (
            str(manager.balance_warning_threshold)
            if manager.balance_warning_threshold is not None else None
        ),
        "affected_accounts": affected_accounts,
    })


@router.post("/projects/{project_id}/managers", status_code=201)
def create_project_manager(
    project_id: uuid.UUID,
    payload: ManagerCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    row = AccountManager(
        project_id=project_id,
        login_name=payload.login_name,
        display_name=payload.display_name,
        rebate_rate=payload.rebate_rate,
        recharge_account=payload.recharge_account,
        auth_status="pending_oauth",
    )
    db.add(row)
    add_audit(db, project_id, actor, "manager.prepare", "account_manager", "准备账户管家接入", details={"login_name": payload.login_name})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="该项目已存在同名账户管家") from exc
    db.refresh(row)
    return envelope(request, {
        "id": str(row.id), "project_id": str(row.project_id), "baidu_user_id": None,
        "login_name": row.login_name, "display_name": row.display_name,
        "rebate_rate": str(row.rebate_rate) if row.rebate_rate is not None else None,
        "balance_warning_threshold": None,
        "balance_warning_active": False,
        "recharge_account": row.recharge_account,
        "auth_status": row.auth_status, "is_active": row.is_active,
        "last_synced_at": None, "account_count": 0,
    })


def serialize_account_draft(row: AccountDraft) -> dict:
    return {
        "id": str(row.id), "project_id": str(row.project_id),
        "manager_id": str(row.manager_id) if row.manager_id else None,
        "manager_login_name": row.manager.login_name if row.manager else None,
        "login_name": row.login_name, "account_type": row.account_type,
        "landing_url_template": row.landing_url_template,
        "status": row.status, "created_at": row.created_at,
    }


@router.get("/projects/{project_id}/account-drafts")
def list_account_drafts(project_id: uuid.UUID, request: Request, db: Session = Depends(get_db), _: Actor = Depends(current_actor)):
    require_project(db, project_id)
    rows = db.scalars(select(AccountDraft).where(AccountDraft.project_id == project_id).order_by(desc(AccountDraft.created_at))).all()
    return envelope(request, [serialize_account_draft(row) for row in rows])


@router.post("/projects/{project_id}/account-drafts", status_code=201)
def create_account_draft(
    project_id: uuid.UUID,
    payload: AccountDraftCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    if payload.manager_id:
        manager = db.get(AccountManager, payload.manager_id)
        if not manager or manager.project_id != project_id:
            raise HTTPException(status_code=400, detail="账户管家不属于当前项目")
    row = AccountDraft(project_id=project_id, created_by=actor.username, **payload.model_dump())
    db.add(row)
    add_audit(db, project_id, actor, "account.prepare", "account_draft", "创建账户接入草稿", details={"login_name": payload.login_name})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="该项目已存在同名账户草稿") from exc
    db.refresh(row)
    return envelope(request, serialize_account_draft(row))


@router.get("/projects/{project_id}/accounts")
def list_project_accounts(project_id: uuid.UUID, request: Request, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    require_project(db, project_id)
    access = project_access(db, project_id, actor)
    rows = refresh_project_account_lifecycles(db, project_id)
    account_statuses = load_account_statuses(db, project_id)
    group_health = load_balance_group_health(
        db,
        project_id,
        fresh_since=datetime.now(UTC) - timedelta(hours=3),
    )
    serialized_rows = []
    for row, lifetime_spend in rows:
        if access.operator_names is not None and row.operator_name not in access.operator_names:
            continue
        effective_lifecycle = row.lifecycle_override or row.lifecycle_stage
        health = None
        if (
            row.is_active
            and row.eliminated_at is None
            and effective_lifecycle in {EMPTY, TESTING}
        ):
            key = balance_group_key(row)
            health = group_health.get(key) if key else None
        serialized_rows.append(
            serialize_account(
                row,
                lifetime_spend,
                health,
                account_statuses.get(row.baidu_account_id),
            )
        )
    return envelope(request, serialized_rows)


@router.get("/projects/{project_id}/account-workspace")
def get_account_workspace(
    project_id: uuid.UUID,
    request: Request,
    date_from: date | None = None,
    date_to: date | None = None,
    lifecycle: str | None = Query(default=None, max_length=50),
    lifecycles: str | None = Query(default=None, max_length=500),
    account_status: str | None = Query(default=None, max_length=30),
    account_statuses: str | None = Query(default=None, max_length=500),
    cost_status: str | None = Query(default=None, max_length=30),
    cost_statuses: str | None = Query(default=None, max_length=500),
    manager_id: uuid.UUID | None = None,
    manager_ids: str | None = Query(default=None, max_length=4000),
    subject: str | None = Query(default=None, max_length=200),
    operator_name: str | None = Query(default=None, max_length=30),
    operator_names: str | None = Query(default=None, max_length=1000),
    account_type: str | None = Query(default=None, max_length=30),
    account_types: str | None = Query(default=None, max_length=500),
    page_type: str | None = Query(default=None, max_length=30),
    page_types: str | None = Query(default=None, max_length=500),
    remote_status: str | None = Query(default=None, pattern="^(missing|1|2|3|4|6|7|11)$"),
    remote_statuses: str | None = Query(default=None, max_length=100),
    account_names: str | None = Query(default=None, max_length=10000),
    search: str | None = Query(default=None, max_length=100),
    sort_by: str = Query(default="default", pattern="^(default|status|account_status|account_id|account_name|subject|lifecycle|cost_status|operator|manager|account_type|page_type|impressions|clicks|spend|adds|copies|cpm|ctr|add_cost|copy_cost|cash_add_cost|cash_copy_cost|budget|balance|updated_at)$"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=20, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    access = require_project_permission(db, project_id, actor, "account_list", "view")
    selected_to = date_to or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    selected_from = date_from or selected_to
    if selected_from > selected_to or (selected_to - selected_from).days > 366:
        raise HTTPException(status_code=422, detail="账户工作台日期范围无效或超过 366 天")
    return envelope(request, account_workspace_data(
        db, project_id, date_from=selected_from, date_to=selected_to,
        lifecycle=lifecycle, lifecycles=lifecycles, account_status=account_status, account_statuses=account_statuses,
        cost_status=cost_status, cost_statuses=cost_statuses, manager_id=manager_id, manager_ids=manager_ids, subject=subject,
        operator_name=operator_name, operator_names=operator_names, account_type=account_type, account_types=account_types,
        page_type=page_type, page_types=page_types, remote_status=remote_status, remote_statuses=remote_statuses, account_names=account_names,
        search=search, sort_by=sort_by, sort_order=sort_order, page=page, page_size=page_size,
        allowed_operator_names=access.operator_names,
    ))


def serialize_project_member(
    row: ProjectAdBuildAccess,
    supervisor_names: dict[uuid.UUID, str] | None = None,
) -> dict:
    permissions = normalize_permissions(row.permissions)
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "username": row.username,
        "display_name": row.display_name,
        "operator_name": row.operator_name,
        "supervisor_id": str(row.supervisor_id) if row.supervisor_id else None,
        "supervisor_name": (supervisor_names or {}).get(row.supervisor_id) if row.supervisor_id else None,
        "data_scope": row.data_scope,
        "permissions": permissions,
        "permission_count": sum(level != "hidden" for level in permissions.values()),
        "can_build_ads": permissions["auto_launch"] == "manage",
        "is_active": row.is_active,
        "is_system_owner": False,
        "version": row.version,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/projects/{project_id}/access/me")
def get_my_project_access(
    project_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    return envelope(request, access_payload(project_access(db, project_id, actor)))


@router.get("/projects/{project_id}/members")
def list_project_members(
    project_id: uuid.UUID,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=100),
    status: str = Query(default="all", pattern="^(all|enabled|disabled)$"),
    data_scope: str | None = Query(default=None, pattern="^(self|team|project)$"),
    supervisor_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    require_project_permission(db, project_id, actor, "member_management", "view")
    members = list(db.scalars(select(ProjectAdBuildAccess).where(
        ProjectAdBuildAccess.project_id == project_id,
    ).order_by(ProjectAdBuildAccess.created_at, ProjectAdBuildAccess.display_name)).all())
    supervisor_names = {row.id: row.display_name for row in members}
    normalized_search = (search or "").strip().casefold()
    filtered = [
        row for row in members
        if (not normalized_search or any(
            normalized_search in str(value or "").casefold()
            for value in (row.display_name, row.username, row.operator_name)
        ))
        and (status == "all" or row.is_active == (status == "enabled"))
        and (not data_scope or row.data_scope == data_scope)
        and (not supervisor_id or row.supervisor_id == supervisor_id)
    ]
    owner_row = {
        "id": "system-owner",
        "project_id": str(project_id),
        "username": system_owner_username(),
        "display_name": "系统管理员",
        "operator_name": None,
        "supervisor_id": None,
        "supervisor_name": None,
        "data_scope": "project",
        "permissions": {key: "manage" for key in MODULES},
        "permission_count": len(MODULES),
        "can_build_ads": True,
        "is_active": True,
        "is_system_owner": True,
        "version": 1,
        "updated_by": "system",
        "updated_at": None,
    }
    include_owner = status != "disabled" and (not data_scope or data_scope == "project")
    if normalized_search and not any(
        normalized_search in value.casefold()
        for value in (owner_row["display_name"], owner_row["username"])
    ):
        include_owner = False
    rows = ([owner_row] if include_owner else []) + [
        serialize_project_member(row, supervisor_names) for row in filtered
    ]
    total = len(rows)
    start = (page - 1) * page_size
    supervisors = [
        {"id": str(row.id), "name": row.display_name}
        for row in members if row.is_active and row.data_scope in {"team", "project"}
    ]
    return envelope(request, {
        "rows": rows[start:start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
        "supervisors": supervisors,
        "summary": {
            "total": len(members) + 1,
            "enabled": sum(row.is_active for row in members) + 1,
            "supervisors": sum(row.is_active and row.data_scope in {"team", "project"} for row in members),
            "disabled": sum(not row.is_active for row in members),
        },
    })


def validate_member_hierarchy(
    db: Session,
    project_id: uuid.UUID,
    member_id: uuid.UUID | None,
    supervisor_id: uuid.UUID | None,
    data_scope: str,
) -> ProjectAdBuildAccess | None:
    if data_scope in {"team", "project"} and supervisor_id:
        raise HTTPException(status_code=422, detail="主管或项目负责人不能再设置直属主管")
    if not supervisor_id:
        return None
    if member_id and supervisor_id == member_id:
        raise HTTPException(status_code=422, detail="成员不能成为自己的主管")
    supervisor = db.get(ProjectAdBuildAccess, supervisor_id)
    if not supervisor or supervisor.project_id != project_id or not supervisor.is_active:
        raise HTTPException(status_code=422, detail="直属主管不存在或已停用")
    if supervisor.supervisor_id or supervisor.data_scope not in {"team", "project"}:
        raise HTTPException(status_code=422, detail="直属主管必须是当前项目的一层主管")
    return supervisor


@router.post("/projects/{project_id}/members", status_code=201)
def create_project_member(
    project_id: uuid.UUID,
    payload: ProjectMemberCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    require_project_permission(db, project_id, actor, "member_management", "manage")
    if payload.username == system_owner_username():
        raise HTTPException(status_code=409, detail="该登录账号属于固定系统管理员")
    if get_project_member(db, project_id, payload.username, active_only=False):
        raise HTTPException(status_code=409, detail="该登录账号已加入当前项目")
    validate_member_hierarchy(db, project_id, None, payload.supervisor_id, payload.data_scope)
    permissions = normalize_permissions(payload.permissions or DEFAULT_MEMBER_PERMISSIONS)
    row = ProjectAdBuildAccess(
        project_id=project_id,
        username=payload.username,
        display_name=payload.display_name,
        operator_name=payload.operator_name,
        supervisor_id=payload.supervisor_id,
        data_scope=payload.data_scope,
        permissions=permissions,
        can_build_ads=permissions["auto_launch"] == "manage",
        is_active=True,
        updated_by=actor.username,
    )
    db.add(row)
    db.flush()
    try:
        update_web_credential(
            settings.auth_htpasswd_path,
            old_username=None,
            new_username=payload.username,
            password=payload.password,
        )
    except OSError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="登录凭据暂时无法保存") from exc
    add_audit(db, project_id, actor, "member.create", "project_member", f"新增成员{row.display_name}", str(row.id), serialize_project_member(row))
    db.commit()
    db.refresh(row)
    return envelope(request, serialize_project_member(row))


@router.patch("/projects/{project_id}/members/system-owner/credentials")
def update_system_owner_credentials(
    project_id: uuid.UUID,
    payload: SystemOwnerCredentialUpdate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    old_username = system_owner_username()
    if not is_system_owner(actor) or actor.username != old_username:
        raise HTTPException(status_code=403, detail="只有当前系统管理员可以修改自己的登录账号")
    if payload.username != old_username and db.scalar(select(ProjectAdBuildAccess.id).where(
        ProjectAdBuildAccess.username == payload.username,
    ).limit(1)):
        raise HTTPException(status_code=409, detail="该登录账号已被项目成员使用")
    try:
        update_system_owner_credential(
            settings,
            old_username=old_username,
            new_username=payload.username,
            password=payload.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="该登录账号已存在") from exc
    except KeyError as exc:
        raise HTTPException(status_code=409, detail="系统管理员原登录凭据不存在") from exc
    except OSError as exc:
        raise HTTPException(status_code=503, detail="系统管理员登录凭据暂时无法保存") from exc
    add_audit(
        db,
        project_id,
        actor,
        "member.owner_credentials.update",
        "system_owner",
        "更新系统管理员登录凭据",
        "system-owner",
        {
            "credentials_changed": {
                "username": old_username != payload.username,
                "password": bool(payload.password),
            },
        },
    )
    db.commit()
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=settings.app_env != "local",
        samesite="strict",
        path="/",
    )
    return envelope(request, {
        "username": payload.username,
        "display_name": "系统管理员",
        "requires_relogin": True,
    })


@router.patch("/projects/{project_id}/members/{member_id}")
def update_project_member(
    project_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: ProjectMemberUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    require_project_permission(db, project_id, actor, "member_management", "manage")
    row = db.get(ProjectAdBuildAccess, member_id)
    if not row or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="成员不存在")
    if row.version != payload.version:
        raise HTTPException(status_code=409, detail="成员权限已被其他人修改，请刷新后重试")
    if payload.username == system_owner_username():
        raise HTTPException(status_code=409, detail="该登录账号属于固定系统管理员")
    existing_username = get_project_member(db, project_id, payload.username, active_only=False)
    if existing_username and existing_username.id != row.id:
        raise HTTPException(status_code=409, detail="该登录账号已加入当前项目")
    validate_member_hierarchy(db, project_id, row.id, payload.supervisor_id, payload.data_scope)
    if not payload.is_active and db.scalar(select(func.count(ProjectAdBuildAccess.id)).where(
        ProjectAdBuildAccess.project_id == project_id,
        ProjectAdBuildAccess.supervisor_id == row.id,
        ProjectAdBuildAccess.is_active.is_(True),
    )):
        raise HTTPException(status_code=409, detail="请先调整该主管的直属成员再停用")
    before = serialize_project_member(row)
    old_username = row.username
    permissions = normalize_permissions(payload.permissions)
    row.username = payload.username
    row.display_name = payload.display_name
    row.operator_name = payload.operator_name
    row.supervisor_id = payload.supervisor_id
    row.data_scope = payload.data_scope
    row.permissions = permissions
    row.can_build_ads = permissions["auto_launch"] == "manage"
    row.is_active = payload.is_active
    row.version += 1
    row.updated_by = actor.username
    after = serialize_project_member(row)
    try:
        if old_username != payload.username or payload.password:
            update_web_credential(
                settings.auth_htpasswd_path,
                old_username=old_username,
                new_username=payload.username,
                password=payload.password,
            )
    except KeyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="原登录凭据不存在，请在修改登录账号时同时设置新密码",
        ) from exc
    except OSError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="登录凭据暂时无法保存") from exc
    add_audit(
        db,
        project_id,
        actor,
        "member.update",
        "project_member",
        f"更新成员{row.display_name}资料",
        str(row.id),
        {
            "before": before,
            "after": after,
            "credentials_changed": {
                "username": old_username != payload.username,
                "password": bool(payload.password),
            },
        },
    )
    db.commit()
    db.refresh(row)
    return envelope(request, serialize_project_member(row))


@router.get("/projects/{project_id}/account-management")
def get_account_management(
    project_id: uuid.UUID,
    request: Request,
    manager_id: uuid.UUID | None = None,
    operator_name: str | None = Query(default=None, max_length=30),
    account_type: str | None = Query(default=None, max_length=30),
    page_type: str | None = Query(default=None, max_length=30),
    remote_status: str | None = Query(default=None, pattern="^(missing|1|2|3|4|6|7|11)$"),
    authorization_status: str | None = Query(default=None, max_length=30),
    search: str | None = Query(default=None, max_length=100),
    sort_by: str = Query(default="account_id", pattern="^(account_id|account_name|operator_name|account_type|page_type|remote_status|authorization)$"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=20, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    access = require_project_permission(db, project_id, actor, "account_management", "view")
    return envelope(request, account_management_data(
        db, project_id, manager_id=manager_id, operator_name=operator_name,
        account_type=account_type, page_type=page_type, remote_status=remote_status,
        authorization_status=authorization_status, search=search, sort_by=sort_by,
        sort_order=sort_order, page=page, page_size=page_size,
        allowed_operator_names=access.operator_names,
    ))


@router.get("/projects/{project_id}/account-selection")
def get_account_selection(
    project_id: uuid.UUID,
    request: Request,
    manager_id: uuid.UUID | None = None,
    lifecycle: str | None = Query(default=None, max_length=50),
    lifecycles: str | None = Query(default=None, max_length=500),
    account_status: str | None = Query(default=None, max_length=30),
    account_statuses: str | None = Query(default=None, max_length=500),
    cost_status: str | None = Query(default=None, max_length=30),
    cost_statuses: str | None = Query(default=None, max_length=500),
    manager_ids: str | None = Query(default=None, max_length=4000),
    operator_name: str | None = Query(default=None, max_length=30),
    operator_names: str | None = Query(default=None, max_length=1000),
    account_type: str | None = Query(default=None, max_length=30),
    account_types: str | None = Query(default=None, max_length=500),
    page_type: str | None = Query(default=None, max_length=30),
    page_types: str | None = Query(default=None, max_length=500),
    remote_status: str | None = Query(default=None, pattern="^(missing|1|2|3|4|6|7|11)$"),
    remote_statuses: str | None = Query(default=None, max_length=100),
    account_names: str | None = Query(default=None, max_length=10000),
    authorization_status: str | None = Query(default=None, max_length=30),
    search: str | None = Query(default=None, max_length=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    access = require_project_permission(db, project_id, actor, "account_list", "view")
    ids = account_selection_ids(
        db, project_id, manager_id=manager_id, manager_ids=manager_ids, lifecycle=lifecycle, lifecycles=lifecycles,
        account_status=account_status, account_statuses=account_statuses, cost_status=cost_status, cost_statuses=cost_statuses,
        operator_name=operator_name, operator_names=operator_names, account_type=account_type, account_types=account_types,
        page_type=page_type, page_types=page_types, remote_status=remote_status, remote_statuses=remote_statuses,
        account_names=account_names, authorization_status=authorization_status, search=search,
        allowed_operator_names=access.operator_names,
    )
    return envelope(request, {"account_ids": ids, "total": len(ids)})


@router.get("/projects/{project_id}/account-workspace/facets")
def get_account_workspace_facets(
    project_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    access = require_project_permission(db, project_id, actor, "account_list", "view")
    return envelope(request, account_workspace_facets(
        db, project_id, allowed_operator_names=access.operator_names,
    ))


@router.get("/projects/{project_id}/accounts/{account_id}/workspace")
def get_account_workspace_detail(
    project_id: uuid.UUID,
    account_id: uuid.UUID,
    request: Request,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    access = require_project_permission(db, project_id, actor, "account_list", "view")
    account = db.scalar(select(Account).where(Account.id == account_id, Account.project_id == project_id))
    if account is None:
        raise HTTPException(status_code=404, detail="账户不存在")
    require_account_scope(access, account)
    selected_to = date_to or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    selected_from = date_from or selected_to
    workspace = account_workspace_data(
        db, project_id, date_from=selected_from, date_to=selected_to,
        account_uuid=account.id, page=1, page_size=20,
        allowed_operator_names=access.operator_names,
    )
    row = next((item for item in workspace["rows"] if item["id"] == str(account.id)), None)
    return envelope(request, {"account": row, "date_from": selected_from, "date_to": selected_to})


@router.get("/projects/{project_id}/accounts/{account_id}/ocpc-projects")
def get_account_cached_ocpc_projects(
    project_id: uuid.UUID,
    account_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    access = require_project_permission(db, project_id, actor, "account_list", "view")
    account = db.scalar(select(Account).where(Account.id == account_id, Account.project_id == project_id))
    if account is None:
        raise HTTPException(status_code=404, detail="账户不存在或已归档")
    require_account_scope(access, account)
    result = account_ocpc_project_cache_data(db, project_id, account_id)
    if result is None:
        raise HTTPException(status_code=404, detail="账户不存在或已归档")
    return envelope(request, result)


@router.post("/projects/{project_id}/accounts/{account_id}/retirement")
def create_account_retirement_operation(
    project_id: uuid.UUID,
    account_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    """Prepare—not execute—the irreversible account retirement task from verified caches."""
    require_project(db, project_id)
    access = require_project_permission(db, project_id, actor, "account_list", "manage")
    account = db.scalar(select(Account).where(
        Account.id == account_id,
        Account.project_id == project_id,
        Account.is_active.is_(True),
    ))
    if account is None:
        raise HTTPException(status_code=404, detail="账户不存在或已归档")
    require_account_scope(access, account)
    if load_account_statuses(db, project_id).get(account.baidu_account_id) == "已淘汰":
        raise HTTPException(status_code=409, detail="该账户状态已是“已淘汰”")
    if account.campaign_cache_status != "succeeded" or account.ocpc_cache_status != "succeeded":
        raise HTTPException(status_code=409, detail="请先同步计划缓存；该同步会同时核对 oCPC 项目与计划")
    campaign_ids = db.scalars(select(CampaignCache.baidu_campaign_id).where(
        CampaignCache.project_id == project_id,
        CampaignCache.account_id == account.id,
        CampaignCache.is_active.is_(True),
    )).all()
    ocpc_project_ids = db.scalars(select(OcpcProjectCache.baidu_ocpc_project_id).where(
        OcpcProjectCache.project_id == project_id,
        OcpcProjectCache.account_id == account.id,
        OcpcProjectCache.is_active.is_(True),
    )).all()
    if not campaign_ids and not ocpc_project_ids:
        raise HTTPException(status_code=409, detail="缓存中没有可淘汰的 oCPC 项目或计划；请先同步后再确认")
    inventory = f"{account.id}:{','.join(map(str, sorted(campaign_ids)))}:{','.join(map(str, sorted(ocpc_project_ids)))}"
    operation = preflight_operation(db, OperationCreate(
        operation_type="account_retirement",
        target_account_id=account.baidu_account_id,
        idempotency_key=f"retire:{hashlib.sha256(inventory.encode('utf-8')).hexdigest()[:48]}",
        payload={
            "target_login_name": account.login_name,
            "manager_login_name": account.manager_login_name or "",
            "campaign_ids": sorted(campaign_ids),
            "ocpc_project_ids": sorted(ocpc_project_ids),
            "audience_ids": [],
            "retirement_only": True,
        },
    ), actor.username)
    add_audit(
        db, project_id, actor, "account.retirement.preflight", "account",
        "生成账户淘汰预检", str(account.id),
        {"operation_id": str(operation.id), "campaign_count": len(campaign_ids), "ocpc_project_count": len(ocpc_project_ids)},
    )
    db.commit()
    return envelope(request, {
        "operation_id": str(operation.id),
        "status": operation.status.value,
        "account_name": account.login_name,
        "campaign_count": len(campaign_ids),
        "ocpc_project_count": len(ocpc_project_ids),
    })


@router.patch("/projects/{project_id}/accounts/{account_id}")
def update_project_account(
    project_id: uuid.UUID,
    account_id: uuid.UUID,
    payload: AccountUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    access = require_project_permission(db, project_id, actor, "account_list", "manage")
    account = db.scalar(select(Account).where(
        Account.id == account_id,
        Account.project_id == project_id,
    ))
    if not account:
        raise HTTPException(status_code=404, detail="当前项目中不存在该账户")
    require_account_scope(access, account)
    account.landing_url_template = payload.landing_url_template
    add_audit(
        db, project_id, actor, "account.url.update", "account", "更新账户落地页 URL",
        str(account.id), {"baidu_account_id": account.baidu_account_id},
    )
    db.commit()
    db.refresh(account)
    return envelope(request, serialize_account(account))


@router.get("/projects/{project_id}/accounts/batch-settings/template")
def download_account_batch_settings_template(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    project = require_project(db, project_id)
    content = build_account_settings_template(())
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": attachment_header(f"{project.name}_账户批量设置模板.xlsx")},
    )


async def _read_account_settings_upload(file: UploadFile) -> tuple[str, bytes]:
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="请上传 xlsx 或 xlsm 文件")
    content = await file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(status_code=400, detail="工作簿不能超过 20 MB")
    if not content:
        raise HTTPException(status_code=400, detail="上传的工作簿为空")
    return file.filename, content


@router.post("/projects/{project_id}/accounts/batch-settings/import/preview")
async def preview_account_batch_settings_import(
    project_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    access = project_access(db, project_id, actor)
    file_name, content = await _read_account_settings_upload(file)
    account_filters = [Account.project_id == project_id]
    if access.operator_names is not None:
        account_filters.append(Account.operator_name.in_(access.operator_names))
    accounts = db.scalars(select(Account).where(*account_filters)).all()
    plan = parse_account_settings_workbook(content, file_name, accounts)
    return envelope(request, plan.public())


@router.post("/projects/{project_id}/accounts/batch-settings/import")
async def import_account_batch_settings(
    project_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    access = project_access(db, project_id, actor)
    file_name, content = await _read_account_settings_upload(file)
    account_filters = [Account.project_id == project_id]
    if access.operator_names is not None:
        account_filters.append(Account.operator_name.in_(access.operator_names))
    accounts = db.scalars(select(Account).where(*account_filters)).all()
    plan = parse_account_settings_workbook(content, file_name, accounts)
    if plan.invalid_count:
        first_error = plan.errors[0]
        raise HTTPException(
            status_code=422,
            detail=f"第 {first_error['row']} 行：{first_error['message']}；请修正后重新预检",
        )
    if not plan.changed_count:
        raise HTTPException(status_code=422, detail="工作簿没有需要更新的内容")

    account_map = {account.id: account for account in accounts}
    lifecycle_changed = False
    manager_financial_changes: dict[uuid.UUID, dict[str, object]] = {}
    for imported_row in plan.rows:
        account = account_map[imported_row.account_id]
        if (
            account.manager_id is None
            or account.manager.financial_settings_mode == "legacy_per_account"
        ):
            continue
        requested = manager_financial_changes.setdefault(account.manager_id, {})
        for field_name in ("rebate_rate", "recharge_account"):
            if field_name not in imported_row.changes:
                continue
            incoming = imported_row.changes[field_name]
            if field_name in requested and requested[field_name] != incoming:
                raise HTTPException(
                    status_code=422,
                    detail=f"同一账户管家在工作簿中设置了不同的{'返点' if field_name == 'rebate_rate' else '充值账户'}",
                )
            requested[field_name] = incoming

    for imported_row in plan.rows:
        account = account_map[imported_row.account_id]
        changes = imported_row.changes
        if "account_type" in changes:
            account.account_type = changes["account_type"]
        if "operator_name" in changes:
            account.operator_name = changes["operator_name"]
        if "page_type" in changes:
            account.page_type = changes["page_type"]
        if "promotion_page" in changes:
            account.promotion_page = changes["promotion_page"]
        if "promotion_link" in changes:
            account.landing_url_template = changes["promotion_link"]
        legacy_financials = (
            account.manager_id is None
            or account.manager.financial_settings_mode == "legacy_per_account"
        )
        if legacy_financials and "rebate_rate" in changes:
            account.rebate_rate = changes["rebate_rate"]
        if legacy_financials and "recharge_account" in changes:
            account.recharge_account = changes["recharge_account"]
        if "lifecycle_stage" in changes:
            lifecycle_stage = changes["lifecycle_stage"]
            account.lifecycle_override = None if lifecycle_stage == "自动判断" else lifecycle_stage
            lifecycle_changed = True

    propagated_account_count = 0
    for manager_id, changes in manager_financial_changes.items():
        propagated_account_count += apply_manager_financial_settings(
            db,
            manager_id=manager_id,
            rebate_rate=changes.get("rebate_rate"),
            recharge_account=changes.get("recharge_account"),
        )

    if lifecycle_changed:
        create_refund_notifications(db, project_id)
    result = {
        **plan.public(),
        "updated_count": plan.changed_count,
        "propagated_account_count": propagated_account_count,
    }
    add_audit(
        db,
        project_id,
        actor,
        "account.batch_settings.import",
        "account",
        "通过工作簿批量设置账户业务信息",
        details={
            "file_name": file_name,
            "sha256": plan.sha256,
            "row_count": plan.row_count,
            "updated_count": plan.changed_count,
            "fields": sorted(plan.changed_fields),
        },
    )
    db.commit()
    return envelope(request, result)


@router.post("/projects/{project_id}/accounts/batch-settings")
def batch_update_project_accounts(
    project_id: uuid.UUID,
    payload: AccountBatchSettings,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    access = project_access(db, project_id, actor)
    _require_explicit_account_scope(db, project_id, payload.account_ids, access)
    changes = {
        "operator_name": payload.operator_name,
        "account_type": payload.account_type,
        "page_type": payload.page_type,
        "promotion_page": payload.promotion_page,
        "promotion_link": payload.promotion_link,
        "rebate_rate": payload.rebate_rate,
        "recharge_account": payload.recharge_account,
        "lifecycle_stage": payload.lifecycle_stage,
    }
    selected_changes = {key: value for key, value in changes.items() if value is not None}
    if not selected_changes:
        raise HTTPException(status_code=422, detail="请至少填写一项要批量设置的内容")

    account_filters = [Account.project_id == project_id]
    if access.operator_names is not None:
        account_filters.append(Account.operator_name.in_(access.operator_names))
    accounts = db.scalars(select(Account).where(*account_filters)).all()
    matched_accounts: dict[uuid.UUID, Account] = {}
    unmatched: list[str] = []
    ambiguous: list[str] = []
    if payload.account_ids:
        requested_ids = set(payload.account_ids)
        matched_accounts = {
            account.id: account for account in accounts
            if account.id in requested_ids and account.is_active
        }
        missing_ids = requested_ids.difference(matched_accounts)
        if missing_ids:
            raise HTTPException(status_code=422, detail="所选账户中存在已归档或不属于当前项目的账户，请刷新后重试")
    else:
        for selector in payload.selectors:
            candidates = [
                account for account in accounts
                if account.login_name == selector or account.account_subject == selector
            ]
            if not candidates:
                unmatched.append(selector)
            elif len(candidates) > 1:
                ambiguous.append(selector)
            else:
                matched_accounts[candidates[0].id] = candidates[0]

    for account in matched_accounts.values():
        if payload.account_type is not None:
            account.account_type = payload.account_type
        if payload.operator_name is not None:
            account.operator_name = payload.operator_name
        if payload.page_type is not None:
            account.page_type = payload.page_type
        if payload.promotion_page is not None:
            account.promotion_page = payload.promotion_page
        if payload.promotion_link is not None:
            account.landing_url_template = payload.promotion_link
        if payload.lifecycle_stage is not None:
            account.lifecycle_override = None if payload.lifecycle_stage == "自动判断" else payload.lifecycle_stage

    propagated_account_count = 0
    matched_manager_ids = {
        account.manager_id
        for account in matched_accounts.values()
        if account.manager_id is not None
        and account.manager.financial_settings_mode != "legacy_per_account"
    }
    if payload.rebate_rate is not None or payload.recharge_account is not None:
        for manager_id in matched_manager_ids:
            propagated_account_count += apply_manager_financial_settings(
                db,
                manager_id=manager_id,
                rebate_rate=payload.rebate_rate,
                recharge_account=payload.recharge_account,
            )
        for account in matched_accounts.values():
            if (
                account.manager_id is not None
                and account.manager.financial_settings_mode != "legacy_per_account"
            ):
                continue
            if payload.rebate_rate is not None:
                account.rebate_rate = payload.rebate_rate
            if payload.recharge_account is not None:
                account.recharge_account = payload.recharge_account

    if payload.lifecycle_stage is not None and matched_accounts:
        create_refund_notifications(db, project_id)

    result = {
        "matched_count": len(matched_accounts),
        "updated_count": len(matched_accounts),
        "manager_count": len(matched_manager_ids),
        "propagated_account_count": propagated_account_count,
        "unmatched": unmatched,
        "ambiguous": ambiguous,
    }
    add_audit(
        db, project_id, actor, "account.batch_settings.update", "account", "批量设置账户业务信息",
        details={**result, "fields": list(selected_changes)},
    )
    db.commit()
    return envelope(request, result)


def _serialize_custom_id_mapping(mapping: HduofenAccountMapping, account: Account) -> dict:
    return {
        "id": str(mapping.id),
        "custom_id": mapping.custom_id,
        "account_id": account.baidu_account_id,
        "account_name": account.login_name,
        "account_subject": account.account_subject,
        "updated_at": mapping.updated_at,
    }


@router.get("/projects/{project_id}/custom-ids")
def list_project_custom_ids(
    project_id: uuid.UUID,
    request: Request,
    search: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=500, ge=1, le=1000),
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    access = project_access(db, project_id, actor)
    conditions = [HduofenAccountMapping.project_id == project_id]
    if access.operator_names is not None:
        conditions.append(Account.operator_name.in_(access.operator_names))
    cleaned_search = search.strip() if search else ""
    if cleaned_search:
        pattern = f"%{cleaned_search}%"
        matches = [
            HduofenAccountMapping.custom_id.ilike(pattern),
            Account.login_name.ilike(pattern),
            Account.account_subject.ilike(pattern),
        ]
        if cleaned_search.isdigit():
            matches.append(Account.baidu_account_id == int(cleaned_search))
        conditions.append(or_(*matches))
    base = (
        select(HduofenAccountMapping, Account)
        .join(Account, HduofenAccountMapping.account_id == Account.id)
        .where(*conditions)
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(
        base.order_by(desc(HduofenAccountMapping.updated_at), Account.login_name).limit(limit)
    ).all()
    return envelope(request, {
        "total": total,
        "limit": limit,
        "rows": [_serialize_custom_id_mapping(mapping, account) for mapping, account in rows],
    })


@router.post("/projects/{project_id}/custom-ids", status_code=201)
def create_project_custom_id(
    project_id: uuid.UUID,
    payload: HduofenCustomIdCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    access = project_access(db, project_id, actor)
    account_conditions = [Account.login_name == payload.account]
    if payload.account.isdigit():
        account_conditions.append(Account.baidu_account_id == int(payload.account))
    accounts = db.scalars(select(Account).where(
        Account.project_id == project_id,
        or_(*account_conditions),
    )).all()
    if not accounts:
        raise HTTPException(status_code=404, detail="当前项目未找到该账户，请输入完整账户名或账户ID")
    if len(accounts) > 1:
        raise HTTPException(status_code=409, detail="账户匹配不唯一，请改用百度账户ID")
    account = accounts[0]
    require_account_scope(access, account)
    existing_id = db.scalar(select(HduofenAccountMapping).where(
        HduofenAccountMapping.project_id == project_id,
        HduofenAccountMapping.custom_id == payload.custom_id,
    ))
    if existing_id is not None:
        existing_account = db.get(Account, existing_id.account_id)
        if existing_id.account_id == account.id:
            return envelope(request, {
                "created": False,
                "mapping": _serialize_custom_id_mapping(existing_id, account),
            })
        raise HTTPException(
            status_code=409,
            detail=f"自定义ID已绑定账户：{existing_account.login_name if existing_account else existing_id.account_id}",
        )
    existing_account_mapping = db.scalar(select(HduofenAccountMapping).where(
        HduofenAccountMapping.project_id == project_id,
        HduofenAccountMapping.account_id == account.id,
    ).order_by(desc(HduofenAccountMapping.updated_at)))
    if existing_account_mapping is not None:
        raise HTTPException(
            status_code=409,
            detail=f"该账户已有自定义ID：{existing_account_mapping.custom_id}",
        )
    now = datetime.now(UTC)
    mapping = HduofenAccountMapping(
        project_id=project_id,
        custom_id=payload.custom_id,
        account_id=account.id,
        source_file="manual://account-management",
        source_sha256=hashlib.sha256(
            f"{project_id}:{account.id}:{payload.custom_id}".encode("utf-8")
        ).hexdigest(),
        created_at=now,
        updated_at=now,
    )
    db.add(mapping)
    db.flush()
    add_audit(
        db,
        project_id,
        actor,
        "hduofen.custom_id.create",
        "hduofen_account_mapping",
        "手工添加账户自定义ID映射",
        str(mapping.id),
        {
            "account_id": account.baidu_account_id,
            "account_name": account.login_name,
            "custom_id": payload.custom_id,
        },
    )
    db.commit()
    return envelope(request, {
        "created": True,
        "mapping": _serialize_custom_id_mapping(mapping, account),
    })


@router.post("/projects/{project_id}/custom-ids/batch", status_code=201)
def create_project_custom_ids_batch(
    project_id: uuid.UUID,
    payload: HduofenCustomIdBatchCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    access = project_access(db, project_id, actor)
    project_accounts = db.scalars(select(Account).where(Account.project_id == project_id)).all()
    accounts_by_name: dict[str, list[Account]] = {}
    accounts_by_baidu_id = {str(account.baidu_account_id): account for account in project_accounts}
    for account in project_accounts:
        accounts_by_name.setdefault(account.login_name, []).append(account)

    errors: list[str] = []
    resolved: list[tuple[int, HduofenCustomIdCreate, Account]] = []
    for line_number, item in enumerate(payload.mappings, start=1):
        candidates = accounts_by_name.get(item.account) or []
        if not candidates and item.account.isdigit():
            account = accounts_by_baidu_id.get(item.account)
            candidates = [account] if account is not None else []
        if not candidates:
            errors.append(f"第{line_number}行：未找到账户 {item.account}")
        elif len(candidates) > 1:
            errors.append(f"第{line_number}行：账户匹配不唯一，请使用百度账户ID")
        else:
            resolved.append((line_number, item, candidates[0]))

    for _, _, account in resolved:
        require_account_scope(access, account)

    custom_counts = Counter(item.custom_id for _, item, _ in resolved)
    account_counts = Counter(account.id for _, _, account in resolved)
    for line_number, item, account in resolved:
        if custom_counts[item.custom_id] > 1:
            errors.append(f"第{line_number}行：自定义ID在本次输入中重复：{item.custom_id}")
        if account_counts[account.id] > 1:
            errors.append(f"第{line_number}行：账户在本次输入中重复：{account.login_name}")

    custom_ids = [item.custom_id for _, item, _ in resolved]
    account_ids = [account.id for _, _, account in resolved]
    existing_rows = db.scalars(select(HduofenAccountMapping).where(
        HduofenAccountMapping.project_id == project_id,
        or_(
            HduofenAccountMapping.custom_id.in_(custom_ids),
            HduofenAccountMapping.account_id.in_(account_ids),
        ),
    )).all() if resolved else []
    existing_by_custom = {row.custom_id: row for row in existing_rows}
    existing_by_account: dict[uuid.UUID, HduofenAccountMapping] = {}
    for row in existing_rows:
        existing_by_account.setdefault(row.account_id, row)

    unchanged: list[tuple[HduofenCustomIdCreate, Account]] = []
    pending: list[tuple[HduofenCustomIdCreate, Account]] = []
    for line_number, item, account in resolved:
        custom_mapping = existing_by_custom.get(item.custom_id)
        account_mapping = existing_by_account.get(account.id)
        if custom_mapping is not None and custom_mapping.account_id != account.id:
            bound_account = db.get(Account, custom_mapping.account_id)
            errors.append(
                f"第{line_number}行：{item.custom_id} 已绑定账户 "
                f"{bound_account.login_name if bound_account else custom_mapping.account_id}"
            )
        elif account_mapping is not None and account_mapping.custom_id != item.custom_id:
            errors.append(
                f"第{line_number}行：账户 {account.login_name} 已有自定义ID "
                f"{account_mapping.custom_id}"
            )
        elif custom_mapping is not None:
            unchanged.append((item, account))
        else:
            pending.append((item, account))

    if errors:
        unique_errors = list(dict.fromkeys(errors))
        suffix = f"；另有 {len(unique_errors) - 12} 条错误" if len(unique_errors) > 12 else ""
        raise HTTPException(status_code=422, detail="；".join(unique_errors[:12]) + suffix)

    now = datetime.now(UTC)
    source_payload = [item.model_dump() for item in payload.mappings]
    source_sha256 = hashlib.sha256(json.dumps(
        source_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    created_rows = []
    for item, account in pending:
        row = HduofenAccountMapping(
            project_id=project_id,
            custom_id=item.custom_id,
            account_id=account.id,
            source_file="manual://account-management-batch",
            source_sha256=source_sha256,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        created_rows.append((row, account))
    db.flush()
    add_audit(
        db,
        project_id,
        actor,
        "hduofen.custom_id.batch_create",
        "project",
        "批量添加账户自定义ID映射",
        str(project_id),
        {
            "submitted_count": len(payload.mappings),
            "created_count": len(created_rows),
            "unchanged_count": len(unchanged),
            "source_sha256": source_sha256,
        },
    )
    db.commit()
    return envelope(request, {
        "submitted_count": len(payload.mappings),
        "created_count": len(created_rows),
        "unchanged_count": len(unchanged),
        "mappings": [
            _serialize_custom_id_mapping(mapping, account)
            for mapping, account in created_rows
        ],
    })


def _campaign_batch_accounts(
    db: Session,
    project_id: uuid.UUID,
    payload: CampaignSettingsScopeRequest,
    allowed_operator_names: tuple[str, ...] | None = None,
) -> list[Account]:
    conditions = [
        Account.project_id == project_id,
        Account.is_active.is_(True),
        Account.eliminated_at.is_(None),
    ]
    if allowed_operator_names is not None:
        conditions.append(Account.operator_name.in_(allowed_operator_names))
    if payload.account_ids:
        conditions.append(Account.id.in_(payload.account_ids))
    if payload.account_type is not None:
        conditions.append(Account.account_type == payload.account_type)
    if payload.page_type is not None:
        conditions.append(Account.page_type == payload.page_type)
    return list(db.scalars(
        select(Account)
        .where(*conditions)
        .order_by(Account.baidu_account_id)
    ).all())


def _campaign_scope_keys(payload: CampaignSettingsScopeRequest) -> tuple[str, str]:
    """Persist wildcard scope fields as empty strings in the existing non-null columns."""
    return (
        payload.account_type.value if payload.account_type is not None else "",
        payload.page_type or "",
    )


def _campaign_setting_record(
    db: Session,
    project_id: uuid.UUID,
    payload: CampaignSettingsScopeRequest,
) -> CampaignBatchSetting | None:
    account_type, page_type = _campaign_scope_keys(payload)
    return db.scalar(select(CampaignBatchSetting).where(
        CampaignBatchSetting.project_id == project_id,
        CampaignBatchSetting.account_type == account_type,
        CampaignBatchSetting.page_type == page_type,
    ))


def _serialize_campaign_setting(
    row: CampaignBatchSetting | None,
    matched_account_count: int,
) -> dict:
    return {
        "configured": row is not None,
        "matched_account_count": matched_account_count,
        "lifecycle_stage": None,
        "online_schedule": row.online_schedule if row else None,
        "online_weekdays": row.online_weekdays if row else None,
        "online_start_hour": row.online_start_hour if row else None,
        "online_end_hour": row.online_end_hour if row else None,
        "schedule_status": row.schedule_status if row else None,
        "schedule_task_id": str(row.schedule_task_id) if row and row.schedule_task_id else None,
        "schedule_account_count": row.schedule_account_count if row else None,
        "schedule_plan_count": row.schedule_plan_count if row else None,
        "schedule_updated_at": row.schedule_updated_at if row else None,
        "pause": row.pause if row else None,
        "pause_status": row.pause_status if row else None,
        "pause_task_id": str(row.pause_task_id) if row and row.pause_task_id else None,
        "pause_account_count": row.pause_account_count if row else None,
        "pause_plan_count": row.pause_plan_count if row else None,
        "pause_updated_at": row.pause_updated_at if row else None,
        "updated_by": row.updated_by if row else None,
        "updated_at": row.updated_at if row else None,
        "source": "system_setting_record",
    }


@router.post("/projects/{project_id}/campaign-settings/current")
def current_campaign_settings(
    project_id: uuid.UUID,
    payload: CampaignSettingsScopeRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    access = project_access(db, project_id, actor)
    _require_explicit_account_scope(db, project_id, payload.account_ids, access)
    accounts = _campaign_batch_accounts(db, project_id, payload, access.operator_names)
    row = _campaign_setting_record(db, project_id, payload)
    return envelope(request, _serialize_campaign_setting(row, len(accounts)))


def _campaign_batch_preview_data(
    project_id: uuid.UUID,
    payload: CampaignBatchUpdateRequest,
    accounts: list[Account],
) -> dict:
    account_type, page_type = _campaign_scope_keys(payload)
    pause_schedule = None
    if payload.action == "schedule":
        pause_schedule = (
            build_plan_pause_schedule_from_windows(
                True,
                [window.model_dump() for window in payload.online_schedule],
            )
            if payload.online_schedule is not None
            else build_plan_pause_schedule(
                True,
                payload.online_weekdays,
                payload.online_start_hour,
                payload.online_end_hour,
            )
        )
    request_data = payload.model_dump(mode="json")
    fingerprint = hashlib.sha256(json.dumps(
        {"project_id": str(project_id), **request_data},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return {
        "fingerprint": fingerprint,
        "action": payload.action,
        "account_type": account_type or None,
        "page_type": page_type or None,
        "lifecycle_stage": None,
        "matched_account_count": len(accounts),
        "sample_accounts": [
            {"account_id": row.baidu_account_id, "account_name": row.login_name}
            for row in accounts[:12]
        ],
        "plan_count": None,
        "plan_count_note": "任务执行时逐账户读取百度计划后确定；当前设置展示本系统记录",
        "online_schedule": (
            [window.model_dump() for window in payload.online_schedule]
            if payload.action == "schedule" and payload.online_schedule is not None
            else None
        ),
        "online_weekdays": payload.online_weekdays if payload.action == "schedule" else None,
        "online_start_hour": payload.online_start_hour if payload.action == "schedule" else None,
        "online_end_hour": payload.online_end_hour if payload.action == "schedule" else None,
        "pause_schedule": pause_schedule,
        "pause": payload.pause if payload.action == "pause" else None,
        "writes_enabled": settings.baidu_writes_enabled,
    }


@router.post("/projects/{project_id}/campaign-batch/preview")
def preview_campaign_batch_update(
    project_id: uuid.UUID,
    payload: CampaignBatchUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    access = project_access(db, project_id, actor)
    _require_explicit_account_scope(db, project_id, payload.account_ids, access)
    accounts = _campaign_batch_accounts(db, project_id, payload, access.operator_names)
    return envelope(request, _campaign_batch_preview_data(project_id, payload, accounts))


@router.post("/projects/{project_id}/campaign-batch", status_code=202)
def create_campaign_batch_update(
    project_id: uuid.UUID,
    payload: CampaignBatchUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    access = project_access(db, project_id, actor)
    _require_explicit_account_scope(db, project_id, payload.account_ids, access)
    accounts = _campaign_batch_accounts(db, project_id, payload, access.operator_names)
    if not accounts:
        raise HTTPException(status_code=422, detail="当前筛选条件没有可执行账户")
    preview = _campaign_batch_preview_data(project_id, payload, accounts)
    active_tasks = db.scalars(select(BackgroundTask).where(
        BackgroundTask.project_id == project_id,
        BackgroundTask.task_type == "campaign_batch_update",
        BackgroundTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
    )).all()
    if any(
        isinstance(task.result, dict)
        and isinstance(task.result.get("request"), dict)
        and task.result["request"].get("fingerprint") == preview["fingerprint"]
        for task in active_tasks
    ):
        raise HTTPException(status_code=409, detail="相同条件的计划批量任务正在执行，请勿重复提交")

    task = BackgroundTask(
        project_id=project_id,
        task_type="campaign_batch_update",
        status=TaskStatus.PENDING,
        current_node="queued",
        progress=0,
        result={
            "request": {
                **payload.model_dump(mode="json"),
                "fingerprint": preview["fingerprint"],
                "account_ids": [str(account.id) for account in accounts],
                "requested_by": actor.username,
            },
            "state": {},
        },
    )
    db.add(task)
    db.flush()
    # An explicit selection is a one-off operation. It must not overwrite the
    # saved default for an account-type/page-type scope.
    if not payload.account_ids:
        setting = _campaign_setting_record(db, project_id, payload)
        if setting is None:
            account_type, page_type = _campaign_scope_keys(payload)
            setting = CampaignBatchSetting(
                project_id=project_id,
                account_type=account_type,
                page_type=page_type,
                updated_by=actor.username,
            )
            db.add(setting)
        now = datetime.now(UTC)
        if payload.action == "schedule":
            setting.online_schedule = (
                [window.model_dump() for window in payload.online_schedule]
                if payload.online_schedule is not None
                else None
            )
            setting.online_weekdays = payload.online_weekdays
            setting.online_start_hour = payload.online_start_hour
            setting.online_end_hour = payload.online_end_hour
            setting.schedule_status = "pending"
            setting.schedule_task_id = task.id
            setting.schedule_account_count = len(accounts)
            setting.schedule_plan_count = None
            setting.schedule_updated_at = now
        else:
            setting.pause = payload.pause
            setting.pause_status = "pending"
            setting.pause_task_id = task.id
            setting.pause_account_count = len(accounts)
            setting.pause_plan_count = None
            setting.pause_updated_at = now
        setting.updated_by = actor.username
        setting.updated_at = now
    add_audit(
        db,
        project_id,
        actor,
        "campaign.batch_update.queue",
        "background_task",
        "提交账户计划批量设置",
        str(task.id),
        {
            "action": payload.action,
            "account_type": preview["account_type"],
            "page_type": preview["page_type"],
            "matched_account_count": len(accounts),
            "writes_enabled": settings.baidu_writes_enabled,
        },
    )
    db.commit()
    from .worker import run_campaign_batch_update
    run_campaign_batch_update.delay(str(task.id))
    return envelope(request, {
        "task_id": str(task.id),
        "status": "queued",
        **preview,
    })


@router.post("/projects/{project_id}/managers/{manager_id}/campaigns/clear", status_code=202)
def clear_manager_campaigns(
    project_id: uuid.UUID,
    manager_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    """Queue a destructive, manager-scoped campaign deletion with readback."""

    require_project(db, project_id)
    manager = db.get(AccountManager, manager_id)
    if manager is None or manager.project_id != project_id:
        raise HTTPException(status_code=404, detail="账户管家不存在或不属于当前项目")
    if not settings.baidu_writes_enabled:
        raise HTTPException(status_code=409, detail="百度写入开关未开启，无法清空计划")

    active_task = db.scalar(
        select(BackgroundTask.id).where(
            BackgroundTask.project_id == project_id,
            BackgroundTask.task_type == "manager_campaign_cleanup",
            BackgroundTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
            BackgroundTask.result["request"]["manager_id"].astext == str(manager_id),
        ).limit(1)
    )
    if active_task is not None:
        raise HTTPException(status_code=409, detail=f"该管家的清空计划任务已在执行：{active_task}")

    accounts = list(db.scalars(
        select(Account)
        .where(Account.project_id == project_id, Account.manager_id == manager_id)
        .order_by(Account.baidu_account_id)
    ).all())
    if not accounts:
        raise HTTPException(status_code=422, detail="该账户管家下没有可处理的账户")

    superseded_operations = list(db.scalars(
        select(Operation).where(
            Operation.target_account_id.in_([account.baidu_account_id for account in accounts]),
            Operation.status.in_([
                OperationStatus.DRAFT,
                OperationStatus.AWAITING_CONFIRMATION,
                OperationStatus.QUEUED,
            ]),
        )
    ).all())
    for operation in superseded_operations:
        operation.status = OperationStatus.FAILED

    task = BackgroundTask(
        project_id=project_id,
        task_type="manager_campaign_cleanup",
        status=TaskStatus.PENDING,
        current_node="queued",
        progress=0,
        heartbeat_at=datetime.now(UTC),
        result={
            "request": {
                "manager_id": str(manager.id),
                "manager_login_name": manager.login_name,
                "account_ids": [str(account.id) for account in accounts],
                "requested_by": actor.username,
            },
            "state": {},
        },
    )
    db.add(task)
    db.flush()
    db.add(AuditEvent(
        project_id=project_id,
        actor=actor.username,
        action="manager.campaign_cleanup.queue",
        target_type="account_manager",
        target_id=str(manager.id),
        summary="提交清空账户管家下全部计划任务",
        details={
            "task_id": str(task.id),
            "manager_login_name": manager.login_name,
            "account_count": len(accounts),
            "superseded_operation_ids": [str(operation.id) for operation in superseded_operations],
        },
    ))
    db.commit()
    from .worker import run_manager_campaign_cleanup

    run_manager_campaign_cleanup.delay(str(task.id))
    return envelope(request, {
        "task_id": str(task.id),
        "status": "queued",
        "manager_login_name": manager.login_name,
        "account_count": len(accounts),
        "superseded_operation_count": len(superseded_operations),
    })


@router.get("/projects/{project_id}/campaign-cache/summary")
def campaign_cache_summary(
    project_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    access = project_access(db, project_id, actor)
    scoped_account_ids = select(Account.id).where(Account.project_id == project_id)
    account_filters = [Account.project_id == project_id]
    if access.operator_names is not None:
        scoped_account_ids = scoped_account_ids.where(Account.operator_name.in_(access.operator_names))
        account_filters.append(Account.operator_name.in_(access.operator_names))
    cached_plans = db.scalar(select(func.count(CampaignCache.id)).where(
        CampaignCache.project_id == project_id,
        CampaignCache.account_id.in_(scoped_account_ids),
        CampaignCache.is_active.is_(True),
    )) or 0
    cached_accounts = db.scalar(select(func.count(func.distinct(CampaignCache.account_id))).where(
        CampaignCache.project_id == project_id,
        CampaignCache.account_id.in_(scoped_account_ids),
        CampaignCache.is_active.is_(True),
    )) or 0
    account_stats = db.execute(select(
        func.count(Account.id),
        func.count(Account.id).filter(Account.campaign_cache_status == "succeeded"),
        func.min(Account.campaign_cache_synced_at),
        func.max(Account.campaign_cache_synced_at),
    ).where(*account_filters)).one()
    return envelope(request, {
        "cached_plan_count": int(cached_plans),
        "cached_account_count": int(cached_accounts),
        "project_account_count": int(account_stats[0] or 0),
        "synchronized_account_count": int(account_stats[1] or 0),
        "earliest_synced_at": account_stats[2],
        "latest_synced_at": account_stats[3],
    })


@router.post("/projects/{project_id}/campaign-cache/sync", status_code=202)
def create_campaign_cache_sync(
    project_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    access = project_access(db, project_id, actor)
    running = db.scalar(select(BackgroundTask.id).where(
        BackgroundTask.project_id == project_id,
        BackgroundTask.task_type == "campaign_cache_sync",
        BackgroundTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
    ).limit(1))
    if running is not None:
        raise HTTPException(status_code=409, detail="计划缓存同步任务正在运行")
    accounts = _campaign_batch_accounts(
        db,
        project_id,
        CampaignSettingsScopeRequest(account_type=None, page_type=None),
        access.operator_names,
    )
    if not accounts:
        raise HTTPException(status_code=422, detail="当前项目没有符合当前范围的可同步账户")
    task = BackgroundTask(
        project_id=project_id,
        task_type="campaign_cache_sync",
        status=TaskStatus.PENDING,
        current_node="queued",
        progress=0,
        result={
            "request": {
                "account_ids": [str(account.id) for account in accounts],
                "requested_by": actor.username,
            },
            "state": {},
        },
    )
    db.add(task)
    db.flush()
    add_audit(
        db,
        project_id,
        actor,
        "campaign.cache.sync.queue",
        "background_task",
        "提交账户计划缓存同步",
        str(task.id),
        {"account_count": len(accounts)},
    )
    db.commit()
    from .worker import sync_campaign_cache
    sync_campaign_cache.delay(str(task.id))
    return envelope(request, {
        "task_id": str(task.id),
        "status": "queued",
        "account_count": len(accounts),
    })


def task_result_summary(task: BackgroundTask) -> str:
    result = task.result if isinstance(task.result, dict) else {}
    state = result.get("state") if isinstance(result.get("state"), dict) else {}
    request_details = result.get("request") if isinstance(result.get("request"), dict) else {}

    if task.task_type == "campaign_batch_update":
        account_ids = request_details.get("account_ids")
        total = len(account_ids) if isinstance(account_ids, list) else 0
        processed = int(state.get("processed_accounts") or state.get("cursor") or 0)
        updated = int(state.get("updated_plan_count") or 0)
        unchanged = int(state.get("unchanged_plan_count") or 0)
        failures = state.get("failed_accounts")
        failed = len(failures) if isinstance(failures, dict) else 0
        action = "修改时段" if request_details.get("action") == "schedule" else "修改启停状态"
        return (
            f"{action}：已处理 {processed}/{total} 个账户，"
            f"更新 {updated} 个计划，无需修改 {unchanged} 个，失败 {failed} 个账户"
        )

    sources = [state, result]
    metric_labels = (
        ("processed_accounts", "已处理账户"),
        ("account_count", "账户"),
        ("updated_count", "已更新"),
        ("created_count", "已创建"),
        ("deleted", "已删除"),
        ("replenished", "已补充"),
        ("checked", "已检查"),
        ("matched_account_count", "命中账户"),
        ("paused_account_count", "已暂停账户"),
        ("paused_campaign_count", "已暂停计划"),
        ("skipped_count", "已跳过"),
        ("failed_count", "失败"),
    )
    metrics: list[str] = []
    seen: set[str] = set()
    for source in sources:
        for key, label in metric_labels:
            value = source.get(key)
            if key not in seen and isinstance(value, (int, float)) and not isinstance(value, bool):
                metrics.append(f"{label} {value}")
                seen.add(key)
            if len(metrics) >= 4:
                break
        if len(metrics) >= 4:
            break
    if metrics:
        return "，".join(metrics)
    if task.last_error:
        return f"未完成：{task.last_error}"
    if task.status == TaskStatus.SUCCEEDED:
        return "执行完成"
    if task.status in {TaskStatus.PENDING, TaskStatus.RUNNING}:
        return "正在执行，结果持续更新"
    if task.status == TaskStatus.BLOCKED:
        return "等待处理后继续"
    return "暂无结果"


def serialize_task_row(
    task: BackgroundTask,
    operation: Operation | None = None,
    account: Account | None = None,
    *,
    is_latest_attempt: bool = True,
) -> dict:
    result = task.result if isinstance(task.result, dict) else {}
    request_details = (
        result.get("request")
        if isinstance(result.get("request"), dict)
        else {}
    )
    workflow_state = (
        result.get("workflow_state")
        if isinstance(result.get("workflow_state"), dict)
        else result.get("state") if isinstance(result.get("state"), dict) else {}
    )
    readback = workflow_state.get("readback")
    if not isinstance(readback, dict):
        readback = None
    target_account_id = operation.target_account_id if operation is not None else None
    target_login_name = account.login_name if account is not None else None
    manager_login_name = account.manager_login_name if account is not None else None
    if operation is not None and isinstance(operation.payload, dict):
        target_login_name = target_login_name or operation.payload.get("target_login_name")
        manager_login_name = manager_login_name or operation.payload.get("manager_login_name")
    resumable_status = task.status in {TaskStatus.FAILED, TaskStatus.BLOCKED}
    superseded = bool(
        resumable_status
        and operation is not None
        and (not is_latest_attempt or operation.status == OperationStatus.SUCCEEDED)
    )
    auto_retry = (
        workflow_state.get("auto_retry")
        if isinstance(workflow_state.get("auto_retry"), dict)
        else None
    )
    can_resume = bool(
        resumable_status
        and not superseded
        and auto_retry is None
        and (operation is None or operation.status == OperationStatus.FAILED)
    )

    return {
        "id": str(task.id),
        "operation_id": str(operation.id) if operation is not None else None,
        "operation_type": operation.operation_type if operation is not None else None,
        "account_name": target_login_name,
        "account_id": target_account_id,
        "manager_login_name": manager_login_name,
        "can_resume": can_resume,
        "superseded": superseded,
        "task_type": task.task_type,
        "execution_action": (
            str(request_details.get("action") or "")
            if task.task_type == "campaign_batch_update"
            else None
        ),
        "status": task.status.value,
        "current_node": task.current_node,
        "progress": task.progress,
        "retry_count": task.retry_count,
        "last_error": task.last_error,
        "result_summary": task_result_summary(task),
        "readback": readback,
        "heartbeat_at": task.heartbeat_at,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


@router.get("/projects/{project_id}/alerts")
def list_project_alerts(project_id: uuid.UUID, request: Request, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    require_project(db, project_id)
    access = project_access(db, project_id, actor)
    scope_filters = [Account.operator_name.in_(access.operator_names)] if access.operator_names is not None else []
    rows = db.scalars(
        select(Alert).join(Account, Alert.account_id == Account.id)
        .where(Account.project_id == project_id, *scope_filters).order_by(desc(Alert.created_at)).limit(100)
    ).all()
    return envelope(request, [{"id": str(row.id), "type": row.alert_type, "severity": row.severity, "title": row.title, "details": row.details, "status": row.status, "created_at": row.created_at} for row in rows])


@router.get("/projects/{project_id}/tasks")
def list_project_tasks(project_id: uuid.UUID, request: Request, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    require_project(db, project_id)
    access = project_access(db, project_id, actor)
    rows = db.execute(
        select(BackgroundTask, Operation, Account)
        .outerjoin(Operation, BackgroundTask.operation_id == Operation.id)
        .outerjoin(
            Account,
            and_(
                Operation.target_account_id == Account.baidu_account_id,
                Account.project_id == project_id,
            ),
        )
        .where(or_(BackgroundTask.project_id == project_id, Account.project_id == project_id))
        .order_by(desc(BackgroundTask.created_at)).limit(100)
    ).all()
    if access.operator_names is not None:
        rows = [
            (task, operation, account)
            for task, operation, account in rows
            if (
                account is not None and account.operator_name in access.operator_names
            ) or (
                account is None
                and isinstance(task.result, dict)
                and isinstance(task.result.get("request"), dict)
                and task.result["request"].get("requested_by") == actor.username
            )
        ]
    latest_task_ids: dict[uuid.UUID, uuid.UUID] = {}
    for task, operation, _account in rows:
        if operation is not None:
            latest_task_ids.setdefault(operation.id, task.id)
    return envelope(request, [
        serialize_task_row(
            task,
            operation,
            account,
            is_latest_attempt=(
                operation is None or latest_task_ids.get(operation.id) == task.id
            ),
        )
        for task, operation, account in rows
    ])


@router.get("/projects/{project_id}/tasks/{task_id}")
def project_task_detail(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    task = db.scalar(select(BackgroundTask).where(
        BackgroundTask.id == task_id,
        BackgroundTask.project_id == project_id,
    ))
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    _require_task_access(db, task, actor, "view")
    return envelope(request, {
        "id": str(task.id),
        "status": task.status.value,
        "current_node": task.current_node,
        "progress": task.progress,
        "retry_count": task.retry_count,
        "last_error": task.last_error,
        "result": task.result,
        "heartbeat_at": task.heartbeat_at,
    })


@router.post("/projects/{project_id}/tasks/{task_id}/resume")
def resume_project_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    task = db.scalar(select(BackgroundTask).where(
        BackgroundTask.id == task_id,
        BackgroundTask.project_id == project_id,
    ))
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    _require_task_access(db, task, actor, "manage")
    request.state.project_task_authorized = True
    return resume_task(task_id, request, db, actor)


@router.post("/projects/{project_id}/tasks/{task_id}/cancel")
def cancel_project_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    task = db.scalar(
        select(BackgroundTask)
        .where(
            BackgroundTask.id == task_id,
            BackgroundTask.project_id == project_id,
        )
        .with_for_update()
    )
    if task is None:
        operation = db.scalar(
            select(Operation).where(Operation.id == task_id).with_for_update()
        )
        if operation is None or operation.operation_type != "search_ad_build_workflow":
            raise HTTPException(status_code=404, detail="任务不存在")
        payload = operation.payload if isinstance(operation.payload, dict) else {}
        try:
            job_id = uuid.UUID(str(payload.get("ad_build_job_id")))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="任务不存在") from exc
        job = db.scalar(select(AdBuildJob).where(
            AdBuildJob.id == job_id,
            AdBuildJob.project_id == project_id,
        ))
        if job is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if operation.status != OperationStatus.QUEUED:
            raise HTTPException(status_code=409, detail="当前任务已经开始执行，不能安全取消")
        task = BackgroundTask(
            project_id=project_id,
            operation_id=operation.id,
            task_type=operation.operation_type,
            status=TaskStatus.PENDING,
            current_node="scheduled_ad_build_wait",
            progress=0,
        )
        db.add(task)
        db.flush()
    _require_task_access(db, task, actor, "manage")
    if task.task_type != "search_ad_build_workflow":
        raise HTTPException(status_code=409, detail="仅自动上线任务支持从这里取消")
    result = dict(task.result) if isinstance(task.result, dict) else {}
    if result.get("cancelled"):
        return envelope(request, {"id": str(task.id), "status": "cancelled"})
    if task.status != TaskStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail="只有尚未开始的任务可以安全取消；执行中的任务不会被强制中断",
        )

    cancelled_at = datetime.now(UTC)
    result.update({
        "cancelled": True,
        "cancelled_by": actor.username,
        "cancelled_at": cancelled_at.isoformat(),
    })
    task.result = result
    flag_modified(task, "result")
    task.status = TaskStatus.BLOCKED
    task.current_node = "cancelled"
    task.heartbeat_at = cancelled_at
    task.last_error = None
    operation = db.get(Operation, task.operation_id) if task.operation_id else None
    if operation is not None and operation.status in {
        OperationStatus.DRAFT,
        OperationStatus.AWAITING_CONFIRMATION,
        OperationStatus.QUEUED,
    }:
        operation.status = OperationStatus.FAILED
    add_audit(
        db,
        project_id,
        actor,
        "cancel_ad_build_task",
        "background_task",
        "取消尚未执行的自动上线任务",
        target_id=str(task.id),
        details={"operation_id": str(task.operation_id) if task.operation_id else None},
    )
    db.commit()
    return envelope(request, {"id": str(task.id), "status": "cancelled"})


@router.get("/projects/{project_id}/notifications")
def list_project_notifications(
    project_id: uuid.UUID,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    access = project_access(db, project_id, actor)
    rows = db.scalars(
        select(Notification)
        .where(Notification.project_id == project_id)
        .order_by(desc(Notification.occurred_at), desc(Notification.created_at))
        .limit(limit)
    ).all()
    if access.operator_names is not None:
        scoped_account_ids = {
            str(value) for value in db.scalars(select(Account.id).where(
                Account.project_id == project_id,
                Account.operator_name.in_(access.operator_names),
            )).all()
        }
        scoped_baidu_ids = {
            str(value) for value in db.scalars(select(Account.baidu_account_id).where(
                Account.project_id == project_id,
                Account.operator_name.in_(access.operator_names),
            )).all()
        }
        allowed_ids = scoped_account_ids | scoped_baidu_ids
        rows = [
            row for row in rows
            if not isinstance(row.payload, dict)
            or not any(key in row.payload for key in ("account_id", "target_account_id"))
            or str(row.payload.get("account_id") or row.payload.get("target_account_id")) in allowed_ids
        ]
    row_ids = [row.id for row in rows]
    read_ids = set(
        db.scalars(
            select(NotificationRead.notification_id).where(
                NotificationRead.username == actor.username,
                NotificationRead.notification_id.in_(row_ids),
            )
        ).all()
    ) if row_ids else set()
    unread_count = sum(row.id not in read_ids for row in rows)
    return envelope(request, {
        "unread_count": unread_count,
        "items": [
            {
                "id": str(row.id),
                "category": row.category,
                "severity": row.severity,
                "title": row.title,
                "summary": row.summary,
                "body": row.body,
                "payload": row.payload or {},
                "occurred_at": row.occurred_at,
                "created_at": row.created_at,
                "is_read": row.id in read_ids,
            }
            for row in rows
        ],
    })


@router.post("/projects/{project_id}/notifications/{notification_id}/read")
def mark_notification_read(
    project_id: uuid.UUID,
    notification_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    notification = db.scalar(select(Notification).where(
        Notification.id == notification_id,
        Notification.project_id == project_id,
    ))
    if notification is None:
        raise HTTPException(status_code=404, detail="提醒不存在")
    db.execute(
        pg_insert(NotificationRead)
        .values(notification_id=notification_id, username=actor.username)
        .on_conflict_do_nothing(
            index_elements=[NotificationRead.notification_id, NotificationRead.username]
        )
    )
    db.commit()
    return envelope(request, {"id": str(notification_id), "is_read": True})


@router.post("/projects/{project_id}/notifications/read-all")
def mark_all_notifications_read(
    project_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    notification_ids = db.scalars(
        select(Notification.id).where(Notification.project_id == project_id)
    ).all()
    if notification_ids:
        db.execute(
            pg_insert(NotificationRead)
            .values([
                {"notification_id": notification_id, "username": actor.username}
                for notification_id in notification_ids
            ])
            .on_conflict_do_nothing(
                index_elements=[NotificationRead.notification_id, NotificationRead.username]
            )
        )
        db.commit()
    return envelope(request, {"read_count": len(notification_ids), "unread_count": 0})


@router.get("/accounts")
def list_accounts(request: Request, db: Session = Depends(get_db), _: Actor = Depends(current_actor)):
    rows = db.scalars(select(Account).order_by(Account.login_name)).all()
    return envelope(request, [serialize_account(row) for row in rows])


@router.get("/alerts")
def list_alerts(request: Request, db: Session = Depends(get_db), _: Actor = Depends(current_actor)):
    rows = db.scalars(select(Alert).order_by(desc(Alert.created_at)).limit(100)).all()
    return envelope(request, [{"id": str(row.id), "type": row.alert_type, "severity": row.severity, "title": row.title, "details": row.details, "status": row.status, "created_at": row.created_at} for row in rows])


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: uuid.UUID, request: Request, db: Session = Depends(get_db), actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR))):
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="告警不存在")
    alert.status = "resolved"
    alert.resolved_by = actor.username
    db.commit()
    return envelope(request, {"id": str(alert.id), "status": alert.status})


@router.post("/imports/preview")
async def import_preview(request: Request, file: UploadFile = File(...), _: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR))):
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="请上传 xlsx 或 xlsm 文件")
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件不能超过 20MB")
    return envelope(request, preview_workbook(file.filename, content).model_dump())


@router.get("/projects/{project_id}/materials")
def list_materials(project_id: uuid.UUID, request: Request, db: Session = Depends(get_db), _: Actor = Depends(current_actor)):
    require_project(db, project_id)
    materials = db.scalars(select(Material).where(Material.project_id == project_id).order_by(desc(Material.created_at))).all()
    data = []
    for material in materials:
        version = db.scalar(select(MaterialVersion).where(MaterialVersion.material_id == material.id).order_by(desc(MaterialVersion.version)).limit(1))
        data.append({
            "id": str(material.id), "name": material.name, "status": material.status,
            "current_version": material.current_version, "created_at": material.created_at,
            "latest": None if not version else {
                "version": version.version, "row_count": version.row_count,
                "sha256": version.sha256, "summary": version.summary,
                "created_by": version.created_by, "created_at": version.created_at,
            },
        })
    return envelope(request, data)


@router.get("/projects/{project_id}/material-keywords")
def list_material_keywords(
    project_id: uuid.UUID,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    blacklisted_only: bool = Query(default=False),
    year: int | None = Query(default=None, ge=2000, le=2100),
    search: str | None = Query(default=None, max_length=100),
    campaign_names: list[str] | None = Query(default=None),
    keyword_search: str | None = Query(default=None, max_length=100),
    blacklist_statuses: list[str] | None = Query(default=None),
    db: Session = Depends(get_db),
    _: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    material_query = select(
        MaterialKeyword.id,
        MaterialKeyword.campaign_name,
        MaterialKeyword.keyword_text,
        MaterialKeyword.is_blacklisted,
        MaterialKeyword.blacklist_reason,
    ).where(MaterialKeyword.project_id == project_id)
    normalized_campaign_names = [value.strip() for value in (campaign_names or []) if value.strip()]
    normalized_statuses = {value.strip().lower() for value in (blacklist_statuses or []) if value.strip()}
    if normalized_campaign_names:
        material_query = material_query.where(MaterialKeyword.campaign_name.in_(normalized_campaign_names))
    if blacklisted_only or normalized_statuses == {"blacklisted"}:
        material_query = material_query.where(MaterialKeyword.is_blacklisted.is_(True))
    elif normalized_statuses == {"normal"}:
        material_query = material_query.where(MaterialKeyword.is_blacklisted.is_(False))
    if keyword_search and keyword_search.strip():
        material_query = material_query.where(
            MaterialKeyword.keyword_text.ilike(f"%{keyword_search.strip()}%")
        )
    if search and search.strip():
        keyword = f"%{search.strip()}%"
        material_query = material_query.where(
            or_(
                MaterialKeyword.campaign_name.ilike(keyword),
                MaterialKeyword.keyword_text.ilike(keyword),
            )
        )
    material_scope = material_query.subquery()
    total = db.scalar(select(func.count()).select_from(material_scope)) or 0
    page_rows = db.execute(
        select(
            material_scope.c.id,
            material_scope.c.campaign_name,
            material_scope.c.keyword_text,
            material_scope.c.is_blacklisted,
            material_scope.c.blacklist_reason,
        )
        .order_by(material_scope.c.campaign_name, material_scope.c.keyword_text)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    page_keywords = [row.keyword_text for row in page_rows]

    daily_years = {
        int(value)
        for value in db.scalars(
            select(func.extract("year", KeywordPerformanceDaily.report_date))
            .join(Account, KeywordPerformanceDaily.account_id == Account.id)
            .where(Account.project_id == project_id)
            .distinct()
        ).all()
        if value is not None
    }
    historical_years = {
        int(value)
        for value in db.scalars(
            select(MaterialKeywordPerformanceYearly.report_year)
            .where(MaterialKeywordPerformanceYearly.project_id == project_id)
            .distinct()
        ).all()
        if value is not None
    }
    available_years = sorted(daily_years | historical_years, reverse=True)
    performance: dict[str, dict] = {}

    def merge_performance(row) -> None:
        totals = performance.setdefault(
            row.keyword_text,
            {
                "impressions": 0,
                "clicks": 0,
                "spend": Decimal("0"),
                "uv": 0,
                "copies": 0,
                "adds": 0,
            },
        )
        for field in ("impressions", "clicks", "uv", "copies", "adds"):
            totals[field] += int(getattr(row, field) or 0)
        totals["spend"] += Decimal(str(row.spend or 0))

    if page_keywords and (year is None or year in daily_years):
        daily_statement = (
            select(
                KeywordPerformanceDaily.keyword_text.label("keyword_text"),
                func.sum(KeywordPerformanceDaily.impressions).label("impressions"),
                func.sum(KeywordPerformanceDaily.clicks).label("clicks"),
                func.sum(KeywordPerformanceDaily.spend).label("spend"),
                func.sum(KeywordPerformanceDaily.uv).label("uv"),
                func.sum(KeywordPerformanceDaily.copies).label("copies"),
                func.sum(KeywordPerformanceDaily.adds).label("adds"),
            )
            .join(Account, KeywordPerformanceDaily.account_id == Account.id)
            .where(
                Account.project_id == project_id,
                KeywordPerformanceDaily.keyword_text.in_(page_keywords),
            )
            .group_by(KeywordPerformanceDaily.keyword_text)
        )
        if year is not None:
            daily_statement = daily_statement.where(
                func.extract("year", KeywordPerformanceDaily.report_date) == year
            )
        for performance_row in db.execute(daily_statement).all():
            merge_performance(performance_row)

    if page_keywords and (year is None or year in historical_years):
        yearly_statement = (
            select(
                MaterialKeyword.keyword_text.label("keyword_text"),
                func.sum(MaterialKeywordPerformanceYearly.impressions).label("impressions"),
                func.sum(MaterialKeywordPerformanceYearly.clicks).label("clicks"),
                func.sum(MaterialKeywordPerformanceYearly.spend).label("spend"),
                func.sum(MaterialKeywordPerformanceYearly.uv).label("uv"),
                func.sum(MaterialKeywordPerformanceYearly.copies).label("copies"),
                func.sum(MaterialKeywordPerformanceYearly.adds).label("adds"),
            )
            .join(
                MaterialKeyword,
                MaterialKeywordPerformanceYearly.material_keyword_id == MaterialKeyword.id,
            )
            .where(
                MaterialKeywordPerformanceYearly.project_id == project_id,
                MaterialKeyword.keyword_text.in_(page_keywords),
            )
            .group_by(MaterialKeyword.keyword_text)
        )
        if year is not None:
            yearly_statement = yearly_statement.where(
                MaterialKeywordPerformanceYearly.report_year == year
            )
        for performance_row in db.execute(yearly_statement).all():
            merge_performance(performance_row)

    data = []
    for row in page_rows:
        campaign_name = row.campaign_name
        keyword_text = row.keyword_text
        item = {
            "id": str(row.id),
            "campaign_name": campaign_name,
            "keyword_text": keyword_text,
            "is_blacklisted": row.is_blacklisted,
            "blacklist_reason": row.blacklist_reason,
        }
        totals = performance.get(keyword_text)
        if not totals:
            data.append({
                **item,
                "impressions": None,
                "clicks": None,
                "spend": None,
                "uv": None,
                "copies": None,
                "adds": None,
                "cpc": None,
                "uv_cost": None,
                "copy_cost": None,
                "add_cost": None,
            })
            continue
        cpc = safe_divide(totals["spend"], totals["clicks"])
        uv_cost = safe_divide(totals["spend"], totals["uv"])
        copy_cost = safe_divide(totals["spend"], totals["copies"])
        add_cost = safe_divide(totals["spend"], totals["adds"])
        data.append({
            **item,
            **totals,
            "spend": f"{totals['spend']:.2f}",
            "cpc": None if cpc is None else f"{cpc:.2f}",
            "uv_cost": None if uv_cost is None else f"{uv_cost:.2f}",
            "copy_cost": None if copy_cost is None else f"{copy_cost:.2f}",
            "add_cost": None if add_cost is None else f"{add_cost:.2f}",
        })
    return envelope(request, {
        "items": data,
        "total": total,
        "page": page,
        "page_size": page_size,
        "blacklisted_only": blacklisted_only,
        "selected_year": year,
        "available_years": available_years,
    })


@router.get("/projects/{project_id}/material-keywords/facets")
def list_material_keyword_facets(
    project_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    _: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    campaign_names = [
        value
        for value in db.scalars(
            select(MaterialKeyword.campaign_name)
            .where(MaterialKeyword.project_id == project_id)
            .distinct()
            .order_by(MaterialKeyword.campaign_name)
        ).all()
        if value
    ]
    return envelope(request, {"campaign_names": campaign_names})


@router.patch("/projects/{project_id}/material-keywords/{keyword_id}/blacklist")
def update_material_keyword_blacklist(
    project_id: uuid.UUID,
    keyword_id: uuid.UUID,
    payload: KeywordBlacklistUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    keyword = db.scalar(select(MaterialKeyword).where(
        MaterialKeyword.id == keyword_id,
        MaterialKeyword.project_id == project_id,
    ))
    if keyword is None:
        raise HTTPException(status_code=404, detail="关键词不存在")
    # Only manual blacklist placeholders are disposable. Tracking keywords are
    # also versionless, but they are durable material-center facts.
    if (
        not payload.blacklisted
        and keyword.material_version_id is None
        and keyword.campaign_name == "黑名单"
    ):
        keyword_text = keyword.keyword_text
        db.delete(keyword)
        add_audit(
            db,
            project_id,
            actor,
            "material_keyword.blacklist.placeholder.delete",
            "material_keyword",
            "移除手工黑名单关键词占位",
            str(keyword_id),
            {"keyword": keyword_text},
        )
        db.commit()
        return envelope(request, {
            "id": str(keyword_id),
            "deleted": True,
            "is_blacklisted": False,
            "blacklist_reason": None,
        })
    keyword.is_blacklisted = payload.blacklisted
    keyword.blacklist_reason = (
        payload.reason or "人工加入黑名单" if payload.blacklisted else None
    )
    keyword.blacklisted_at = datetime.now(UTC) if payload.blacklisted else None
    keyword.blacklisted_by = actor.username if payload.blacklisted else None
    add_audit(
        db,
        project_id,
        actor,
        "material_keyword.blacklist.update",
        "material_keyword",
        "关键词加入黑名单" if payload.blacklisted else "关键词移出黑名单",
        str(keyword.id),
        {"keyword": keyword.keyword_text, "reason": keyword.blacklist_reason},
    )
    db.commit()
    return envelope(request, {
        "id": str(keyword.id),
        "deleted": False,
        "is_blacklisted": keyword.is_blacklisted,
        "blacklist_reason": keyword.blacklist_reason,
    })


@router.post("/projects/{project_id}/material-keywords/blacklist/bulk", status_code=201)
def create_manual_keyword_blacklist(
    project_id: uuid.UUID,
    payload: ManualKeywordBlacklistCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    normalized = {keyword.casefold(): keyword for keyword in payload.keywords}
    existing_rows = db.scalars(
        select(MaterialKeyword).where(
            MaterialKeyword.project_id == project_id,
            func.lower(MaterialKeyword.keyword_text).in_([keyword.lower() for keyword in payload.keywords]),
        )
    ).all()
    existing = {row.keyword_text.casefold(): row for row in existing_rows}
    reason = payload.reason or "人工批量加入关键词黑名单"
    changed_at = datetime.now(UTC)
    created_count = updated_count = already_count = 0

    for key, keyword_text in normalized.items():
        row = existing.get(key)
        if row is None:
            db.add(MaterialKeyword(
                project_id=project_id,
                material_version_id=None,
                row_number=None,
                campaign_name="黑名单",
                keyword_text=keyword_text,
                keyword_utf8_encoded=encode_keyword_utf8(keyword_text),
                keyword_encoding_version=KEYWORD_ENCODING_VERSION,
                is_blacklisted=True,
                blacklist_reason=reason,
                blacklisted_at=changed_at,
                blacklisted_by=actor.username,
            ))
            created_count += 1
            continue
        if row.is_blacklisted:
            already_count += 1
            continue
        row.is_blacklisted = True
        row.blacklist_reason = reason
        row.blacklisted_at = changed_at
        row.blacklisted_by = actor.username
        updated_count += 1

    add_audit(
        db,
        project_id,
        actor,
        "material_keyword.blacklist.bulk_create",
        "material_keyword",
        "批量添加关键词黑名单",
        details={
            "input_count": len(normalized),
            "created_count": created_count,
            "updated_count": updated_count,
            "already_count": already_count,
            "reason": reason,
            "sample": list(normalized.values())[:20],
        },
    )
    db.commit()
    return envelope(request, {
        "input_count": len(normalized),
        "created_count": created_count,
        "updated_count": updated_count,
        "already_count": already_count,
    })


def load_creative_pool(db: Session, project_id: uuid.UUID) -> tuple[list[CreativeSegment], list[CreativeCombination], set[str]]:
    segments = db.scalars(
        select(CreativeSegment)
        .where(CreativeSegment.project_id == project_id)
        .order_by(CreativeSegment.segment_type, CreativeSegment.created_at)
    ).all()
    combinations = db.scalars(
        select(CreativeCombination).where(CreativeCombination.project_id == project_id)
    ).all()
    active_ids = {row.id for row in segments if not row.is_blacklisted}
    active_blacklisted_hashes = {
        row.combination_hash
        for row in combinations
        if row.is_blacklisted
        and row.title_segment_id in active_ids
        and row.description1_segment_id in active_ids
        and (row.description2_segment_id is None or row.description2_segment_id in active_ids)
    }
    return segments, combinations, active_blacklisted_hashes


def serialize_creative_combination(row: CreativeCombination, segment_map: dict[uuid.UUID, CreativeSegment]) -> dict:
    return {
        "id": str(row.id),
        "combination_hash": row.combination_hash,
        "title": segment_map[row.title_segment_id].content,
        "description1": segment_map[row.description1_segment_id].content,
        "description2": segment_map[row.description2_segment_id].content if row.description2_segment_id else "",
        "is_blacklisted": row.is_blacklisted,
        "rejection_count": row.rejection_count,
        "blacklist_reason": row.blacklist_reason,
        "blacklisted_at": row.blacklisted_at,
    }


@router.get("/projects/{project_id}/creative-center")
def get_creative_center(
    project_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    _: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    segments, combinations, active_blacklisted_hashes = load_creative_pool(db, project_id)
    summary = creative_pool_summary(segments, active_blacklisted_hashes)
    segment_map = {row.id: row for row in segments}
    grouped = {
        segment_type: [
            {
                "id": str(row.id),
                "content": row.content,
                "is_blacklisted": row.is_blacklisted,
                "rejection_count": row.rejection_count,
                "blacklist_reason": row.blacklist_reason,
                "created_at": row.created_at,
            }
            for row in segments
            if row.segment_type == segment_type
        ][:500]
        for segment_type in ("title", "description1", "description2")
    }
    tracked_combinations = [
        serialize_creative_combination(row, segment_map)
        for row in sorted(combinations, key=lambda item: (not item.is_blacklisted, -item.rejection_count, item.created_at))
        if row.is_blacklisted or row.rejection_count > 0
    ][:200]
    assignment_counts = {
        status: count
        for status, count in db.execute(
            select(CreativeAssignment.status, func.count())
            .where(CreativeAssignment.project_id == project_id)
            .group_by(CreativeAssignment.status)
        ).all()
    }
    return envelope(request, {
        **summary,
        "registered_combination_count": len(combinations),
        "creative_count_per_account": CREATIVE_COUNT_PER_ACCOUNT,
        "second_hop_rejection_threshold": SECOND_HOP_REJECTION_THRESHOLD,
        "segment_rejection_threshold": CREATIVE_SEGMENT_REJECTION_THRESHOLD,
        "segments": grouped,
        "tracked_combinations": tracked_combinations,
        "assignment_counts": assignment_counts,
    })


@router.post("/projects/{project_id}/creative-segments/bulk", status_code=201)
def create_creative_segments(
    project_id: uuid.UUID,
    payload: CreativeSegmentBulkCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    existing_rows = db.scalars(
        select(CreativeSegment).where(
            CreativeSegment.project_id == project_id,
            CreativeSegment.segment_type == payload.segment_type,
            func.lower(CreativeSegment.content).in_([value.lower() for value in payload.contents]),
        )
    ).all()
    existing = {row.content.casefold() for row in existing_rows}
    created_count = 0
    for content in payload.contents:
        if content.casefold() in existing:
            continue
        db.add(CreativeSegment(
            project_id=project_id,
            segment_type=payload.segment_type,
            content=content,
            created_by=actor.username,
        ))
        created_count += 1
    add_audit(
        db,
        project_id,
        actor,
        "creative_segment.bulk_create",
        "creative_segment",
        "批量添加创意分段",
        details={
            "segment_type": payload.segment_type,
            "input_count": len(payload.contents),
            "created_count": created_count,
            "already_count": len(payload.contents) - created_count,
        },
    )
    db.commit()
    return envelope(request, {
        "input_count": len(payload.contents),
        "created_count": created_count,
        "already_count": len(payload.contents) - created_count,
    })


@router.patch("/projects/{project_id}/creative-segments/{segment_id}/blacklist")
def update_creative_segment_blacklist(
    project_id: uuid.UUID,
    segment_id: uuid.UUID,
    payload: CreativeBlacklistUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    row = db.scalar(select(CreativeSegment).where(
        CreativeSegment.project_id == project_id,
        CreativeSegment.id == segment_id,
    ))
    if row is None:
        raise HTTPException(status_code=404, detail="创意分段不存在")
    if not payload.blacklisted and row.rejection_count >= CREATIVE_SEGMENT_REJECTION_THRESHOLD:
        raise HTTPException(
            status_code=409,
            detail=f"该创意原料累计拒审已达到{CREATIVE_SEGMENT_REJECTION_THRESHOLD}次，不能恢复使用",
        )
    row.is_blacklisted = payload.blacklisted
    row.blacklist_reason = payload.reason or ("人工停用" if payload.blacklisted else None)
    add_audit(
        db,
        project_id,
        actor,
        "creative_segment.blacklist.update",
        "creative_segment",
        "停用创意分段" if payload.blacklisted else "恢复创意分段",
        str(row.id),
        {"segment_type": row.segment_type, "content": row.content, "reason": row.blacklist_reason},
    )
    db.commit()
    return envelope(request, {"id": str(row.id), "is_blacklisted": row.is_blacklisted})


@router.post("/projects/{project_id}/creative-combinations/preview")
def preview_creative_combinations(
    project_id: uuid.UUID,
    payload: CreativeCombinationPreviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    _: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    segments, _, active_blacklisted_hashes = load_creative_pool(db, project_id)
    rows = select_random_creative_combinations(
        segments,
        active_blacklisted_hashes,
        seed=f"{project_id}:{payload.seed}",
        limit=payload.limit,
    )
    return envelope(request, {
        "requested_count": payload.limit,
        "selected_count": len(rows),
        "items": [
            {
                "combination_hash": row.combination_hash,
                "title": row.title,
                "description1": row.description1,
                "description2": row.description2,
            }
            for row in rows
        ],
    })


@router.patch("/projects/{project_id}/creative-assignments/{assignment_id}/bind")
def bind_creative_assignment(
    project_id: uuid.UUID,
    assignment_id: uuid.UUID,
    payload: CreativeAssignmentBind,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    row = db.scalar(select(CreativeAssignment).where(
        CreativeAssignment.project_id == project_id,
        CreativeAssignment.id == assignment_id,
    ))
    if row is None:
        raise HTTPException(status_code=404, detail="创意投放记录不存在")
    row.baidu_creative_id = payload.baidu_creative_id
    row.creative_payload = payload.creative_payload
    row.status = "submitted"
    row.submitted_at = datetime.now(UTC)
    add_audit(
        db,
        project_id,
        actor,
        "creative_assignment.bind",
        "creative_assignment",
        "登记百度创意ID",
        str(row.id),
        {"baidu_creative_id": payload.baidu_creative_id},
    )
    db.commit()
    return envelope(request, {"id": str(row.id), "status": row.status})


@router.post("/projects/{project_id}/creative-reviews/sync", status_code=202)
def queue_creative_review_sync(
    project_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    task = BackgroundTask(
        project_id=project_id,
        task_type="creative_review_sync",
        current_node="queued",
        progress=0,
    )
    db.add(task)
    add_audit(
        db,
        project_id,
        actor,
        "creative_review.sync.queue",
        "background_task",
        "提交创意审核状态同步",
        str(task.id),
    )
    db.commit()
    db.refresh(task)
    from .worker import sync_project_creative_reviews
    sync_project_creative_reviews.delay(str(project_id), str(task.id))
    return envelope(request, {"task_id": str(task.id), "status": "queued"})


def load_keyword_tier_rules(db: Session, project_id: uuid.UUID) -> KeywordTierRuleConfig:
    row = db.scalar(select(ProjectPreference).where(
        ProjectPreference.project_id == project_id,
        ProjectPreference.key == KEYWORD_TIER_PREFERENCE_KEY,
    ))
    return KeywordTierRuleConfig.model_validate(row.value if row else {})


def keyword_tier_performance_scope(project_id: uuid.UUID):
    daily_scope = (
        select(
            KeywordPerformanceDaily.keyword_text.label("keyword_text"),
            literal(1).label("performance_rows"),
            KeywordPerformanceDaily.spend.label("spend"),
            KeywordPerformanceDaily.copies.label("copies"),
            KeywordPerformanceDaily.adds.label("adds"),
        )
        .join(Account, KeywordPerformanceDaily.account_id == Account.id)
        .where(Account.project_id == project_id)
    )
    yearly_scope = (
        select(
            MaterialKeyword.keyword_text.label("keyword_text"),
            literal(1).label("performance_rows"),
            MaterialKeywordPerformanceYearly.spend.label("spend"),
            MaterialKeywordPerformanceYearly.copies.label("copies"),
            MaterialKeywordPerformanceYearly.adds.label("adds"),
        )
        .join(
            MaterialKeyword,
            MaterialKeywordPerformanceYearly.material_keyword_id == MaterialKeyword.id,
        )
        .where(MaterialKeywordPerformanceYearly.project_id == project_id)
    )
    combined = union_all(daily_scope, yearly_scope).subquery()
    return (
        select(
            combined.c.keyword_text,
            func.sum(combined.c.performance_rows).label("performance_rows"),
            func.sum(combined.c.spend).label("spend"),
            func.sum(combined.c.copies).label("copies"),
            func.sum(combined.c.adds).label("adds"),
        )
        .group_by(combined.c.keyword_text)
        .subquery()
    )


@router.post("/projects/{project_id}/keyword-tier-rules/dry-run")
def dry_run_keyword_tier_rules(
    project_id: uuid.UUID,
    request: Request,
    payload: KeywordTierDryRunRequest | None = None,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    rules = payload.rules if payload and payload.rules else load_keyword_tier_rules(db, project_id)
    performance_scope = keyword_tier_performance_scope(project_id)
    rows = db.execute(
        select(
            MaterialKeyword.keyword_text,
            MaterialKeyword.campaign_name,
            MaterialKeyword.is_blacklisted,
            performance_scope.c.performance_rows,
            performance_scope.c.spend,
            performance_scope.c.copies,
            performance_scope.c.adds,
        )
        .outerjoin(
            performance_scope,
            performance_scope.c.keyword_text == MaterialKeyword.keyword_text,
        )
        .where(MaterialKeyword.project_id == project_id)
    ).all()

    current_counts: Counter[str] = Counter()
    evaluated_counts: Counter[str] = Counter()
    samples = []
    change_count = 0
    upgrade_count = 0
    downgrade_count = 0
    blacklisted_count = 0
    for row in rows:
        current_counts[row.campaign_name] += 1
        if row.is_blacklisted:
            blacklisted_count += 1
            continue
        if row.performance_rows:
            evaluated = classify_keyword(
                has_performance=True,
                spend=row.spend,
                copies=row.copies,
                adds=row.adds,
                rules=rules,
            )
        else:
            # Missing synchronized history is not evidence of poor performance.
            evaluated = row.campaign_name
        evaluated_counts[evaluated] += 1
        if evaluated != row.campaign_name:
            change_count += 1
            current_rank = TIER_RANK.get(row.campaign_name)
            evaluated_rank = TIER_RANK.get(evaluated)
            if current_rank is not None and evaluated_rank is not None:
                if evaluated_rank > current_rank:
                    upgrade_count += 1
                elif evaluated_rank < current_rank:
                    downgrade_count += 1
            if len(samples) < 20:
                samples.append({
                    "keyword": row.keyword_text,
                    "from_plan": row.campaign_name,
                    "evaluated_plan": evaluated,
                })

    result = {
        "total": len(rows),
        "evaluable_total": len(rows) - blacklisted_count,
        "change_count": change_count,
        "upgrade_count": upgrade_count,
        "downgrade_count": downgrade_count,
        "risk_count": evaluated_counts["成本高"] + evaluated_counts["空耗"],
        "blacklisted_count": blacklisted_count,
        "current_counts": dict(current_counts),
        "evaluated_counts": dict(evaluated_counts),
        "samples": samples,
        "rules": rules.model_dump(mode="json"),
    }
    add_audit(
        db, project_id, actor, "keyword_tiers.dry_run", "material", "试算关键词分级规则",
        details={"total": len(rows), "change_count": change_count},
    )
    db.commit()
    return envelope(request, result)


@router.post("/projects/{project_id}/keyword-tier-rules/apply-risk-blacklist")
def apply_keyword_tier_risk_blacklist(
    project_id: uuid.UUID,
    request: Request,
    payload: KeywordTierDryRunRequest | None = None,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    rules = payload.rules if payload and payload.rules else load_keyword_tier_rules(db, project_id)
    performance_scope = keyword_tier_performance_scope(project_id)
    rows = db.execute(
        select(
            MaterialKeyword,
            performance_scope.c.performance_rows,
            performance_scope.c.spend,
            performance_scope.c.copies,
            performance_scope.c.adds,
        )
        .outerjoin(
            performance_scope,
            performance_scope.c.keyword_text == MaterialKeyword.keyword_text,
        )
        .where(
            MaterialKeyword.project_id == project_id,
            MaterialKeyword.is_blacklisted.is_(False),
        )
    ).all()

    matched: Counter[str] = Counter()
    changed_at = datetime.now(UTC)
    for keyword, performance_rows, spend, copies, adds in rows:
        if not performance_rows:
            continue
        evaluated = classify_keyword(
            has_performance=True,
            spend=spend,
            copies=copies,
            adds=adds,
            rules=rules,
        )
        if evaluated not in {"成本高", "空耗"}:
            continue
        keyword.campaign_name = evaluated
        keyword.is_blacklisted = True
        keyword.blacklist_reason = f"历史累计分级命中{evaluated}，系统自动加入黑名单"
        keyword.blacklisted_at = changed_at
        keyword.blacklisted_by = actor.username
        matched[evaluated] += 1

    total = matched["成本高"] + matched["空耗"]
    add_audit(
        db,
        project_id,
        actor,
        "keyword_tiers.risk_blacklist.apply",
        "material_keyword",
        "执行分级并将成本高、空耗关键词加入黑名单",
        details={
            "blacklisted_count": total,
            "cost_high_count": matched["成本高"],
            "empty_spend_count": matched["空耗"],
            "rules": rules.model_dump(mode="json"),
        },
    )
    db.commit()
    return envelope(request, {
        "blacklisted_count": total,
        "cost_high_count": matched["成本高"],
        "empty_spend_count": matched["空耗"],
    })


@router.post("/projects/{project_id}/keyword-tier-rules/apply")
def apply_keyword_tier_adjustments(
    project_id: uuid.UUID,
    request: Request,
    payload: KeywordTierDryRunRequest | None = None,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    """Apply cumulative tier changes locally; no Baidu write is performed."""
    require_project(db, project_id)
    rules = payload.rules if payload and payload.rules else load_keyword_tier_rules(db, project_id)
    performance_scope = keyword_tier_performance_scope(project_id)
    rows = db.execute(
        select(
            MaterialKeyword,
            performance_scope.c.performance_rows,
            performance_scope.c.spend,
            performance_scope.c.copies,
            performance_scope.c.adds,
        )
        .outerjoin(
            performance_scope,
            performance_scope.c.keyword_text == MaterialKeyword.keyword_text,
        )
        .where(
            MaterialKeyword.project_id == project_id,
            MaterialKeyword.is_blacklisted.is_(False),
        )
    ).all()

    changed_at = datetime.now(UTC)
    changed_count = upgrade_count = downgrade_count = blacklisted_count = 0
    evaluated_counts: Counter[str] = Counter()
    samples = []
    for keyword, performance_rows, spend, copies, adds in rows:
        if not performance_rows:
            continue
        evaluated = classify_keyword(
            has_performance=True,
            spend=spend,
            copies=copies,
            adds=adds,
            rules=rules,
        )
        evaluated_counts[evaluated] += 1
        previous = keyword.campaign_name
        if evaluated in {"成本高", "空耗"}:
            keyword.campaign_name = evaluated
            keyword.is_blacklisted = True
            keyword.blacklist_reason = f"历史累计分级命中{evaluated}，系统自动加入黑名单"
            keyword.blacklisted_at = changed_at
            keyword.blacklisted_by = actor.username
            blacklisted_count += 1
        elif evaluated != previous:
            keyword.campaign_name = evaluated
        else:
            continue

        changed_count += 1
        current_rank = TIER_RANK.get(previous)
        evaluated_rank = TIER_RANK.get(evaluated)
        if current_rank is not None and evaluated_rank is not None:
            if evaluated_rank > current_rank:
                upgrade_count += 1
            elif evaluated_rank < current_rank:
                downgrade_count += 1
        if len(samples) < 20:
            samples.append(
                {"keyword": keyword.keyword_text, "from_plan": previous, "to_plan": evaluated}
            )

    result = {
        "evaluated_count": sum(evaluated_counts.values()),
        "changed_count": changed_count,
        "upgrade_count": upgrade_count,
        "downgrade_count": downgrade_count,
        "blacklisted_count": blacklisted_count,
        "cost_high_count": evaluated_counts["成本高"],
        "empty_spend_count": evaluated_counts["空耗"],
        "evaluated_counts": dict(evaluated_counts),
        "samples": samples,
    }
    add_audit(
        db,
        project_id,
        actor,
        "keyword_tiers.apply",
        "material_keyword",
        "按历史累计数据自动调整关键词计划级别",
        details={**result, "rules": rules.model_dump(mode="json")},
    )
    db.commit()
    return envelope(request, result)


@router.post("/projects/{project_id}/materials/import", status_code=201)
async def import_material(
    project_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="请上传 xlsx 或 xlsm 文件")
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件不能超过 20MB")
    preview, material_rows = parse_material_workbook(file.filename, content)
    if preview.invalid_count:
        return envelope(request, {"saved": False, "preview": preview.model_dump()}, status="validation_error")

    existing_keywords = set(db.scalars(
        select(MaterialKeyword.keyword_text)
        .where(MaterialKeyword.project_id == project_id)
    ).all())
    preview, material_rows = filter_new_material_rows(preview, material_rows, existing_keywords)

    material = db.scalar(select(Material).where(
        Material.project_id == project_id,
        Material.name == PROJECT_MATERIAL_LIBRARY_NAME,
    ))
    if not material_rows:
        add_audit(
            db, project_id, actor, "material.import", "material", "物料追加完成，无新增数据",
            None if material is None else str(material.id), {
                "added_count": 0,
                "skip_count": preview.skip_count,
                "sha256": preview.sha256,
            },
        )
        db.commit()
        return envelope(request, {
            "saved": True,
            "material_id": None if material is None else str(material.id),
            "version": 0 if material is None else material.current_version,
            "preview": preview.model_dump(),
        })

    if material:
        material.current_version += 1
    else:
        material = Material(
            project_id=project_id,
            name=PROJECT_MATERIAL_LIBRARY_NAME,
            current_version=1,
        )
        db.add(material)
        db.flush()
    digest = hashlib.sha256(content).hexdigest()
    directory = settings.storage_root / "imports" / str(project_id)
    directory.mkdir(parents=True, exist_ok=True)
    stored_path = directory / f"{material.id}-v{material.current_version}-{digest[:12]}.xlsx"
    stored_path.write_bytes(content)
    version = MaterialVersion(
        material_id=material.id,
        version=material.current_version,
        file_path=str(stored_path),
        sha256=digest,
        row_count=0,
        summary={},
        created_by=actor.username,
    )
    db.add(version)
    db.flush()
    batch_size = 5000
    inserted_count = 0
    for offset in range(0, len(material_rows), batch_size):
        batch = [
            {"project_id": project_id, "material_version_id": version.id, **row}
            for row in material_rows[offset:offset + batch_size]
        ]
        statement = (
            pg_insert(MaterialKeyword)
            .values(batch)
            .on_conflict_do_nothing(
                index_elements=[
                    MaterialKeyword.project_id,
                    MaterialKeyword.keyword_text,
                ]
            )
            .returning(MaterialKeyword.id)
        )
        inserted_count += len(db.scalars(statement).all())
    if inserted_count != len(material_rows):
        preview = preview.model_copy(update={
            "valid_count": inserted_count,
            "create_count": inserted_count,
            "skip_count": preview.skip_count + len(material_rows) - inserted_count,
        })
    persisted_summary = preview.model_dump(mode="json")
    persisted_summary.pop("filename", None)
    version.row_count = inserted_count
    version.summary = persisted_summary
    add_audit(
        db, project_id, actor, "material.import", "material", "追加项目公共物料",
        str(material.id), {
            "version": material.current_version,
            "sha256": digest,
            "added_count": inserted_count,
            "skip_count": preview.skip_count,
        },
    )
    db.commit()
    return envelope(request, {"saved": True, "material_id": str(material.id), "version": material.current_version, "preview": preview.model_dump()})


@router.post("/operations")
def create_operation(payload: OperationCreate, request: Request, db: Session = Depends(get_db), actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR))):
    operation = preflight_operation(db, payload, actor.username)
    return envelope(request, {"id": str(operation.id), "status": operation.status.value, "preflight_result": operation.preflight_result})


def create_keyword_allocation(payload: KeywordPlanRequest, db: Session) -> tuple[dict, dict[int, Account]]:
    if not db.get(Project, payload.project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    accounts = db.scalars(select(Account).where(
        Account.project_id == payload.project_id,
        Account.baidu_account_id.in_(payload.account_ids),
    )).all()
    account_map = {account.baidu_account_id: account for account in accounts}
    missing = sorted(set(payload.account_ids) - set(account_map))
    if missing:
        raise HTTPException(status_code=400, detail=f"目标账户不存在：{', '.join(map(str, missing))}")
    try:
        plan = build_keyword_plan(
            account_ids=payload.account_ids,
            campaign_name=payload.campaign_name,
            keywords=[TieredKeyword(text=item.text, tier=item.tier) for item in payload.keywords],
            config=KeywordPlanConfig(**payload.config.model_dump()),
        )
    except KeywordPlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return plan, account_map


@router.post("/keyword-plans/preview")
def preview_keyword_plan(payload: KeywordPlanRequest, request: Request, db: Session = Depends(get_db), _: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR))):
    plan, _ = create_keyword_allocation(payload, db)
    return envelope(request, plan)


@router.post("/keyword-plans")
def submit_keyword_plan(payload: KeywordPlanRequest, request: Request, db: Session = Depends(get_db), actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR))):
    plan, account_map = create_keyword_allocation(payload, db)
    previous_plan = None
    if payload.config.batch_number > 1:
        candidates = db.scalars(select(KeywordDeploymentPlan).where(
            KeywordDeploymentPlan.project_id == payload.project_id,
            KeywordDeploymentPlan.campaign_name == payload.campaign_name,
        ).order_by(KeywordDeploymentPlan.created_at.desc())).all()
        previous_batch = payload.config.batch_number - 1
        previous_plan = next((
            candidate for candidate in candidates
            if candidate.input_summary.get("config", {}).get("batch_number") == previous_batch
        ), None)
        if previous_plan is None:
            raise HTTPException(status_code=409, detail=f"请先保存第 {previous_batch} 批，再提交第 {payload.config.batch_number} 批")
    stored = KeywordDeploymentPlan(
        project_id=payload.project_id,
        campaign_name=payload.campaign_name,
        input_summary={"account_count": plan["account_count"], "source_counts": plan["source_counts"], "config": plan["config"]},
        allocation_plan=plan,
        created_by=actor.username,
    )
    db.add(stored)
    db.commit()
    db.refresh(stored)
    operations = []
    for account_plan in plan["accounts"]:
        account = account_map[account_plan["account_id"]]
        operation_type = "keyword_tier_deployment" if plan["batch"]["mode"] == "initial" else "keyword_tier_def_rotation"
        operation = preflight_operation(db, OperationCreate(
            operation_type=operation_type,
            target_account_id=account.baidu_account_id,
            idempotency_key=f"keyword-plan:{stored.id}:{account.baidu_account_id}",
            payload={
                "keyword_plan_id": str(stored.id),
                "previous_keyword_plan_id": str(previous_plan.id) if previous_plan else None,
                "batch_number": plan["batch"]["number"],
                "batch_mode": plan["batch"]["mode"],
                "replace_unit_prefix": f"{payload.campaign_name}_DEF_补充_" if previous_plan else None,
                "manager_login_name": account.manager_login_name,
                "target_login_name": account.login_name,
                "campaign_name": payload.campaign_name,
                "units": account_plan["units"],
            },
        ), actor.username)
        operations.append({"operation_id": str(operation.id), "target_account_id": account.baidu_account_id, "status": operation.status.value})
    return envelope(request, {"plan_id": str(stored.id), "strategy": plan["strategy"], "operations": operations})


def serialize_ad_build_access(row: ProjectAdBuildAccess) -> dict:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "username": row.username,
        "display_name": row.display_name,
        "operator_name": row.operator_name,
        "can_build_ads": row.can_build_ads,
        "is_active": row.is_active,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at,
    }


def actor_ad_build_access(
    db: Session,
    project_id: uuid.UUID,
    actor: Actor,
    *,
    require_enabled: bool,
) -> ProjectAdBuildAccess | None:
    access = db.scalar(select(ProjectAdBuildAccess).where(
        ProjectAdBuildAccess.project_id == project_id,
        ProjectAdBuildAccess.username == actor.username,
    ))
    if access:
        if require_enabled and (not access.is_active or not access.can_build_ads):
            raise HTTPException(status_code=403, detail="当前用户的投放搭建权限已停用")
        return access
    if is_system_owner(actor):
        return None
    if require_enabled:
        raise HTTPException(status_code=403, detail="当前用户尚未配置投放账户归属权限")
    return None


def create_ad_build_preview(
    payload: AdBuildPreviewRequest,
    db: Session,
    actor: Actor,
) -> tuple[dict, dict[int, Account]]:
    project = db.get(Project, payload.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    unknown_region_ids = sorted(set(payload.region_target) - baidu_region_ids())
    if unknown_region_ids:
        raise HTTPException(
            status_code=422,
            detail=f"包含未识别的百度省市地域ID：{unknown_region_ids[:5]}",
        )
    all_accounts = db.scalars(
        select(Account)
        .where(Account.project_id == payload.project_id)
        .order_by(Account.baidu_account_id)
    ).all()
    permission_access = require_project_permission(
        db, payload.project_id, actor, "auto_launch", "manage"
    )
    operator_names = ad_build_operator_names(permission_access)
    operator_scope = "、".join(operator_names) if operator_names is not None else None
    if operator_names is not None and payload.selection_mode == "specified_accounts":
        normalized = {value.strip() for value in payload.account_selectors if value.strip()}
        forbidden = [account for account in all_accounts if account.operator_name not in operator_names and (
            account.login_name in normalized or str(account.baidu_account_id) in normalized
        )]
        if forbidden:
            raise HTTPException(
                status_code=403,
                detail=f"不能使用数据范围外的账户；当前允许运营归属“{operator_scope}”",
            )
    accounts = all_accounts if operator_names is None else [
        account for account in all_accounts if account.operator_name in operator_names
    ]
    account_statuses = load_account_statuses(db, payload.project_id)
    account_map = {row.baidu_account_id: row for row in accounts}
    material_rows = db.scalars(
        select(MaterialKeyword)
        .where(
            MaterialKeyword.project_id == payload.project_id,
            MaterialKeyword.is_blacklisted.is_(False),
        )
        .order_by(MaterialKeyword.campaign_name, MaterialKeyword.keyword_text)
    ).all()
    material_snapshot = [
        {
            "id": str(row.id),
            "campaign_name": row.campaign_name,
            "keyword_text": row.keyword_text,
            "keyword_utf8_encoded": row.keyword_utf8_encoded,
        }
        for row in material_rows
    ]
    material_fingerprint = hashlib.sha256(
        json.dumps(material_snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    campaign_counts: dict[str, int] = {}
    for item in material_snapshot:
        name = str(item["campaign_name"] or "未命名计划")
        campaign_counts[name] = campaign_counts.get(name, 0) + 1
    material_summary = {
        "fingerprint": material_fingerprint,
        "campaign_count": len(campaign_counts),
        "campaigns": [
            {"name": name, "keyword_count": count, "unit_count": (count + 4999) // 5000}
            for name, count in campaign_counts.items()
        ],
    }
    creative_segments, _, creative_blacklisted_hashes = load_creative_pool(db, payload.project_id)
    creative_summary = creative_pool_summary(creative_segments, creative_blacklisted_hashes)
    plan = build_ad_build_preview(
        accounts,
        payload,
        material_keyword_count=len(material_snapshot),
        writes_enabled=settings.baidu_writes_enabled,
        creative_summary=creative_summary,
        material_summary=material_summary,
        account_statuses=account_statuses,
    )
    try:
        plan["ocpc_project_names"] = [
            build_ocpc_project_name(project.name, batch["scheduled_at"])
            for batch in plan["batches"]
        ]
    except ValueError as exc:
        plan["errors"] = list(dict.fromkeys([*plan["errors"], str(exc)]))
        plan["can_submit"] = False
    plan["material_snapshot"] = material_snapshot
    plan["build_rule"] = ad_build_rule_summary()
    negative_keywords = project_negative_keyword_snapshot(db, payload.project_id)
    negative_keyword_fingerprint = hashlib.sha256(
        json.dumps(
            negative_keywords,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    plan["negative_keywords"] = {
        "phrase_count": len(negative_keywords["phrase"]),
        "exact_count": len(negative_keywords["exact"]),
        "runtime_source": "project_postgresql",
    }
    plan["negative_keyword_fingerprint"] = negative_keyword_fingerprint
    plan["access_scope"] = {
        "username": actor.username,
        "restricted": operator_scope is not None,
        "operator_name": operator_scope,
        "eligible_account_count": len(accounts),
    }
    return plan, account_map


def _require_explicit_account_scope(
    db: Session,
    project_id: uuid.UUID,
    account_ids: list[uuid.UUID] | None,
    access,
) -> None:
    if not account_ids or access.operator_names is None:
        return
    rows = db.scalars(select(Account).where(
        Account.project_id == project_id,
        Account.id.in_(account_ids),
    )).all()
    for account in rows:
        require_account_scope(access, account)
@router.get("/projects/{project_id}/ad-build-access/me")
def get_my_ad_build_access(
    project_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    access = project_access(db, project_id, actor)
    build_operator_names = ad_build_operator_names(access)
    member = access.member
    account_filters = [Account.project_id == project_id]
    if build_operator_names is not None:
        account_filters.append(Account.operator_name.in_(build_operator_names))
    operator_scope = (
        "、".join(build_operator_names)
        if build_operator_names is not None
        else None
    )
    return envelope(request, {
        "username": actor.username,
        "display_name": (
            "系统管理员"
            if access.is_owner
            else (member.display_name if member else actor.username)
        ),
        # Keep operator_name for the legacy UI while exposing the full scope.
        "operator_name": operator_scope,
        "operator_names": (
            list(build_operator_names)
            if build_operator_names is not None
            else None
        ),
        "data_scope": access.data_scope,
        "can_build_ads": access.permissions["auto_launch"] == "manage",
        "is_active": True if member is None else member.is_active,
        "restricted": build_operator_names is not None,
        "eligible_account_count": db.scalar(
            select(func.count()).select_from(Account).where(*account_filters)
        ) or 0,
    })


@router.get("/projects/{project_id}/ad-build-access/users")
def list_ad_build_access_users(
    project_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    _: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    rows = db.scalars(select(ProjectAdBuildAccess).where(
        ProjectAdBuildAccess.project_id == project_id,
    ).order_by(ProjectAdBuildAccess.operator_name)).all()
    total_accounts = db.scalar(
        select(func.count()).select_from(Account).where(Account.project_id == project_id)
    ) or 0
    return envelope(request, [{
        "username": "admin",
        "display_name": "管理员",
        "operator_name": None,
        "can_build_ads": True,
        "is_active": True,
        "restricted": False,
        "eligible_account_count": total_accounts,
    }, *[{
        **serialize_ad_build_access(row),
        "eligible_account_count": db.scalar(
            select(func.count()).select_from(Account).where(
                Account.project_id == project_id,
                Account.operator_name == row.operator_name,
            )
        ) or 0,
    } for row in rows]])


@router.patch("/projects/{project_id}/ad-build-access/users/{username}")
def update_ad_build_access_user(
    project_id: uuid.UUID,
    username: str,
    payload: AdBuildAccessUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    row = db.scalar(select(ProjectAdBuildAccess).where(
        ProjectAdBuildAccess.project_id == project_id,
        ProjectAdBuildAccess.username == username,
    ))
    if not row:
        raise HTTPException(status_code=404, detail="投放权限账户不存在")
    row.can_build_ads = payload.can_build_ads
    row.is_active = payload.is_active
    row.permissions = {
        **normalize_permissions(row.permissions),
        "auto_launch": "manage" if payload.can_build_ads else "view",
    }
    row.version += 1
    row.updated_by = actor.username
    add_audit(
        db,
        project_id,
        actor,
        "ad_build_access.update",
        "project_members",
        f"更新{row.display_name}的投放账户权限",
        str(row.id),
        {
            "username": row.username,
            "operator_name": row.operator_name,
            "can_build_ads": row.can_build_ads,
            "is_active": row.is_active,
        },
    )
    db.commit()
    db.refresh(row)
    return envelope(request, serialize_ad_build_access(row))


def serialize_project_negative_keyword(row: ProjectNegativeKeyword) -> dict:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "match_type": row.match_type,
        "keyword_text": row.keyword_text,
        "source": row.source,
        "reference_template_version_id": (
            str(row.reference_template_version_id) if row.reference_template_version_id else None
        ),
        "created_by": row.created_by,
        "created_at": row.created_at,
    }


@router.get("/projects/{project_id}/negative-keywords")
def list_project_negative_keywords(
    project_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    _: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    rows = db.scalars(
        select(ProjectNegativeKeyword)
        .where(ProjectNegativeKeyword.project_id == project_id)
        .order_by(
            ProjectNegativeKeyword.match_type,
            ProjectNegativeKeyword.created_at,
            ProjectNegativeKeyword.id,
        )
    ).all()
    counts = Counter(row.match_type for row in rows)
    return envelope(request, {
        "items": [serialize_project_negative_keyword(row) for row in rows],
        "counts": {"phrase": counts["phrase"], "exact": counts["exact"]},
        "total": len(rows),
        "runtime_source": "project_postgresql",
    })


@router.post("/projects/{project_id}/negative-keywords/bulk", status_code=201)
def add_project_negative_keywords(
    project_id: uuid.UUID,
    payload: NegativeKeywordBulkCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    rows = [
        {
            "id": uuid.uuid4(),
            "project_id": project_id,
            "match_type": payload.match_type,
            "keyword_text": keyword,
            "normalized_keyword_text": normalized_negative_keyword(keyword),
            "source": "manual",
            "reference_template_version_id": None,
            "created_by": actor.username,
        }
        for keyword in payload.keywords
    ]
    statement = (
        pg_insert(ProjectNegativeKeyword)
        .values(rows)
        .on_conflict_do_nothing(
            index_elements=["project_id", "match_type", "normalized_keyword_text"]
        )
        .returning(ProjectNegativeKeyword.id)
    )
    created_ids = list(db.scalars(statement))
    add_audit(
        db,
        project_id,
        actor,
        "negative_keyword.bulk_add",
        "project_negative_keyword",
        f"添加{len(created_ids)}个项目否词",
        details={
            "match_type": payload.match_type,
            "input_count": len(payload.keywords),
            "created_count": len(created_ids),
        },
    )
    db.commit()
    return envelope(request, {
        "input_count": len(payload.keywords),
        "created_count": len(created_ids),
        "duplicate_count": len(payload.keywords) - len(created_ids),
    })


@router.delete("/projects/{project_id}/negative-keywords/{negative_keyword_id}")
def delete_project_negative_keyword(
    project_id: uuid.UUID,
    negative_keyword_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    row = db.get(ProjectNegativeKeyword, negative_keyword_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="否词不存在")
    details = {
        "match_type": row.match_type,
        "keyword_text": row.keyword_text,
        "source": row.source,
    }
    db.delete(row)
    add_audit(
        db,
        project_id,
        actor,
        "negative_keyword.delete",
        "project_negative_keyword",
        f"删除项目否词：{row.keyword_text}",
        str(row.id),
        details,
    )
    db.commit()
    return envelope(request, {"deleted": True, **details})


def current_negative_keyword_copy_template(
    db: Session,
    project_id: uuid.UUID,
) -> tuple[ReferenceTemplateVersion, str]:
    reference_template = db.scalar(
        select(ReferenceTemplateVersion)
        .where(
            ReferenceTemplateVersion.project_id == project_id,
            ReferenceTemplateVersion.source_account_id == 86459649,
            ReferenceTemplateVersion.is_active.is_(True),
            ReferenceTemplateVersion.status == "ready",
        )
        .order_by(desc(ReferenceTemplateVersion.version), desc(ReferenceTemplateVersion.captured_at))
    )
    if reference_template is not None:
        return reference_template, "current_project"

    reference_template = db.scalar(
        select(ReferenceTemplateVersion)
        .where(
            ReferenceTemplateVersion.source_account_id == 86459649,
            ReferenceTemplateVersion.is_active.is_(True),
            ReferenceTemplateVersion.status == "ready",
        )
        .order_by(desc(ReferenceTemplateVersion.captured_at), desc(ReferenceTemplateVersion.created_at))
    )
    if reference_template is None:
        raise HTTPException(status_code=409, detail="当前没有可复制的百度 API 参考模板否词")
    return reference_template, "latest_available"


def negative_keyword_copy_preview(
    db: Session,
    project_id: uuid.UUID,
    reference_template: ReferenceTemplateVersion,
    source_scope: str,
) -> dict:
    candidates = reference_template_negative_keywords(reference_template.template_data)
    existing = set(db.execute(
        select(
            ProjectNegativeKeyword.match_type,
            ProjectNegativeKeyword.normalized_keyword_text,
        ).where(ProjectNegativeKeyword.project_id == project_id)
    ).all())
    candidate_counts = {key: len(values) for key, values in candidates.items()}
    new_counts = {
        match_type: sum(
            1 for keyword in keywords
            if (match_type, normalized_negative_keyword(keyword)) not in existing
        )
        for match_type, keywords in candidates.items()
    }
    duplicate_counts = {
        match_type: candidate_counts[match_type] - new_counts[match_type]
        for match_type in ("phrase", "exact")
    }
    source_project = db.get(Project, reference_template.project_id)
    return {
        "template_id": str(reference_template.id),
        "template_version": reference_template.version,
        "source_project_id": str(reference_template.project_id),
        "source_project_name": source_project.name if source_project else "未知项目",
        "source_scope": source_scope,
        "candidate_counts": candidate_counts,
        "candidate_total": sum(candidate_counts.values()),
        "new_counts": new_counts,
        "new_total": sum(new_counts.values()),
        "duplicate_counts": duplicate_counts,
        "duplicate_total": sum(duplicate_counts.values()),
        "fingerprint": reference_template_negative_keyword_fingerprint(reference_template),
        "runtime_source_after_copy": "project_postgresql",
    }


@router.get("/projects/{project_id}/negative-keywords/reference-template-preview")
def preview_project_negative_keywords_from_reference(
    project_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    _: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    reference_template, source_scope = current_negative_keyword_copy_template(db, project_id)
    return envelope(
        request,
        negative_keyword_copy_preview(db, project_id, reference_template, source_scope),
    )


@router.post("/projects/{project_id}/negative-keywords/sync-reference-template")
def sync_project_negative_keywords_from_reference(
    project_id: uuid.UUID,
    payload: NegativeKeywordTemplateCopy,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    reference_template, source_scope = current_negative_keyword_copy_template(db, project_id)
    preview = negative_keyword_copy_preview(db, project_id, reference_template, source_scope)
    if str(payload.template_id) != preview["template_id"] or payload.fingerprint != preview["fingerprint"]:
        raise HTTPException(status_code=409, detail="当前模板已变化，请重新预览后再复制")
    result = sync_reference_template_negative_keywords(
        db,
        project_id,
        reference_template,
        actor.username,
    )
    add_audit(
        db,
        project_id,
        actor,
        "negative_keyword.reference_template_sync",
        "project_negative_keyword",
        f"从当前模板复制{result['created_total']}个项目否词",
        str(reference_template.id),
        {**result, "source_scope": source_scope, "preview_fingerprint": preview["fingerprint"]},
    )
    db.commit()
    result["source_scope"] = source_scope
    result["duplicate_total"] = preview["duplicate_total"]
    result["snapshot"] = project_negative_keyword_snapshot(db, project_id)
    return envelope(request, result)


def serialize_reference_template(row: ReferenceTemplateVersion) -> dict:
    return {
        "id": str(row.id), "project_id": str(row.project_id), "source_account_id": row.source_account_id,
        "source_login_name": row.source_login_name, "manager_login_name": row.manager_login_name,
        "version": row.version, "status": row.status, "captured_at": row.captured_at,
        "hierarchy_counts": row.hierarchy_counts, "template_data": row.template_data,
        "analysis": row.analysis, "raw_data_path": row.raw_data_path, "raw_sha256": row.raw_sha256,
        "is_active": row.is_active, "created_by": row.created_by,
    }


@router.get("/projects/{project_id}/reference-template")
def get_reference_template(
    project_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    _: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    row = db.scalar(select(ReferenceTemplateVersion).where(
        ReferenceTemplateVersion.project_id == project_id,
        ReferenceTemplateVersion.source_account_id == 86459649,
        ReferenceTemplateVersion.is_active.is_(True),
    ).order_by(desc(ReferenceTemplateVersion.version)))
    return envelope(request, serialize_reference_template(row) if row else None)


@router.post("/projects/{project_id}/reference-template/sync", status_code=202)
def queue_reference_template_sync(
    project_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    account = db.scalar(select(Account).where(
        Account.project_id == project_id,
        Account.baidu_account_id == 86459649,
    ))
    if account is None:
        raise HTTPException(status_code=404, detail="当前项目不存在参考账户86459649")
    running = db.scalar(select(BackgroundTask).where(
        BackgroundTask.project_id == project_id,
        BackgroundTask.task_type == "reference_template_sync",
        BackgroundTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
    ))
    if running:
        return envelope(request, {"task_id": str(running.id), "status": running.status.value})
    task = BackgroundTask(project_id=project_id, task_type="reference_template_sync", current_node="queued", progress=0)
    db.add(task)
    add_audit(db, project_id, actor, "reference_template.sync.queue", "background_task", "提交参考账户86459649只读同步", str(task.id))
    db.commit()
    db.refresh(task)
    from .worker import sync_reference_account_template
    sync_reference_account_template.delay(str(task.id), str(project_id), actor.username)
    return envelope(request, {"task_id": str(task.id), "status": task.status.value})


@router.post("/ad-builds/preview")
def preview_ad_build(
    payload: AdBuildPreviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    plan, _ = create_ad_build_preview(payload, db, actor)
    return envelope(request, plan)


@router.post("/ad-builds", status_code=201)
def create_ad_build(
    payload: AdBuildCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    plan, account_map = create_ad_build_preview(payload, db, actor)
    project = require_project(db, payload.project_id)
    if payload.selection_fingerprint != plan["selection_fingerprint"] or payload.selected_account_ids != plan["selected_account_ids"]:
        raise HTTPException(status_code=409, detail="账户队列已变化，请重新预览后再提交")
    if payload.material_fingerprint != plan["material_fingerprint"]:
        raise HTTPException(status_code=409, detail="物料关键词已变化，请重新预览后再提交")
    if not plan["can_submit"]:
        raise HTTPException(status_code=409, detail="；".join(plan["errors"]))
    if payload.build_rule_version != AD_BUILD_RULE_VERSION:
        raise HTTPException(status_code=409, detail="自动搭建规则已更新，请重新预览")
    build_rules = current_ad_build_rules()
    negative_keywords = project_negative_keyword_snapshot(db, payload.project_id)
    negative_keyword_fingerprint = hashlib.sha256(
        json.dumps(
            negative_keywords,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if payload.negative_keyword_fingerprint != negative_keyword_fingerprint:
        raise HTTPException(status_code=409, detail="项目否词已变化，请重新预览后再提交")

    job_id = uuid.uuid4()
    now = datetime.now(UTC)
    job = AdBuildJob(
        id=job_id,
        project_id=payload.project_id,
        selection_mode=payload.selection_mode,
        execution_mode=payload.execution_mode,
        status="scheduled" if payload.execution_mode == "scheduled" else "ready",
        first_scheduled_at=plan["first_scheduled_at"],
        batch_size=plan["batch_size"],
        batch_interval_minutes=plan["batch_interval_minutes"],
        account_count=plan["selected_count"],
        batch_count=plan["batch_count"],
        selection_config={
            "project_name": project.name,
            "ocpc_project_name_rule": "项目名称_MMDD_HH",
            "keyword_mode": payload.keyword_mode,
            "material_fingerprint": plan["material_fingerprint"],
            "material_snapshot": plan["material_snapshot"],
            "account_selectors": payload.account_selectors,
            "manager_login_names": payload.manager_login_names,
            "subject_names": payload.subject_names,
            "quantity": payload.quantity,
            "selection_seed": payload.selection_seed,
            "selected_account_ids": plan["selected_account_ids"],
            "selection_fingerprint": plan["selection_fingerprint"],
            "creative_pool_fingerprint": plan["creative_pool_fingerprint"],
            "creative_count_per_account": plan["creative_count_per_account"],
            "project_bid": str(payload.project_bid),
            "online_schedule_enabled": payload.online_schedule_enabled,
            "online_schedule": (
                [window.model_dump() for window in payload.online_schedule]
                if payload.online_schedule is not None
                else None
            ),
            "online_weekdays": payload.online_weekdays,
            "online_start_hour": payload.online_start_hour,
            "online_end_hour": payload.online_end_hour,
            "scheduled_dates": [value.isoformat() for value in payload.scheduled_dates],
            "scheduled_times": [value.strftime("%H:%M") for value in payload.scheduled_times],
            "schedule_unlimited": payload.schedule_unlimited,
            "build_rule_version": AD_BUILD_RULE_VERSION,
            "negative_keyword_source": "project_postgresql",
            "negative_keyword_fingerprint": negative_keyword_fingerprint,
            "negative_keyword_counts": {
                "phrase": len(negative_keywords["phrase"]),
                "exact": len(negative_keywords["exact"]),
            },
            "region_target": payload.region_target,
            "geo_location_status": payload.geo_location_status,
        },
        preflight_result={
            "can_submit": plan["can_submit"],
            "errors": plan["errors"],
            "warnings": plan["warnings"],
            "material_keyword_count": plan["material_keyword_count"],
            "keyword_mode": payload.keyword_mode,
            "material_fingerprint": plan["material_fingerprint"],
            "creative_available_combination_count": plan["creative_available_combination_count"],
            "creative_blacklisted_combination_count": plan["creative_blacklisted_combination_count"],
            "creative_segment_counts": plan["creative_segment_counts"],
            "permission_warning_count": plan["permission_warning_count"],
            "writes_enabled_at_creation": settings.baidu_writes_enabled,
            "negative_keyword_source": "project_postgresql",
            "negative_keyword_fingerprint": negative_keyword_fingerprint,
            "negative_keyword_counts": {
                "phrase": len(negative_keywords["phrase"]),
                "exact": len(negative_keywords["exact"]),
            },
            "build_rule_version": AD_BUILD_RULE_VERSION,
        },
        workflow_version=WORKFLOW_VERSION,
        created_by=actor.username,
    )
    db.add(job)
    db.flush()

    created_batches: list[AdBuildBatch] = []
    operation_count = 0
    creative_segments, existing_combinations, creative_blacklisted_hashes = load_creative_pool(db, payload.project_id)
    combination_map = {row.combination_hash: row for row in existing_combinations}
    for batch_plan in plan["batches"]:
        try:
            ocpc_project_name = build_ocpc_project_name(project.name, batch_plan["scheduled_at"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        batch = AdBuildBatch(
            job_id=job.id,
            batch_number=batch_plan["number"],
            scheduled_at=batch_plan["scheduled_at"],
            status="scheduled" if payload.execution_mode == "scheduled" else "ready",
            account_ids=batch_plan["account_ids"],
            operation_ids=[],
        )
        db.add(batch)
        db.flush()
        operation_ids: list[str] = []
        for account_id in batch_plan["account_ids"]:
            account = account_map[account_id]
            account_type = getattr(account.account_type, "value", account.account_type)
            workflow_overrides = account_workflow_overrides(account)
            selected_creatives = select_random_creative_combinations(
                creative_segments,
                creative_blacklisted_hashes,
                seed=f"{payload.project_id}:{payload.selection_seed}:{account.baidu_account_id}",
                limit=CREATIVE_COUNT_PER_ACCOUNT,
            )
            if len(selected_creatives) != CREATIVE_COUNT_PER_ACCOUNT:
                raise HTTPException(status_code=409, detail="创意库在创建任务前发生变化，请重新预览")
            creative_payload: list[dict] = []
            for slot_number, candidate in enumerate(selected_creatives, start=1):
                combination = ensure_creative_center_combination(
                    db, payload.project_id, candidate, combination_map,
                )
                assignment = CreativeAssignment(
                    id=uuid.uuid4(),
                    project_id=payload.project_id,
                    job_id=job.id,
                    account_id=account.id,
                    combination_id=combination.id,
                    slot_number=slot_number,
                    generation=1,
                    status="planned",
                )
                db.add(assignment)
                creative_payload.append({
                    "assignment_id": str(assignment.id),
                    "combination_id": str(combination.id),
                    "combination_hash": candidate.combination_hash,
                    "slot_number": slot_number,
                    "title": candidate.title,
                    "description1": candidate.description1,
                    "description2": candidate.description2,
                })
            operation = preflight_operation(db, OperationCreate(
                operation_type="search_ad_build_workflow",
                target_account_id=account.baidu_account_id,
                idempotency_key=f"ad-build:{job.id}:{account.baidu_account_id}",
                payload={
                    "ad_build_job_id": str(job.id),
                    "ad_build_batch_id": str(batch.id),
                    "execution_batch_number": batch.batch_number,
                    "keyword_batch_number": 1,
                    "scheduled_at": batch.scheduled_at.isoformat(),
                    "ocpc_project_name": ocpc_project_name,
                    "ocpc_project_name_rule": "项目名称_MMDD_HH",
                    "workflow_version": WORKFLOW_VERSION,
                    "workflow": account_workflow_steps(account),
                    "selection_mode": payload.selection_mode,
                    "keyword_mode": payload.keyword_mode,
                    "material_fingerprint": plan["material_fingerprint"],
                    "manager_login_name": account.manager_login_name,
                    "target_login_name": account.login_name,
                    "account_type": account_type,
                    "account_subject": account.account_subject,
                    "lifecycle_stage": account.lifecycle_stage,
                    "page_type": account.page_type,
                    "promotion_page": account.promotion_page,
                    "promotion_link": account.landing_url_template,
                    **workflow_overrides,
                    "material_source": "project_public_material_latest",
                    "creative_source": "project_creative_center_random_50",
                    "creative_combinations": creative_payload,
                    "creative_review_policy": {
                        "query_service": "creative.get",
                        "one_hop_main_reason_3": "delete_then_replenish_allow_resubmit",
                        "second_hop_main_reason_3": "count_rejection_blacklist_after_5",
                        "second_hop_segment_rejection": "blacklist_after_50",
                        "blacklisted_combination_resubmit": False,
                    },
                    "project_target_bid": str(payload.project_bid),
                    "plan_online_schedule": plan["build_settings"],
                    "preembedded_plan_update_fields": [
                        "phrase_negative_keywords",
                        "exact_negative_keywords",
                        "device_mobile",
                        "pause_schedule_if_enabled",
                    ] if account_type == "一跳预埋户" else [],
                    "account_region_update": "account_promotion_region_list",
                    "region_target": payload.region_target,
                    "geo_location_status": payload.geo_location_status,
                    "build_rule_version": AD_BUILD_RULE_VERSION,
                    "build_rules": build_rules,
                    "project_negative_keywords": negative_keywords,
                    "negative_keyword_source": "project_postgresql",
                    "negative_keyword_fingerprint": negative_keyword_fingerprint,
                    "campaign_region_mode": "unset",
                },
            ), actor.username)
            operation.status = OperationStatus.QUEUED
            operation.confirmed_by = actor.username
            operation.confirmed_at = now
            task = BackgroundTask(
                project_id=payload.project_id,
                operation_id=operation.id,
                task_type=operation.operation_type,
                status=TaskStatus.PENDING,
                current_node="scheduled_ad_build_wait",
                progress=0,
                heartbeat_at=now,
                result={"scheduled_for": batch.scheduled_at.isoformat()},
            )
            db.add(task)
            operation_ids.append(str(operation.id))
            operation_count += 1
        batch.operation_ids = operation_ids
        created_batches.append(batch)

    if not settings.baidu_writes_enabled:
        job.status = "waiting_writes"
        for batch in created_batches:
            batch.status = "waiting_writes"
    add_audit(
        db,
        payload.project_id,
        actor,
        "ad_build.create",
        "ad_build_job",
        "创建广告新建任务队列",
        str(job.id),
        {
            "keyword_mode": payload.keyword_mode,
            "selection_mode": payload.selection_mode,
            "execution_mode": payload.execution_mode,
            "account_count": job.account_count,
            "batch_count": job.batch_count,
            "batch_size": job.batch_size,
            "batch_interval_minutes": job.batch_interval_minutes,
            "scheduled_dates": plan["scheduled_dates"],
            "scheduled_times": plan["scheduled_times"],
            "schedule_unlimited": plan["schedule_unlimited"],
            "workflow_version": WORKFLOW_VERSION,
            "project_bid": str(payload.project_bid),
            "online_schedule_enabled": payload.online_schedule_enabled,
            "online_schedule": (
                [window.model_dump() for window in payload.online_schedule]
                if payload.online_schedule is not None
                else None
            ),
            "creative_count_per_account": CREATIVE_COUNT_PER_ACCOUNT,
            "creative_pool_fingerprint": plan["creative_pool_fingerprint"],
        },
    )
    db.commit()
    if payload.execution_mode == "immediate":
        from .worker import dispatch_ad_build_batch
        dispatch_ad_build_batch.delay(str(created_batches[0].id))
    return envelope(request, {
        "id": str(job.id),
        "status": job.status,
        "account_count": job.account_count,
        "batch_count": job.batch_count,
        "operation_count": operation_count,
        "writes_enabled": settings.baidu_writes_enabled,
        "batches": [
            {
                "id": str(batch.id),
                "number": batch.batch_number,
                "scheduled_at": batch.scheduled_at,
                "status": batch.status,
                "account_count": len(batch.account_ids),
            }
            for batch in created_batches
        ],
    })


AD_BUILD_NODE_LABELS = [
    ("material_preflight", "物料预检"),
    ("account_settings", "账户设置"),
    ("campaigns", "计划"),
    ("adgroups", "单元"),
    ("ocpc", "oCPC"),
    ("keywords", "关键词"),
    ("audiences", "人群"),
    ("creatives", "创意"),
    ("final_readback", "回读验证"),
]


def serialize_ad_build_nodes(task: BackgroundTask | None) -> list[dict]:
    result = task.result if task is not None and isinstance(task.result, dict) else {}
    cancelled = bool(result.get("cancelled"))
    state = result.get("workflow_state") if isinstance(result.get("workflow_state"), dict) else {}
    timings = state.get("timings") if isinstance(state.get("timings"), dict) else {}
    current_node = str(task.current_node or "") if task is not None else ""
    waiting_for_dispatch = current_node in {
        "queued",
        "scheduled",
        "scheduled_ad_build_wait",
        "waiting_writes",
    }
    current_key = next((key for key, _ in AD_BUILD_NODE_LABELS if key in current_node), None)
    if current_key is None and task is not None and not waiting_for_dispatch:
        progress = int(task.progress or 0)
        current_key = next((key for key, threshold in [
            ("material_preflight", 10), ("account_settings", 20), ("campaigns", 35),
            ("adgroups", 45), ("ocpc", 48), ("keywords", 82),
            ("audiences", 88), ("creatives", 96), ("final_readback", 100),
        ] if progress < threshold), "final_readback")
    nodes: list[dict] = []
    reached_current = False
    for key, label in AD_BUILD_NODE_LABELS:
        timing = timings.get(key) if isinstance(timings.get(key), dict) else {}
        if timing.get("completed_at"):
            status = "succeeded"
        elif task is None or cancelled or waiting_for_dispatch:
            status = "pending"
        elif key == current_key:
            reached_current = True
            status = "failed" if task.status in {TaskStatus.FAILED, TaskStatus.BLOCKED} else "running"
        elif not reached_current and timing.get("started_at"):
            status = "running"
        else:
            status = "pending"
        nodes.append({
            "key": key,
            "label": label,
            "status": status,
            "started_at": timing.get("started_at"),
            "completed_at": timing.get("completed_at"),
            "duration_seconds": timing.get("duration_seconds"),
            "message": task.last_error if status == "failed" else None,
        })
    return nodes


@router.get("/projects/{project_id}/ad-builds")
def list_ad_builds(
    project_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    _: Actor = Depends(current_actor),
):
    rows = db.scalars(
        select(AdBuildJob)
        .where(AdBuildJob.project_id == project_id)
        .order_by(desc(AdBuildJob.created_at))
        .limit(30)
    ).all()
    data = []
    for row in rows:
        batches = db.scalars(
            select(AdBuildBatch)
            .where(AdBuildBatch.job_id == row.id)
            .order_by(AdBuildBatch.batch_number)
        ).all()
        batch_data = []
        job_account_rows: list[dict] = []
        for batch in batches:
            account_ids: list[int] = []
            for value in batch.account_ids if isinstance(batch.account_ids, list) else []:
                try:
                    account_ids.append(int(value))
                except (TypeError, ValueError):
                    continue
            operation_ids: list[uuid.UUID] = []
            for value in batch.operation_ids if isinstance(batch.operation_ids, list) else []:
                try:
                    operation_ids.append(uuid.UUID(str(value)))
                except (TypeError, ValueError):
                    continue

            accounts_by_id = {
                account.baidu_account_id: account
                for account in db.scalars(
                    select(Account).where(
                        Account.project_id == row.project_id,
                        Account.baidu_account_id.in_(account_ids),
                    )
                ).all()
            } if account_ids else {}
            operations_by_id = {
                operation.id: operation
                for operation in db.scalars(
                    select(Operation).where(Operation.id.in_(operation_ids))
                ).all()
            } if operation_ids else {}
            latest_tasks_by_operation: dict[uuid.UUID, BackgroundTask] = {}
            if operation_ids:
                task_rows = db.scalars(
                    select(BackgroundTask)
                    .where(BackgroundTask.operation_id.in_(operation_ids))
                    .order_by(desc(BackgroundTask.created_at))
                ).all()
                for task_row in task_rows:
                    if task_row.operation_id is not None:
                        latest_tasks_by_operation.setdefault(task_row.operation_id, task_row)

            account_rows = []
            for index, account_id in enumerate(account_ids):
                account = accounts_by_id.get(account_id)
                operation_id = operation_ids[index] if index < len(operation_ids) else None
                operation = operations_by_id.get(operation_id) if operation_id is not None else None
                task = latest_tasks_by_operation.get(operation_id) if operation_id is not None else None
                fallback_status = (
                    "pending" if batch.status in {"ready", "scheduled"} else batch.status
                )
                fallback_node = {
                    "waiting_writes": "waiting_writes",
                    "scheduled": "scheduled",
                    "ready": "queued",
                }.get(batch.status, batch.status)
                account_row = {
                    "account_id": account.baidu_account_id if account is not None else (
                        operation.target_account_id if operation is not None else None
                    ),
                    "account_name": account.login_name if account is not None else (
                        operation.payload.get("target_login_name")
                        if operation is not None and isinstance(operation.payload, dict)
                        else None
                    ),
                    "account_subject": account.account_subject if account is not None else None,
                    "manager_login_name": account.manager_login_name if account is not None else (
                        operation.payload.get("manager_login_name")
                        if operation is not None and isinstance(operation.payload, dict)
                        else None
                    ),
                    "operation_id": str(operation_id) if operation_id is not None else None,
                    "task_id": str(task.id) if task is not None else (
                        str(operation_id) if operation_id is not None else None
                    ),
                    "status": (
                        "cancelled"
                        if task is not None
                        and isinstance(task.result, dict)
                        and task.result.get("cancelled")
                        else task.status.value if task is not None else fallback_status
                    ),
                    "current_node": task.current_node if task is not None else fallback_node,
                    "progress": task.progress if task is not None else 0,
                    "last_error": task.last_error if task is not None else None,
                    "result_summary": task_result_summary(task) if task is not None else (
                        "等待执行" if fallback_status == "pending" else "尚未产生执行结果"
                    ),
                    "nodes": serialize_ad_build_nodes(task),
                    "updated_at": (
                        task.updated_at if task is not None
                        else batch.dispatched_at or batch.created_at
                    ),
                }
                account_rows.append(account_row)
                job_account_rows.append(account_row)

            batch_data.append({
                "id": str(batch.id),
                "number": batch.batch_number,
                "scheduled_at": batch.scheduled_at,
                "status": batch.status,
                "account_count": len(batch.account_ids),
                "accounts": account_rows,
            })

        account_status_counts: dict[str, int] = {}
        for account_row in job_account_rows:
            status = str(account_row["status"])
            account_status_counts[status] = account_status_counts.get(status, 0) + 1
        data.append({
            "id": str(row.id),
            "keyword_mode": row.selection_config.get("keyword_mode", "preferred") if isinstance(row.selection_config, dict) else "preferred",
            "selection_mode": row.selection_mode,
            "execution_mode": row.execution_mode,
            "status": row.status,
            "first_scheduled_at": row.first_scheduled_at,
            "batch_size": row.batch_size,
            "batch_interval_minutes": row.batch_interval_minutes,
            "account_count": row.account_count,
            "batch_count": row.batch_count,
            "workflow_version": row.workflow_version,
            "created_by": row.created_by,
            "created_at": row.created_at,
            "account_status_counts": account_status_counts,
            "batches": batch_data,
        })
    return envelope(request, data)


@router.post("/operations/{operation_id}/confirm")
def confirm(operation_id: uuid.UUID, request: Request, db: Session = Depends(get_db), actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR))):
    operation, task = confirm_operation(db, operation_id, actor.username)
    from .worker import execute_operation
    execute_operation.delay(str(task.id))
    return envelope(request, {"operation_id": str(operation.id), "task_id": str(task.id), "status": operation.status.value})


@router.get("/tasks")
def list_tasks(request: Request, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    if not is_system_owner(actor):
        raise HTTPException(status_code=404, detail="任务不存在")
    rows = db.scalars(select(BackgroundTask).order_by(desc(BackgroundTask.created_at)).limit(100)).all()
    return envelope(request, [serialize_task_row(row) for row in rows])


@router.get("/tasks/{task_id}")
def task_detail(task_id: uuid.UUID, request: Request, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    if not is_system_owner(actor):
        raise HTTPException(status_code=404, detail="任务不存在")
    task = db.get(BackgroundTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return envelope(request, {"id": str(task.id), "status": task.status.value, "current_node": task.current_node, "progress": task.progress, "retry_count": task.retry_count, "last_error": task.last_error, "result": task.result, "heartbeat_at": task.heartbeat_at})


@router.post("/tasks/{task_id}/resume")
def resume_task(task_id: uuid.UUID, request: Request, db: Session = Depends(get_db), actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR))):
    if not is_system_owner(actor) and not getattr(request.state, "project_task_authorized", False):
        raise HTTPException(status_code=404, detail="任务不存在")
    task = db.get(BackgroundTask, task_id)
    if not task or task.status.value not in {"failed", "blocked"}:
        raise HTTPException(status_code=409, detail="只有失败或阻塞任务可以续跑")
    if isinstance(task.result, dict) and task.result.get("cancelled"):
        raise HTTPException(status_code=409, detail="已取消任务不能续跑；请重新创建自动上线任务")
    if task.task_type in {
        "baidu_account_backfill",
        "baidu_account_hourly_refresh",
        "baidu_account_final_archive",
    }:
        payload = task.result if isinstance(task.result, dict) else {}
        state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
        request_payload = dict(payload.get("request") or {})
        if task.status == TaskStatus.FAILED or state.get("failed_accounts"):
            failed_accounts = state.get("failed_accounts") or {}
            failed_account_ids: list[int] = []
            for account_id in failed_accounts:
                try:
                    failed_account_ids.append(int(account_id))
                except (TypeError, ValueError):
                    continue
            if failed_account_ids:
                local_account_ids = db.scalars(
                    select(Account.id).where(
                        Account.project_id == task.project_id,
                        Account.baidu_account_id.in_(sorted(set(failed_account_ids))),
                    )
                ).all()
                request_payload["account_ids"] = [str(account_id) for account_id in local_account_ids]
                request_payload["failed_baidu_account_ids"] = sorted(set(failed_account_ids))
                request_payload["retry_failed_only"] = True
            state.update({
                "cursor_account_id": 0,
                "processed_accounts": 0,
                "rows_upserted": 0,
                "empty_accounts": 0,
                "failed_accounts": {},
            })
        state["consecutive_errors"] = 0
        task.result = {"request": request_payload, "state": state}
        flag_modified(task, "result")
        task.status = TaskStatus.PENDING
        task.heartbeat_at = datetime.now(UTC)
        task.current_node = "queued_for_resume"
        task.last_error = None
        task.progress = 0
        db.commit()
        from .worker import sync_baidu_account_backfill
        sync_baidu_account_backfill.delay(str(task.id))
        return envelope(request, {"id": str(task.id), "status": "queued_for_resume"})
    if task.task_type in {"baidu_keyword_backfill", "baidu_keyword_daily_archive"}:
        payload = task.result if isinstance(task.result, dict) else {}
        state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
        if task.status == TaskStatus.FAILED or state.get("failed_accounts"):
            state.update({
                "cursor_account_id": 0,
                "processed_accounts": 0,
                "empty_accounts": 0,
                "report_pages": 0,
                "rows_seen": 0,
                "rows_matched": 0,
                "rows_unmatched": 0,
                "rows_non_keyword": 0,
                "deleted_marker_rows": 0,
                "rows_upserted": 0,
                "unmatched_keyword_samples": [],
                "failed_accounts": {},
            })
        state["consecutive_errors"] = 0
        task.result = {"request": payload.get("request") or {}, "state": state}
        flag_modified(task, "result")
        task.status = TaskStatus.PENDING
        task.heartbeat_at = datetime.now(UTC)
        task.current_node = "queued_for_resume"
        task.last_error = None
        task.progress = 0
        db.commit()
        from .worker import sync_baidu_keyword_backfill
        sync_baidu_keyword_backfill.delay(str(task.id))
        return envelope(request, {"id": str(task.id), "status": "queued_for_resume"})
    if task.task_type == "baidu_budget_snapshot":
        payload = task.result if isinstance(task.result, dict) else {}
        state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
        state.update({
            "cursor_account_id": 0,
            "processed_accounts": 0,
            "updated_accounts": 0,
            "failed_accounts": {},
        })
        task.result = {"request": payload.get("request") or {}, "state": state}
        flag_modified(task, "result")
        task.status = TaskStatus.PENDING
        task.heartbeat_at = datetime.now(UTC)
        task.current_node = "queued_for_resume"
        task.last_error = None
        task.progress = 0
        db.commit()
        from .worker import sync_project_budget_snapshot

        sync_project_budget_snapshot.delay(str(task.id))
        return envelope(request, {"id": str(task.id), "status": "queued_for_resume"})
    if task.task_type == "campaign_batch_update":
        payload = task.result if isinstance(task.result, dict) else {}
        request_payload = dict(payload.get("request") or {})
        state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
        failed_accounts = state.get("failed_accounts") if isinstance(state.get("failed_accounts"), dict) else {}
        if failed_accounts:
            failed_baidu_ids = []
            for value in failed_accounts:
                try:
                    failed_baidu_ids.append(int(value))
                except (TypeError, ValueError):
                    continue
            local_ids = db.scalars(select(Account.id).where(
                Account.project_id == task.project_id,
                Account.baidu_account_id.in_(failed_baidu_ids),
            )).all()
            request_payload["account_ids"] = [str(value) for value in local_ids]
        task.result = {"request": request_payload, "state": {}}
        flag_modified(task, "result")
        task.status = TaskStatus.PENDING
        task.heartbeat_at = datetime.now(UTC)
        task.current_node = "queued_for_resume"
        task.last_error = None
        task.progress = 0
        action = str(request_payload.get("action") or "")
        if action in {"schedule", "pause"}:
            setting = db.scalar(select(CampaignBatchSetting).where(
                CampaignBatchSetting.project_id == task.project_id,
                CampaignBatchSetting.account_type == str(request_payload.get("account_type") or ""),
                CampaignBatchSetting.page_type == str(request_payload.get("page_type") or ""),
            ))
            if setting is not None and getattr(setting, f"{action}_task_id") == task.id:
                setattr(setting, f"{action}_status", "pending")
                setting.updated_at = datetime.now(UTC)
        db.commit()
        from .worker import run_campaign_batch_update
        run_campaign_batch_update.delay(str(task.id))
        return envelope(request, {"id": str(task.id), "status": "queued_for_resume"})
    if task.task_type == "manager_campaign_cleanup":
        payload = task.result if isinstance(task.result, dict) else {}
        request_payload = dict(payload.get("request") or {})
        state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
        failed_accounts = state.get("failed_accounts") if isinstance(state.get("failed_accounts"), dict) else {}
        if failed_accounts:
            failed_baidu_ids = []
            for value in failed_accounts:
                try:
                    failed_baidu_ids.append(int(value))
                except (TypeError, ValueError):
                    continue
            try:
                manager_id = uuid.UUID(str(request_payload.get("manager_id")))
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=409, detail="清空计划任务缺少账户管家范围") from exc
            accounts = db.scalars(select(Account).where(
                Account.project_id == task.project_id,
                Account.manager_id == manager_id,
                Account.baidu_account_id.in_(failed_baidu_ids),
            ).order_by(Account.baidu_account_id)).all()
            request_payload["account_ids"] = [str(account.id) for account in accounts]
        task.result = {"request": request_payload, "state": {}}
        flag_modified(task, "result")
        task.status = TaskStatus.PENDING
        task.heartbeat_at = datetime.now(UTC)
        task.current_node = "queued_for_resume"
        task.last_error = None
        task.progress = 0
        task.retry_count = 0
        db.commit()
        from .worker import run_manager_campaign_cleanup
        run_manager_campaign_cleanup.delay(str(task.id))
        return envelope(request, {"id": str(task.id), "status": "queued_for_resume"})
    if task.task_type == "hduofen_capture":
        payload = task.result if isinstance(task.result, dict) else {}
        request_details = (
            payload.get("request") if isinstance(payload.get("request"), dict) else {}
        )
        date_from = str(request_details.get("date_from") or "")
        date_to = str(request_details.get("date_to") or "")
        if not date_from or not date_to or task.project_id is None:
            raise HTTPException(status_code=409, detail="好多粉任务缺少可续跑日期范围")
        task.status = TaskStatus.PENDING
        task.heartbeat_at = datetime.now(UTC)
        task.current_node = "queued_for_resume"
        task.last_error = None
        task.progress = 0
        task.result = {"request": request_details}
        flag_modified(task, "result")
        db.commit()
        from .worker import capture_hduofen_for_task
        capture_hduofen_for_task.delay(
            str(task.id), str(task.project_id), date_from, date_to
        )
        return envelope(request, {"id": str(task.id), "status": "queued_for_resume"})
    if task.task_type == "account_elimination_cycle":
        payload = task.result if isinstance(task.result, dict) else {}
        task.status = TaskStatus.PENDING
        task.heartbeat_at = datetime.now(UTC)
        task.current_node = "queued_for_resume"
        task.last_error = None
        task.progress = 0
        task.retry_count = 0
        task.result = {"request": payload.get("request") or {}, "state": {}}
        flag_modified(task, "result")
        db.commit()
        from .worker import run_account_elimination_cycle
        run_account_elimination_cycle.delay(str(task.id))
        return envelope(request, {"id": str(task.id), "status": "queued_for_resume"})
    operation = db.get(Operation, task.operation_id) if task.operation_id else None
    if operation is None:
        raise HTTPException(status_code=409, detail="任务缺少可续跑的操作申请")
    latest_task_id = db.scalar(
        select(BackgroundTask.id)
        .where(BackgroundTask.operation_id == operation.id)
        .order_by(desc(BackgroundTask.created_at), desc(BackgroundTask.id))
        .limit(1)
    )
    if latest_task_id != task.id:
        raise HTTPException(status_code=409, detail="该账户已有更新的执行记录，请勿续跑历史失败任务")
    if operation.status == OperationStatus.SUCCEEDED:
        raise HTTPException(status_code=409, detail="该账户后续任务已经成功，无需再次续跑")
    if operation.status != OperationStatus.FAILED:
        raise HTTPException(status_code=409, detail="当前操作正在执行或等待调度，不能重复续跑")
    task.status = TaskStatus.PENDING
    task.heartbeat_at = datetime.now(UTC)
    task.current_node = "queued_for_resume"
    task.last_error = None
    task.retry_count = 0
    operation.status = OperationStatus.QUEUED
    batch_id = operation.payload.get("ad_build_batch_id") if isinstance(operation.payload, dict) else None
    if batch_id:
        batch = db.get(AdBuildBatch, uuid.UUID(str(batch_id)))
        if batch is not None:
            batch.status = "dispatched"
            job = db.get(AdBuildJob, batch.job_id)
            if job is not None:
                job.status = "running"
    db.commit()
    from .worker import execute_operation
    execute_operation.delay(str(task.id))
    return envelope(request, {"id": str(task.id), "status": "queued_for_resume"})


@router.get("/tasks/{task_id}/events")
async def task_events(task_id: uuid.UUID, db: Session = Depends(get_db), _: Actor = Depends(current_actor)):
    async def stream():
        last = None
        for _ in range(300):
            db.expire_all()
            task = db.get(BackgroundTask, task_id)
            if not task:
                yield "event: error\ndata: {\"message\":\"task not found\"}\n\n"
                return
            state = {"status": task.status.value, "node": task.current_node, "progress": task.progress, "heartbeat_at": task.heartbeat_at.isoformat() if task.heartbeat_at else None}
            serialized = json.dumps(state, ensure_ascii=False)
            if serialized != last:
                yield f"event: task\ndata: {serialized}\n\n"
                last = serialized
            if task.status.value in {"succeeded", "failed", "blocked"}:
                return
            await asyncio.sleep(2)
    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/attribution/unmatched")
def unmatched(request: Request, _: Actor = Depends(current_actor)):
    return envelope(request, [])


def build_daily_report(
    db: Session,
    project_id: uuid.UUID,
    start: date,
    end: date,
    *,
    page: int = 1,
    page_size: int | None = 20,
    search: str | None = None,
    manager_id: uuid.UUID | None = None,
    manager_ids: str | None = None,
    account_type: str | None = None,
    account_types: str | None = None,
    page_type: str | None = None,
    page_types: str | None = None,
    operator_name: str | None = None,
    operator_names: str | None = None,
    lifecycle: str | None = None,
    lifecycles: str | None = None,
    cost_status: str | None = None,
    cost_statuses: str | None = None,
    account_names: str | None = None,
    sort_by: str = "spend",
    sort_order: str = "desc",
    include_summary: bool = True,
    allowed_operator_names: tuple[str, ...] | None = None,
) -> dict:
    judgment_preference = load_account_judgment_preference(db, project_id)
    facts = judgment_facts(db, project_id)
    resolved_cost_status = cost_judgment_expressions(facts, judgment_preference)["status"]

    def with_judgment_joins(statement):
        return (
            statement
            .outerjoin(facts.lifetime_metrics, facts.lifetime_metrics.c.account_id == Account.id)
            .outerjoin(facts.recent_metrics, facts.recent_metrics.c.account_id == Account.id)
            .outerjoin(facts.campaign_facts, facts.campaign_facts.c.account_id == Account.id)
        )

    account_filters = [Account.project_id == project_id]
    if allowed_operator_names is not None:
        account_filters.append(Account.operator_name.in_(allowed_operator_names))
    normalized_search = (search or "").strip()
    normalized_account_type = (account_type or "").strip()
    normalized_page_type = (page_type or "").strip()
    normalized_operator_name = (operator_name or "").strip()
    selected_manager_ids = tuple(dict.fromkeys(item.strip() for item in (manager_ids or "").split(",") if item.strip()))
    selected_account_types = tuple(dict.fromkeys(item.strip() for item in (account_types or "").split(",") if item.strip()))
    selected_page_types = tuple(dict.fromkeys(item.strip() for item in (page_types or "").split(",") if item.strip()))
    selected_operators = tuple(dict.fromkeys(item.strip() for item in (operator_names or "").split(",") if item.strip()))
    selected_cost_statuses = tuple(dict.fromkeys(item.strip() for item in (cost_statuses or cost_status or "").split(",") if item.strip()))
    selected_account_names = tuple(dict.fromkeys(item.strip() for item in (account_names or "").split(",") if item.strip()))
    if selected_manager_ids:
        try:
            manager_uuid_values = tuple(uuid.UUID(value) for value in selected_manager_ids)
        except ValueError:
            manager_uuid_values = ()
        account_filters.append(Account.manager_id.in_(manager_uuid_values) if manager_uuid_values else False)
    elif manager_id:
        account_filters.append(Account.manager_id == manager_id)
    if selected_account_types:
        resolved_types = []
        for value in selected_account_types:
            try:
                resolved_types.append(AccountType(value))
            except ValueError:
                try:
                    resolved_types.append(AccountType[value])
                except KeyError:
                    continue
        account_filters.append(Account.account_type.in_(resolved_types) if resolved_types else False)
    elif normalized_account_type:
        try:
            resolved_account_type = AccountType(normalized_account_type)
        except ValueError:
            try:
                resolved_account_type = AccountType[normalized_account_type]
            except KeyError:
                resolved_account_type = None
        account_filters.append(Account.account_type == resolved_account_type if resolved_account_type else False)
    if selected_page_types:
        account_filters.append(Account.page_type.in_(selected_page_types))
    elif normalized_page_type:
        account_filters.append(Account.page_type == normalized_page_type)
    if selected_operators:
        assigned_operators = tuple(value for value in selected_operators if value != "__unassigned__")
        operator_conditions = [Account.operator_name.in_(assigned_operators)] if assigned_operators else []
        if "__unassigned__" in selected_operators:
            operator_conditions.append(or_(Account.operator_name.is_(None), Account.operator_name == ""))
        account_filters.append(or_(*operator_conditions) if operator_conditions else False)
    elif normalized_operator_name == "__unassigned__":
        account_filters.append(or_(Account.operator_name.is_(None), Account.operator_name == ""))
    elif normalized_operator_name:
        account_filters.append(Account.operator_name == normalized_operator_name)
    if selected_cost_statuses:
        account_filters.append(resolved_cost_status.in_(selected_cost_statuses))
    if selected_account_names:
        account_filters.append(Account.login_name.in_(selected_account_names))
    if normalized_search:
        escaped_search = (
            normalized_search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        pattern = f"%{escaped_search}%"
        account_filters.append(or_(
            Account.login_name.ilike(pattern, escape="\\"),
            cast(Account.baidu_account_id, String).ilike(pattern, escape="\\"),
        ))
    filters = [*account_filters, PerformanceDaily.report_date.between(start, end)]
    total = (
        int(db.scalar(
            with_judgment_joins(
                select(func.count(PerformanceDaily.id))
                .join(Account, PerformanceDaily.account_id == Account.id)
            )
            .where(*filters)
        ) or 0)
        if include_summary
        else 0
    )
    cpc_expression = PerformanceDaily.spend / func.nullif(PerformanceDaily.clicks, 0)
    uv_cost_expression = PerformanceDaily.spend / func.nullif(PerformanceDaily.uv, 0)
    copy_cost_expression = PerformanceDaily.spend / func.nullif(PerformanceDaily.copies, 0)
    add_cost_expression = PerformanceDaily.spend / func.nullif(PerformanceDaily.adds, 0)
    cash_spend_expression = PerformanceDaily.spend / (
        literal(Decimal("1")) + Account.rebate_rate / literal(Decimal("100"))
    )
    sort_expressions = {
        "account_name": Account.login_name,
        "account_id": Account.baidu_account_id,
        "operator_name": Account.operator_name,
        "manager_name": Account.manager_login_name,
        "account_type": cast(Account.account_type, String),
        "page_type": Account.page_type,
        "balance": Account.balance,
        "impressions": PerformanceDaily.impressions,
        "clicks": PerformanceDaily.clicks,
        "spend": PerformanceDaily.spend,
        "uv": PerformanceDaily.uv,
        "copies": PerformanceDaily.copies,
        "adds": PerformanceDaily.adds,
        "cpc": cpc_expression,
        "uv_cost": uv_cost_expression,
        "copy_cost": copy_cost_expression,
        "add_cost": add_cost_expression,
        "cash_spend": cash_spend_expression,
        "cash_copy_cost": cash_spend_expression / func.nullif(PerformanceDaily.copies, 0),
        "cash_add_cost": cash_spend_expression / func.nullif(PerformanceDaily.adds, 0),
        "cost_status": resolved_cost_status,
    }
    sort_expression = sort_expressions.get(sort_by, PerformanceDaily.spend)
    primary_order = (
        sort_expression.asc().nulls_last()
        if sort_order == "asc"
        else sort_expression.desc().nulls_last()
    )
    rows_query = (
        with_judgment_joins(
            select(PerformanceDaily, Account, resolved_cost_status.label("cost_status"))
            .join(Account, PerformanceDaily.account_id == Account.id)
        )
        .where(*filters)
        .order_by(
            primary_order,
            desc(PerformanceDaily.report_date),
            Account.login_name,
            Account.id,
        )
    )
    if page_size is not None:
        rows_query = rows_query.offset((page - 1) * page_size).limit(page_size)
    rows = db.execute(rows_query).all()
    result = []
    for performance, account, row_cost_status in rows:
        spend = Decimal(performance.spend)
        rebate_rate = Decimal(account.rebate_rate) if account.rebate_rate is not None else None
        cash_spend = calculate_cash_spend(spend, rebate_rate)
        metrics = calculate_report_metrics(
            spend, cash_spend, performance.clicks, performance.uv, performance.copies, performance.adds
        )
        result.append({
            "date": performance.report_date,
            "account_id": account.baidu_account_id,
            "account_name": account.login_name,
            "balance": account.balance if account.budget_snapshot_at is not None else None,
            "balance_snapshot_at": account.budget_snapshot_at,
            "cost_status": row_cost_status,
            "operator_name": account.operator_name,
            "manager_id": str(account.manager_id) if account.manager_id else None,
            "manager_name": account.manager.login_name if account.manager else account.manager_login_name,
            "account_type": account.account_type.value,
            "page_type": account.page_type,
            "promotion_page": account.promotion_page,
            "promotion_link": account.landing_url_template,
            "rebate_rate": account.rebate_rate,
            "recharge_account": account.recharge_account,
            "impressions": performance.impressions,
            "clicks": performance.clicks,
            "spend": spend,
            "cash_spend": cash_spend,
            "uv": performance.uv,
            "copies": performance.copies,
            "adds": performance.adds,
            **metrics,
        })

    if not include_summary:
        return {
            "date_from": start,
            "date_to": end,
            "total": len(result),
            "page": 1,
            "page_size": len(result),
            "total_pages": 1,
            "search": normalized_search,
            "manager_id": str(manager_id) if manager_id else "",
            "account_type": normalized_account_type,
            "page_type": normalized_page_type,
            "operator_name": normalized_operator_name,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "rows": result,
        }

    aggregate = db.execute(
        with_judgment_joins(select(
            func.coalesce(func.sum(PerformanceDaily.spend), 0),
            func.coalesce(func.sum(PerformanceDaily.impressions), 0),
            func.coalesce(func.sum(PerformanceDaily.clicks), 0),
            func.coalesce(func.sum(PerformanceDaily.uv), 0),
            func.coalesce(func.sum(PerformanceDaily.copies), 0),
            func.coalesce(func.sum(PerformanceDaily.adds), 0),
            func.max(PerformanceDaily.source_watermark),
        ).join(Account, PerformanceDaily.account_id == Account.id))
        .where(*filters)
    ).one()
    total_spend = Decimal(aggregate[0] or 0)
    totals = {
        "impressions": int(aggregate[1] or 0),
        "clicks": int(aggregate[2] or 0),
        "uv": int(aggregate[3] or 0),
        "copies": int(aggregate[4] or 0),
        "adds": int(aggregate[5] or 0),
    }
    watermark = aggregate[6]
    cash_groups = db.execute(
        with_judgment_joins(
            select(func.sum(PerformanceDaily.spend), Account.rebate_rate)
            .join(Account, PerformanceDaily.account_id == Account.id)
        )
        .where(*filters)
        .group_by(Account.id, Account.rebate_rate)
    ).all()
    cash_values = [
        calculate_cash_spend(Decimal(spend or 0), Decimal(rate) if rate is not None else None)
        for spend, rate in cash_groups
    ]
    summary_cash_spend = (
        sum((value for value in cash_values if value is not None), Decimal("0"))
        if cash_groups and all(value is not None for value in cash_values)
        else None
    )
    summary_metrics = calculate_report_metrics(
        total_spend,
        summary_cash_spend,
        totals["clicks"],
        totals["uv"],
        totals["copies"],
        totals["adds"],
    )
    summary = {
        "spend": total_spend,
        "cash_spend": summary_cash_spend,
        **totals,
        **summary_metrics,
    }
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=(end - start).days)
    previous_filters = [
        *account_filters,
        PerformanceDaily.report_date.between(previous_start, previous_end),
    ]
    previous_aggregate = db.execute(
        with_judgment_joins(select(
            func.coalesce(func.sum(PerformanceDaily.spend), 0),
            func.coalesce(func.sum(PerformanceDaily.impressions), 0),
            func.coalesce(func.sum(PerformanceDaily.clicks), 0),
            func.coalesce(func.sum(PerformanceDaily.uv), 0),
            func.coalesce(func.sum(PerformanceDaily.copies), 0),
            func.coalesce(func.sum(PerformanceDaily.adds), 0),
        ).join(Account, PerformanceDaily.account_id == Account.id))
        .where(*previous_filters)
    ).one()
    previous_spend = Decimal(previous_aggregate[0] or 0)
    previous_totals = {
        "impressions": int(previous_aggregate[1] or 0),
        "clicks": int(previous_aggregate[2] or 0),
        "uv": int(previous_aggregate[3] or 0),
        "copies": int(previous_aggregate[4] or 0),
        "adds": int(previous_aggregate[5] or 0),
    }
    previous_cash_groups = db.execute(
        with_judgment_joins(
            select(func.sum(PerformanceDaily.spend), Account.rebate_rate)
            .join(Account, PerformanceDaily.account_id == Account.id)
        )
        .where(*previous_filters)
        .group_by(Account.id, Account.rebate_rate)
    ).all()
    previous_cash_values = [
        calculate_cash_spend(Decimal(spend or 0), Decimal(rate) if rate is not None else None)
        for spend, rate in previous_cash_groups
    ]
    previous_cash_spend = (
        sum((value for value in previous_cash_values if value is not None), Decimal("0"))
        if previous_cash_groups and all(value is not None for value in previous_cash_values)
        else None
    )
    previous_metrics = calculate_report_metrics(
        previous_spend,
        previous_cash_spend,
        previous_totals["clicks"],
        previous_totals["uv"],
        previous_totals["copies"],
        previous_totals["adds"],
    )
    previous_summary = {
        "spend": previous_spend,
        "cash_spend": previous_cash_spend,
        **previous_totals,
        **previous_metrics,
    }
    page_types = [
        value
        for value in db.scalars(
            select(Account.page_type)
            .where(
                Account.project_id == project_id,
                *( [Account.operator_name.in_(allowed_operator_names)] if allowed_operator_names is not None else [] ),
                Account.page_type.is_not(None),
                Account.page_type != "",
            )
            .distinct()
            .order_by(Account.page_type)
        ).all()
        if value
    ]
    report_account_names = [
        value
        for value in db.scalars(
            select(Account.login_name)
            .where(
                Account.project_id == project_id,
                *( [Account.operator_name.in_(allowed_operator_names)] if allowed_operator_names is not None else [] ),
                Account.login_name.is_not(None),
                Account.login_name != "",
            )
            .distinct()
            .order_by(Account.login_name)
        ).all()
        if value
    ]
    operator_names = [
        value
        for value in db.scalars(
            select(Account.operator_name)
            .where(
                Account.project_id == project_id,
                *( [Account.operator_name.in_(allowed_operator_names)] if allowed_operator_names is not None else [] ),
                Account.operator_name.is_not(None),
                Account.operator_name != "",
            )
            .distinct()
            .order_by(Account.operator_name)
        ).all()
        if value
    ]
    has_unassigned_operator = bool(db.scalar(
        select(func.count(Account.id)).where(
            Account.project_id == project_id,
            *( [Account.operator_name.in_(allowed_operator_names)] if allowed_operator_names is not None else [] ),
            or_(Account.operator_name.is_(None), Account.operator_name == ""),
        )
    ))
    managers = [
        {"id": str(manager.id), "name": manager.display_name or manager.login_name}
        for manager in db.scalars(
            select(AccountManager)
            .where(
                AccountManager.project_id == project_id,
                AccountManager.is_active.is_(True),
                *( [AccountManager.id.in_(select(Account.manager_id).where(
                    Account.project_id == project_id,
                    Account.operator_name.in_(allowed_operator_names),
                ))] if allowed_operator_names is not None else [] ),
            )
            .order_by(AccountManager.display_name, AccountManager.login_name)
        ).all()
    ]
    return {
        "date_from": start, "date_to": end, "watermark": watermark,
        "search": normalized_search,
        "manager_id": str(manager_id) if manager_id else "",
        "managers": managers,
        "account_type": normalized_account_type,
        "account_types": [item.value for item in AccountType],
        "page_type": normalized_page_type,
        "page_types": page_types,
        "operator_name": normalized_operator_name,
        "operator_names": operator_names,
        "has_unassigned_operator": has_unassigned_operator,
        "account_names": report_account_names,
        "cost_statuses": list(selected_cost_statuses),
        "cost_judgment": judgment_preference,
        "sort_by": sort_by,
        "sort_order": sort_order,
        "total": total,
        "page": page,
        "page_size": page_size or total,
        "total_pages": (
            max(1, (total + page_size - 1) // page_size) if page_size is not None else 1
        ),
        "summary": summary,
        "comparison": {
            "date_from": previous_start,
            "date_to": previous_end,
            "summary": previous_summary,
            "trends": _comparison_trends(summary, previous_summary),
        },
        "rows": result,
    }


def _task_permission_module(task: BackgroundTask) -> str:
    task_type = task.task_type
    if "ad_build" in task_type or task_type.startswith("creative"):
        return "auto_launch"
    if task_type.startswith("manager_"):
        return "account_management"
    if "automation" in task_type or task_type.startswith("budget_"):
        return "strategies"
    if "report" in task_type or task_type.startswith("hduofen"):
        return "reports"
    return "account_list"


def _require_task_access(
    db: Session,
    task: BackgroundTask,
    actor: Actor,
    level: str,
):
    if task.project_id is None:
        if not is_system_owner(actor):
            raise HTTPException(status_code=404, detail="任务不存在")
        return None
    access = require_project_permission(
        db,
        task.project_id,
        actor,
        _task_permission_module(task),
        level,
    )
    if access.operator_names is None:
        return access
    payload = task.result if isinstance(task.result, dict) else {}
    request_details = payload.get("request") if isinstance(payload.get("request"), dict) else {}
    account_ids = request_details.get("account_ids")
    if isinstance(account_ids, list) and account_ids:
        parsed_ids = []
        for value in account_ids:
            try:
                parsed_ids.append(uuid.UUID(str(value)))
            except (TypeError, ValueError):
                continue
        rows = db.scalars(select(Account).where(
            Account.project_id == task.project_id,
            Account.id.in_(parsed_ids),
        )).all() if parsed_ids else []
        for account in rows:
            require_account_scope(access, account)
    if task.operation_id:
        operation = db.get(Operation, task.operation_id)
        if operation is not None:
            account = db.scalar(select(Account).where(
                Account.project_id == task.project_id,
                Account.baidu_account_id == operation.target_account_id,
            ))
            if account is not None:
                require_account_scope(access, account)
    if not account_ids and not task.operation_id and request_details.get("requested_by") != actor.username:
        raise HTTPException(status_code=404, detail="任务不存在")
    return access


def _finance_date_range(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    selected_to = date_to or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    selected_from = date_from or selected_to
    if selected_from > selected_to or (selected_to - selected_from).days > 366:
        raise HTTPException(status_code=422, detail="财务报表日期范围无效或超过 366 天")
    return selected_from, selected_to


@router.get("/projects/{project_id}/finance/recharge-reconciliation")
def get_recharge_reconciliation(
    project_id: uuid.UUID,
    request: Request,
    date_from: date | None = None,
    date_to: date | None = None,
    movement_type: str | None = Query(default=None, pattern="^(recharge|refund)$"),
    reconciliation_status: str | None = Query(default=None, pattern="^(reconciled|unreconciled)$"),
    search: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=10, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    require_project_permission(db, project_id, actor, "finance_reports", "view")
    selected_from, selected_to = _finance_date_range(date_from, date_to)
    return envelope(request, recharge_reconciliation_report(
        db,
        project_id,
        date_from=selected_from,
        date_to=selected_to,
        movement_type=movement_type,
        reconciliation_status=reconciliation_status,
        search=search,
        page=page,
        page_size=page_size,
    ))


@router.patch("/projects/{project_id}/finance/recharge-reconciliation")
def update_recharge_reconciliation(
    project_id: uuid.UUID,
    payload: FinanceReconciliationUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    require_project_permission(db, project_id, actor, "finance_reports", "manage")
    result = set_reconciliation_status(
        db,
        project_id,
        rows=payload.rows,
        reconciled=payload.reconciled,
        actor=actor.username,
    )
    db.add(AuditEvent(
        project_id=project_id,
        actor=actor.username,
        action="finance.reconciliation.confirm" if payload.reconciled else "finance.reconciliation.cancel",
        target_type="finance_reconciliation",
        target_id=str(result["updated"]),
        summary=f"{'确认' if payload.reconciled else '取消'}对账 {result['updated']} 条",
        details={
            "reconciled": payload.reconciled,
            "rows": [
                {
                    "date": row.report_date.isoformat(),
                    "account_id": row.account_id,
                    "movement_type": row.movement_type,
                }
                for row in payload.rows
            ],
            **result,
        },
    ))
    db.commit()
    return envelope(request, result)


@router.get("/projects/{project_id}/finance/profit")
def get_profit_report(
    project_id: uuid.UUID,
    request: Request,
    date_from: date | None = None,
    date_to: date | None = None,
    operator_name: str | None = Query(default=None, max_length=30),
    search: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=10, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    access = require_project_permission(db, project_id, actor, "finance_reports", "view")
    selected_from, selected_to = _finance_date_range(date_from, date_to)
    try:
        data = profit_report(
            db,
            project_id,
            date_from=selected_from,
            date_to=selected_to,
            operator_name=operator_name,
            allowed_operator_names=access.operator_names,
            search=search,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return envelope(request, data)


@router.patch("/projects/{project_id}/finance/profit")
def update_profit_report(
    project_id: uuid.UUID,
    payload: FinanceProfitUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    access = require_project_permission(db, project_id, actor, "finance_reports", "manage")
    try:
        updated = save_profit_inputs(
            db,
            project_id,
            operator_name=payload.operator_name,
            allowed_operator_names=access.operator_names,
            rows=payload.rows,
            actor=actor.username,
        )
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    db.add(AuditEvent(
        project_id=project_id,
        actor=actor.username,
        action="finance.profit.reported_spend.update",
        target_type="finance_profit_report",
        target_id=payload.operator_name or "all",
        summary=f"更新利润报表报消耗 {updated} 天",
        details={
            "operator_name": payload.operator_name,
            "dates": [row.report_date.isoformat() for row in payload.rows],
        },
    ))
    db.commit()
    return envelope(request, {"updated": updated})


@router.get("/projects/{project_id}/reports/daily")
def daily_report(
    project_id: uuid.UUID,
    request: Request,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=100),
    manager_id: uuid.UUID | None = None,
    manager_ids: str | None = Query(default=None, max_length=4000),
    account_type: str | None = Query(default=None, max_length=30),
    account_types: str | None = Query(default=None, max_length=500),
    page_type: str | None = Query(default=None, max_length=30),
    page_types: str | None = Query(default=None, max_length=500),
    operator_name: str | None = Query(default=None, max_length=30),
    operator_names: str | None = Query(default=None, max_length=1000),
    lifecycle: str | None = Query(default=None, max_length=50),
    lifecycles: str | None = Query(default=None, max_length=500),
    cost_status: str | None = Query(default=None, max_length=30),
    cost_statuses: str | None = Query(default=None, max_length=500),
    account_names: str | None = Query(default=None, max_length=10000),
    sort_by: str = Query(
        default="spend",
        pattern="^(account_name|account_id|operator_name|manager_name|account_type|page_type|balance|impressions|clicks|spend|uv|copies|adds|cpc|uv_cost|copy_cost|add_cost|cash_spend|cash_copy_cost|cash_add_cost|cost_status)$",
    ),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    access = require_project_permission(db, project_id, actor, "reports", "view")
    end = date_to or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    start = date_from or end
    if start > end or (end - start).days > 366:
        raise HTTPException(status_code=400, detail="报表日期范围无效或超过 366 天")
    return envelope(
        request,
        build_daily_report(
            db,
            project_id,
            start,
            end,
            page=page,
            page_size=page_size,
            search=search,
            manager_id=manager_id,
            manager_ids=manager_ids,
            account_type=account_type,
            account_types=account_types,
            page_type=page_type,
            page_types=page_types,
            operator_name=operator_name,
            operator_names=operator_names,
            lifecycle=lifecycle,
            lifecycles=lifecycles,
            cost_status=cost_status,
            cost_statuses=cost_statuses,
            account_names=account_names,
            sort_by=sort_by,
            sort_order=sort_order,
            allowed_operator_names=access.operator_names,
        ),
    )


@router.post("/projects/{project_id}/reports/baidu-account-backfill")
def start_baidu_account_backfill(
    project_id: uuid.UUID,
    request: Request,
    date_from: date = Query(default=date(2026, 2, 14)),
    date_to: date | None = Query(default=None),
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    """Queue the agreed account-only Baidu report backfill; no lower-level reports are requested."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    date_to = date_to or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if date_to < date_from:
        raise HTTPException(status_code=422, detail="结束日期不能早于开始日期")
    if (date_to - date_from).days > 823:
        raise HTTPException(status_code=422, detail="搜索整体账户报告单次最多补齐824天")
    account_count = int(db.scalar(select(func.count(Account.id)).where(
        Account.project_id == project_id,
        Account.is_active.is_(True),
    )) or 0)
    if account_count == 0:
        raise HTTPException(status_code=409, detail="当前项目没有可同步账户")
    authorized_manager = db.scalar(select(AccountManager.id).where(
        AccountManager.project_id == project_id,
        AccountManager.is_active.is_(True),
        AccountManager.auth_status == "authorized",
    ).limit(1))
    if authorized_manager is None:
        raise HTTPException(status_code=409, detail="当前项目没有已授权的账户管家")

    running = db.scalar(select(BackgroundTask).where(
        BackgroundTask.project_id == project_id,
        BackgroundTask.task_type == "baidu_account_backfill",
        BackgroundTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
    ).order_by(desc(BackgroundTask.created_at)))
    if running:
        return envelope(request, {
            "task_id": str(running.id),
            "status": running.status.value,
            "message": "账户日报补齐任务已在运行",
        })

    preference = db.scalar(select(ProjectPreference).where(
        ProjectPreference.project_id == project_id,
        ProjectPreference.key == "baidu_account_report",
    ))
    preference_value = {
        "enabled": True,
        "scope": "account_daily",
        "start_date": date_from.isoformat(),
        "rolling_refresh_days": 2,
    }
    if preference is None:
        preference = ProjectPreference(
            project_id=project_id,
            key="baidu_account_report",
            value=preference_value,
            updated_by=actor.username,
        )
        db.add(preference)
    else:
        preference.value = preference_value
        preference.updated_by = actor.username

    task = BackgroundTask(
        project_id=project_id,
        task_type="baidu_account_backfill",
        current_node="queued",
        result={
            "request": {
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "scope": "account_daily",
                "report_type": 170026,
            },
            "state": {
                "cursor_account_id": 0,
                "processed_accounts": 0,
                "rows_upserted": 0,
                "empty_accounts": 0,
                "failed_accounts": {},
                "consecutive_errors": 0,
                "total_accounts": account_count,
            },
        },
    )
    db.add(task)
    db.add(AuditEvent(
        project_id=project_id,
        actor=actor.username,
        action="baidu.account_report.backfill.requested",
        target_type="background_task",
        target_id=str(task.id),
        summary="发起百度账户日报历史补齐",
        details={
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "scope": "account_daily",
            "account_count": account_count,
        },
    ))
    db.commit()
    from .worker import sync_baidu_account_backfill
    sync_baidu_account_backfill.delay(str(task.id))
    return envelope(request, {
        "task_id": str(task.id),
        "status": "pending",
        "scope": "account_daily",
        "date_from": date_from,
        "date_to": date_to,
        "account_count": account_count,
    })


@router.post("/projects/{project_id}/reports/baidu-keyword-backfill")
def start_baidu_keyword_backfill(
    project_id: uuid.UUID,
    request: Request,
    date_from: date = Query(default=date(2026, 2, 14)),
    date_to: date | None = Query(default=None),
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    """Queue exact material-keyword matching for active second-hop accounts only."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    date_to = date_to or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if date_to < date_from:
        raise HTTPException(status_code=422, detail="结束日期不能早于开始日期")
    if (date_to - date_from).days > 730:
        raise HTTPException(status_code=422, detail="搜索关键词报告单次最多补齐731天")
    account_count = int(db.scalar(select(func.count(Account.id)).where(
        Account.project_id == project_id,
        Account.is_active.is_(True),
        Account.account_type == AccountType.SECOND_HOP,
    )) or 0)
    if account_count == 0:
        raise HTTPException(status_code=409, detail="当前项目没有可同步的二跳账户")
    material_keyword_count = int(db.scalar(select(func.count(MaterialKeyword.id)).where(
        MaterialKeyword.project_id == project_id,
    )) or 0)
    if material_keyword_count == 0:
        raise HTTPException(status_code=409, detail="物料中心没有关键词，无法进行精确匹配")
    authorized_manager = db.scalar(select(AccountManager.id).where(
        AccountManager.project_id == project_id,
        AccountManager.is_active.is_(True),
        AccountManager.auth_status == "authorized",
    ).limit(1))
    if authorized_manager is None:
        raise HTTPException(status_code=409, detail="当前项目没有已授权的账户管家")

    running = db.scalar(select(BackgroundTask).where(
        BackgroundTask.project_id == project_id,
        BackgroundTask.task_type == "baidu_keyword_backfill",
        BackgroundTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
    ).order_by(desc(BackgroundTask.created_at)))
    if running:
        return envelope(request, {
            "task_id": str(running.id),
            "status": running.status.value,
            "message": "二跳账户关键词补齐任务已在运行",
        })

    task = BackgroundTask(
        project_id=project_id,
        task_type="baidu_keyword_backfill",
        current_node="queued",
        result={
            "request": {
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "scope": "keyword_daily_second_hop_material_exact",
                "report_type": 2602783,
                "account_type": AccountType.SECOND_HOP.value,
                "match_mode": "exact_after_deleted_marker_removal",
            },
            "state": {
                "cursor_account_id": 0,
                "processed_accounts": 0,
                "empty_accounts": 0,
                "report_pages": 0,
                "rows_seen": 0,
                "rows_matched": 0,
                "rows_unmatched": 0,
                "rows_non_keyword": 0,
                "deleted_marker_rows": 0,
                "rows_upserted": 0,
                "unmatched_keyword_samples": [],
                "failed_accounts": {},
                "consecutive_errors": 0,
                "total_accounts": account_count,
            },
        },
    )
    db.add(task)
    db.flush()
    db.add(AuditEvent(
        project_id=project_id,
        actor=actor.username,
        action="baidu.keyword_report.backfill.requested",
        target_type="background_task",
        target_id=str(task.id),
        summary="发起二跳账户百度关键词日报历史补齐",
        details={
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "account_type": AccountType.SECOND_HOP.value,
            "account_count": account_count,
            "material_keyword_count": material_keyword_count,
            "match_mode": "exact_after_deleted_marker_removal",
        },
    ))
    db.commit()
    from .worker import sync_baidu_keyword_backfill
    sync_baidu_keyword_backfill.delay(str(task.id))
    return envelope(request, {
        "task_id": str(task.id),
        "status": "pending",
        "scope": "keyword_daily_second_hop_material_exact",
        "date_from": date_from,
        "date_to": date_to,
        "account_type": AccountType.SECOND_HOP.value,
        "account_count": account_count,
        "material_keyword_count": material_keyword_count,
    })


@router.get("/projects/{project_id}/reports/daily.csv")
def export_daily_report(
    project_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = Query(default=None, max_length=100),
    manager_id: uuid.UUID | None = None,
    manager_ids: str | None = Query(default=None, max_length=4000),
    account_type: str | None = Query(default=None, max_length=30),
    account_types: str | None = Query(default=None, max_length=500),
    page_type: str | None = Query(default=None, max_length=30),
    page_types: str | None = Query(default=None, max_length=500),
    operator_name: str | None = Query(default=None, max_length=30),
    operator_names: str | None = Query(default=None, max_length=1000),
    lifecycle: str | None = Query(default=None, max_length=50),
    lifecycles: str | None = Query(default=None, max_length=500),
    cost_status: str | None = Query(default=None, max_length=30),
    cost_statuses: str | None = Query(default=None, max_length=500),
    account_names: str | None = Query(default=None, max_length=10000),
    sort_by: str = Query(
        default="spend",
        pattern="^(account_name|account_id|operator_name|manager_name|account_type|page_type|balance|impressions|clicks|spend|uv|copies|adds|cpc|uv_cost|copy_cost|add_cost|cash_spend|cash_copy_cost|cash_add_cost|cost_status)$",
    ),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    access = require_project_permission(db, project_id, actor, "reports", "manage")
    end = date_to or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    start = date_from or end
    report = build_daily_report(
        db,
        project_id,
        start,
        end,
        page=1,
        page_size=None,
        search=search,
        manager_id=manager_id,
        manager_ids=manager_ids,
        account_type=account_type,
        account_types=account_types,
        page_type=page_type,
        page_types=page_types,
        operator_name=operator_name,
        operator_names=operator_names,
        lifecycle=lifecycle,
        lifecycles=lifecycles,
        cost_status=cost_status,
        cost_statuses=cost_statuses,
        account_names=account_names,
        sort_by=sort_by,
        sort_order=sort_order,
        include_summary=False,
        allowed_operator_names=access.operator_names,
    )
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow(["日期", "账户", "账户ID", "余额", "成本判断", "运营", "账户类型", "页面类型", "推广页面", "推广链接", "返点", "钱柜账户", "展现", "点击", "消费", "UV", "复制", "加粉", "CPC", "UV成本", "复制成本", "加粉成本", "现金消费", "现金复制成本", "现金加粉成本"])
    for row in report["rows"]:
        writer.writerow([row[key] for key in ("date", "account_name", "account_id", "balance", "cost_status", "operator_name", "account_type", "page_type", "promotion_page", "promotion_link", "rebate_rate", "recharge_account", "impressions", "clicks", "spend", "uv", "copies", "adds", "cpc", "uv_cost", "copy_cost", "add_cost", "cash_spend", "cash_copy_cost", "cash_add_cost")])
    filename = f"search-report-{start}-{end}.csv"
    return Response(output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/projects/{project_id}/reports/daily.xlsx")
def download_daily_report(
    project_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = Query(default=None, max_length=100),
    manager_id: uuid.UUID | None = None,
    manager_ids: str | None = Query(default=None, max_length=4000),
    account_type: str | None = Query(default=None, max_length=30),
    account_types: str | None = Query(default=None, max_length=500),
    page_type: str | None = Query(default=None, max_length=30),
    page_types: str | None = Query(default=None, max_length=500),
    operator_name: str | None = Query(default=None, max_length=30),
    operator_names: str | None = Query(default=None, max_length=1000),
    lifecycle: str | None = Query(default=None, max_length=50),
    lifecycles: str | None = Query(default=None, max_length=500),
    cost_status: str | None = Query(default=None, max_length=30),
    cost_statuses: str | None = Query(default=None, max_length=500),
    account_names: str | None = Query(default=None, max_length=10000),
    sort_by: str = Query(
        default="spend",
        pattern="^(account_name|account_id|operator_name|manager_name|account_type|page_type|balance|impressions|clicks|spend|uv|copies|adds|cpc|uv_cost|copy_cost|add_cost|cash_spend|cash_copy_cost|cash_add_cost|cost_status)$",
    ),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    project = require_project(db, project_id)
    access = require_project_permission(db, project_id, actor, "reports", "manage")
    end = date_to or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    start = date_from or end
    if start > end or (end - start).days > 366:
        raise HTTPException(status_code=400, detail="报表日期范围无效或超过 366 天")
    report = build_daily_report(
        db,
        project_id,
        start,
        end,
        page=1,
        page_size=None,
        search=search,
        manager_id=manager_id,
        manager_ids=manager_ids,
        account_type=account_type,
        account_types=account_types,
        page_type=page_type,
        page_types=page_types,
        operator_name=operator_name,
        operator_names=operator_names,
        lifecycle=lifecycle,
        lifecycles=lifecycles,
        cost_status=cost_status,
        cost_statuses=cost_statuses,
        account_names=account_names,
        sort_by=sort_by,
        sort_order=sort_order,
        include_summary=False,
        allowed_operator_names=access.operator_names,
    )
    content = build_daily_report_xlsx(report["rows"])
    filename = f"{project.name}_数据报表_{start}_{end}.xlsx"
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": attachment_header(filename)},
    )


def serialize_hduofen_capture_task(task: BackgroundTask) -> dict:
    result = task.result if isinstance(task.result, dict) else {}
    request_details = result.get("request") if isinstance(result.get("request"), dict) else {}
    capture = result.get("capture") if isinstance(result.get("capture"), dict) else {}
    captures = capture.get("captures") if isinstance(capture.get("captures"), list) else []
    return {
        "id": str(task.id),
        "status": task.status.value,
        "current_node": task.current_node,
        "progress": task.progress,
        "date_from": request_details.get("date_from"),
        "date_to": request_details.get("date_to"),
        "created_at": task.created_at,
        "heartbeat_at": task.heartbeat_at,
        "last_error": task.last_error,
        "ingestion": capture.get("ingestion") if isinstance(capture.get("ingestion"), dict) else {},
        "captures": [
            {
                key: item.get(key)
                for key in ("name", "record_count", "expected_count", "complete")
            }
            for item in captures
            if isinstance(item, dict)
        ],
    }


@router.get("/projects/{project_id}/tracking/captures")
def list_hduofen_captures(
    project_id: uuid.UUID,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    rows = db.scalars(
        select(BackgroundTask)
        .where(
            BackgroundTask.project_id == project_id,
            BackgroundTask.task_type == "hduofen_capture",
        )
        .order_by(desc(BackgroundTask.created_at))
        .limit(limit)
    ).all()
    return envelope(request, [serialize_hduofen_capture_task(row) for row in rows])


@router.get("/projects/{project_id}/tracking/unmatched")
def list_hduofen_unmatched(
    project_id: uuid.UUID,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    base_filter = (
        HduofenEvent.project_id == project_id,
        HduofenEvent.metric_included.is_(False),
    )
    total = db.scalar(
        select(func.count()).select_from(HduofenEvent).where(*base_filter)
    ) or 0
    reason_rows = db.execute(
        select(HduofenEvent.exclusion_reason, func.count())
        .where(*base_filter)
        .group_by(HduofenEvent.exclusion_reason)
    ).all()
    rows = db.scalars(
        select(HduofenEvent)
        .where(*base_filter)
        .order_by(desc(HduofenEvent.event_at))
        .limit(limit)
    ).all()
    return envelope(request, {
        "total": total,
        "summary": {str(reason or "unknown"): count for reason, count in reason_rows},
        "items": [
            {
                "id": str(row.id),
                "source_type": row.source_type,
                "event_date": row.event_date,
                "baidu_account_id": row.baidu_account_id,
                "tracking_keyword": row.tracking_keyword,
                "exclusion_reason": row.exclusion_reason,
            }
            for row in rows
        ],
    })


@router.post("/projects/{project_id}/tracking/captures", status_code=202)
def queue_hduofen_capture(
    project_id: uuid.UUID,
    payload: HduofenCaptureRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if payload.date_from > payload.date_to:
        raise HTTPException(status_code=400, detail="开始日期不能晚于结束日期")
    if payload.date_to > today:
        raise HTTPException(status_code=400, detail="结束日期不能晚于今天")
    if (payload.date_to - payload.date_from).days > 30:
        raise HTTPException(status_code=400, detail="单次最多获取连续 31 天数据")
    if not settings.hduofen_capture_enabled:
        raise HTTPException(status_code=409, detail="好多粉运行时采集总开关未开启")
    if not settings.hduofen_username or not settings.hduofen_password:
        raise HTTPException(status_code=409, detail="好多粉登录凭据未配置")

    active_task = db.scalar(
        select(BackgroundTask).where(
            BackgroundTask.project_id == project_id,
            BackgroundTask.task_type == "hduofen_capture",
            BackgroundTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
        )
    )
    if active_task is not None:
        raise HTTPException(status_code=409, detail="当前项目已有好多粉采集任务正在执行")

    request_details = {
        "date_from": payload.date_from.isoformat(),
        "date_to": payload.date_to.isoformat(),
    }
    task = BackgroundTask(
        project_id=project_id,
        task_type="hduofen_capture",
        status=TaskStatus.PENDING,
        current_node="queued",
        progress=0,
        result={"request": request_details},
    )
    db.add(task)
    db.flush()
    add_audit(
        db,
        project_id,
        actor,
        "hduofen.capture.queue",
        "background_task",
        "提交好多粉日期采集任务",
        str(task.id),
        request_details,
    )
    db.commit()
    db.refresh(task)

    from .worker import capture_hduofen_for_task

    capture_hduofen_for_task.delay(
        str(task.id),
        str(project_id),
        request_details["date_from"],
        request_details["date_to"],
    )
    return envelope(request, {
        "task_id": str(task.id),
        "status": "queued",
        **request_details,
    })


def preference_defaults(key: str) -> dict:
    defaults = {
        "tracking": {"enabled": False, "interval_minutes": 60, "attribution_window_hours": 72},
        "settings": {"report_refresh_minutes": 60, "timezone": "Asia/Shanghai", "automation_guard": True},
        ACCOUNT_JUDGMENT_PREFERENCE_KEY: default_account_judgment_preference(),
        KEYWORD_TIER_PREFERENCE_KEY: KeywordTierRuleConfig().model_dump(mode="json"),
        AD_BUILD_REGION_PREFERENCE_KEY: default_ad_build_region_preference(),
    }
    return defaults[key]


def _ad_build_plan_settings_data(
    db: Session,
    project_id: uuid.UUID,
    *,
    refresh_material_plans: bool = False,
) -> dict:
    published = load_plan_repeat_counts(db, project_id)
    draft = load_plan_repeat_counts_for_key(
        db,
        project_id,
        AD_BUILD_PLAN_REPEATS_DRAFT_KEY,
    )
    configured = draft if draft else published
    draft_row = db.scalar(select(ProjectPreference).where(
        ProjectPreference.project_id == project_id,
        ProjectPreference.key == AD_BUILD_PLAN_REPEATS_DRAFT_KEY,
    ))
    published_row = db.scalar(select(ProjectPreference).where(
        ProjectPreference.project_id == project_id,
        ProjectPreference.key == AD_BUILD_PLAN_REPEATS_KEY,
    ))
    rows = db.execute(
        select(MaterialKeyword.campaign_name, func.count(MaterialKeyword.id))
        .where(
            MaterialKeyword.project_id == project_id,
            MaterialKeyword.is_blacklisted.is_(False),
        )
        .group_by(MaterialKeyword.campaign_name)
        .order_by(MaterialKeyword.campaign_name)
    ).all()
    material_counts = {
        str(campaign_name or "未命名计划"): int(keyword_count or 0)
        for campaign_name, keyword_count in rows
    }
    plan_names = (
        sorted(material_counts)
        if refresh_material_plans
        else sorted(configured)
    )
    items = []
    for name in plan_names:
        items.append({
            "campaign_name": name,
            "keyword_count": material_counts.get(name, 0),
            "repeat_count": configured.get(name, default_plan_repeat_count(name)),
            "is_configured": name in configured,
        })
    visible_row = draft_row or published_row
    return {
        "items": items,
        "plan_count": len(items),
        "has_draft": draft_row is not None,
        "has_published": published_row is not None,
        "updated_by": visible_row.updated_by if visible_row else None,
        "updated_at": visible_row.updated_at if visible_row else None,
    }


def _upsert_keyword_tier_preference(
    db: Session,
    project_id: uuid.UUID,
    config: dict,
    actor: str,
) -> ProjectPreference:
    normalized = KeywordTierRuleConfig.model_validate(config).model_dump(mode="json")
    row = db.scalar(select(ProjectPreference).where(
        ProjectPreference.project_id == project_id,
        ProjectPreference.key == KEYWORD_TIER_PREFERENCE_KEY,
    ))
    if row:
        row.value = normalized
        row.updated_by = actor
    else:
        row = ProjectPreference(
            project_id=project_id,
            key=KEYWORD_TIER_PREFERENCE_KEY,
            value=normalized,
            updated_by=actor,
        )
        db.add(row)
    return row


def _publish_keyword_tier_preference_to_strategy(
    db: Session,
    project_id: uuid.UUID,
    config: dict,
    actor: str,
) -> StrategyPolicy:
    """Keep manual grading and automatic keyword grading on one active config."""
    normalized = KeywordTierRuleConfig.model_validate(config).model_dump(mode="json")
    policy = _strategy_policy(db, project_id, KEYWORD_TIER_PREFERENCE_KEY)
    active = db.get(StrategyVersion, policy.active_version_id)
    if active and active.config == normalized:
        return policy

    stale_drafts = db.scalars(select(StrategyVersion).where(
        StrategyVersion.policy_id == policy.id,
        StrategyVersion.status == "draft",
    )).all()
    for draft in stale_drafts:
        db.delete(draft)

    next_version = int(db.scalar(
        select(func.max(StrategyVersion.version_number)).where(
            StrategyVersion.policy_id == policy.id,
        )
    ) or 0) + 1
    now = datetime.now(UTC)
    version = StrategyVersion(
        policy_id=policy.id,
        version_number=next_version,
        status="published",
        base_version_id=policy.active_version_id,
        config=normalized,
        config_hash=config_hash(normalized),
        created_by=actor,
        published_by=actor,
        published_at=now,
    )
    db.add(version)
    db.flush()
    policy.active_version_id = version.id
    policy.revision += 1
    return policy


def _strategy_policy(db: Session, project_id: uuid.UUID, strategy_key: str) -> StrategyPolicy:
    try:
        policies = ensure_strategy_policies(db, project_id)
    except StrategyConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row = next((item for item in policies if item.strategy_key == strategy_key), None)
    if row is None:
        raise HTTPException(status_code=404, detail="策略不存在")
    return row


def _strategy_dry_run_result(db: Session, project_id: uuid.UUID, strategy_key: str, config: dict) -> dict:
    if strategy_key in {"account_status", "cost_judgment", "realtime_closure"}:
        account_count = int(db.scalar(select(func.count(Account.id)).where(
            Account.project_id == project_id,
            Account.is_active.is_(True),
        )) or 0)
        action = {
            "account_status": "发布账户状态统一判定规则",
            "cost_judgment": "发布加粉/复制现金成本判定标准",
            "realtime_closure": "发布项目刷新与实时闭环规则",
        }[strategy_key]
        return {
            "candidate_count": account_count,
            "evaluated_count": account_count,
            "sample_account_ids": [],
            "action": action,
        }
    facts = judgment_facts(db, project_id)
    judgment_preference = load_account_judgment_preference(db, project_id)
    judgment_mode = judgment_preference["mode"]
    judgment_rules = judgment_preference[judgment_mode]
    conversion_name = "复制" if judgment_mode == "copy_cash" else "加粉"
    account_status = account_status_expression(facts)
    def judgment_query(statement):
        return (
            statement
            .outerjoin(facts.lifetime_metrics, facts.lifetime_metrics.c.account_id == Account.id)
            .outerjoin(facts.recent_metrics, facts.recent_metrics.c.account_id == Account.id)
            .outerjoin(facts.campaign_facts, facts.campaign_facts.c.account_id == Account.id)
        )
    base_filters = [
        Account.project_id == project_id, Account.is_active.is_(True),
        Account.eliminated_at.is_(None), account_status.in_(IN_USE_ACCOUNT_STATUSES),
    ]
    if strategy_key == "budget_reset":
        target = Decimal(config["target_budget"])
        minimum_difference = Decimal(str(config.get("minimum_difference", "0.01")))
        accounts = db.scalars(judgment_query(select(Account)).where(
            *base_filters,
            account_status.in_((
                ACCOUNT_STATUS_ALL_PAUSED,
                ACCOUNT_STATUS_BUDGET_LOW,
                ACCOUNT_STATUS_ONLINE,
            )),
            Account.current_budget.is_not(None),
        )).all()
        items = [
            item
            for item in accounts
            if needs_budget_reset(
                item.current_budget,
                target_budget=target,
                minimum_difference=minimum_difference,
            )
        ]
        return {"candidate_count": len(items), "sample_account_ids": [item.baidu_account_id for item in items[:20]], "action": f"到点将日预算重置为 {target} 账户币"}
    if strategy_key == "budget_append":
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        metrics = {
            account_id: (Decimal(spend or 0), int(adds or 0), int(copies or 0))
            for account_id, spend, adds, copies in db.execute(
                select(PerformanceDaily.account_id, func.sum(PerformanceDaily.spend), func.sum(PerformanceDaily.adds), func.sum(PerformanceDaily.copies))
                .where(PerformanceDaily.report_date == today).group_by(PerformanceDaily.account_id)
            ).all()
        }
        accounts = db.scalars(judgment_query(select(Account)).where(*base_filters, Account.current_budget.is_not(None))).all()
        items = [item for item in accounts if is_budget_append_candidate(
            spend=metrics.get(item.id, (Decimal(0), 0, 0))[0],
            conversions=metrics.get(item.id, (Decimal(0), 0, 0))[2 if judgment_mode == "copy_cash" else 1],
            cash_spend=calculate_cash_spend(metrics.get(item.id, (Decimal(0), 0, 0))[0], Decimal(item.rebate_rate) if item.rebate_rate is not None else None),
            require_cash_spend=True,
            current_budget=item.current_budget, cost_limit=Decimal(judgment_rules["cost_limit"]),
            utilization_limit=Decimal(config["utilization_limit"]),
        )]
        round_amounts = normalize_budget_append_round_amounts(config)
        unique_amounts = {str(item["amount"]) for item in round_amounts}
        action = (
            f"每轮追加 {round_amounts[0]['amount']} 元"
            if len(unique_amounts) == 1
            else "按第 1 至第 10 轮固定金额追加"
        )
        return {"candidate_count": len(items), "sample_account_ids": [item.baidu_account_id for item in items[:20]], "action": f"按{conversion_name}现金成本标准；{action}"}
    if strategy_key == "elimination":
        eligible_account_ids = judgment_query(select(Account.id)).where(
            *base_filters,
            func.coalesce(facts.campaign_facts.c.plan_count, 0)
            > func.coalesce(facts.campaign_facts.c.paused_plan_count, 0),
        )
        rows = db.execute(
            select(Account.baidu_account_id, Account.rebate_rate, func.coalesce(func.sum(PerformanceDaily.spend), 0), func.coalesce(func.sum(PerformanceDaily.adds), 0), func.coalesce(func.sum(PerformanceDaily.copies), 0))
            .outerjoin(PerformanceDaily, PerformanceDaily.account_id == Account.id)
            .where(Account.id.in_(eligible_account_ids)).group_by(Account.id, Account.baidu_account_id, Account.rebate_rate).order_by(Account.baidu_account_id)
        ).all()
        spend_limit = Decimal(judgment_rules["cold_start_spend_limit"])
        cost_limit = Decimal(judgment_rules["cost_limit"])
        matched_accounts = []
        for account_id, rebate_rate, spend, adds, copies in rows:
            spend_value = Decimal(spend or 0)
            conversions = int(copies or 0) if judgment_mode == "copy_cash" else int(adds or 0)
            reason = elimination_reason(
                spend_value,
                conversions,
                spend_without_add_limit=spend_limit,
                add_cost_limit=cost_limit,
                cash_spend=calculate_cash_spend(spend_value, Decimal(rebate_rate) if rebate_rate is not None else None),
                require_cash_spend=True,
                conversion_label=conversion_name,
            )
            if reason:
                matched_accounts.append(account_id)
        return {
            "candidate_count": len(matched_accounts),
            "matched_count": len(matched_accounts),
            "sample_account_ids": matched_accounts[:20],
            "action": f"按{conversion_name}现金成本标准，命中后直接暂停账户全部计划",
        }
    rules = KeywordTierRuleConfig.model_validate(config)
    performance_scope = keyword_tier_performance_scope(project_id)
    rows = db.execute(
        select(MaterialKeyword.campaign_name, MaterialKeyword.is_blacklisted, performance_scope.c.performance_rows, performance_scope.c.spend, performance_scope.c.copies, performance_scope.c.adds)
        .outerjoin(performance_scope, performance_scope.c.keyword_text == MaterialKeyword.keyword_text)
        .where(MaterialKeyword.project_id == project_id)
    ).all()
    changed = 0
    for row in rows:
        if row.is_blacklisted or not row.performance_rows:
            continue
        if classify_keyword(has_performance=True, spend=row.spend, copies=row.copies, adds=row.adds, rules=rules) != row.campaign_name:
            changed += 1
    return {"candidate_count": changed, "evaluated_count": len(rows), "action": "仅显示分级变化，不自动应用"}


@router.get("/projects/{project_id}/strategies")
def list_project_strategies(project_id: uuid.UUID, request: Request, db: Session = Depends(get_db), _: Actor = Depends(current_actor)):
    require_project(db, project_id)
    rows = ensure_strategy_policies(db, project_id)
    db.commit()
    return envelope(request, [strategy_payload(db, row) for row in rows])


@router.get("/projects/{project_id}/strategies/{strategy_key}")
def get_project_strategy(project_id: uuid.UUID, strategy_key: str, request: Request, db: Session = Depends(get_db), _: Actor = Depends(current_actor)):
    require_project(db, project_id)
    row = _strategy_policy(db, project_id, strategy_key)
    db.commit()
    return envelope(request, strategy_payload(db, row))


@router.put("/projects/{project_id}/strategies/{strategy_key}/draft")
def update_project_strategy_draft(project_id: uuid.UUID, strategy_key: str, payload: StrategyDraftUpdate, request: Request, db: Session = Depends(get_db), actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR))):
    require_project(db, project_id)
    policy = _strategy_policy(db, project_id, strategy_key)
    try:
        draft = save_draft(db, policy, config=payload.config, expected_revision=payload.expected_revision, actor=actor.username)
    except RuntimeError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="策略已被其他用户修改，请刷新后比较") from exc
    except StrategyConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    add_audit(db, project_id, actor, "strategy.draft.save", "strategy_policy", "保存策略草稿", str(policy.id), {"strategy_key": strategy_key, "config_hash": draft.config_hash})
    db.commit()
    db.refresh(policy)
    db.refresh(draft)
    return envelope(request, strategy_payload(db, policy))


@router.post("/projects/{project_id}/strategies/{strategy_key}/validate")
def validate_project_strategy(project_id: uuid.UUID, strategy_key: str, payload: StrategyDraftUpdate, request: Request, db: Session = Depends(get_db), _: Actor = Depends(current_actor)):
    require_project(db, project_id)
    policy = _strategy_policy(db, project_id, strategy_key)
    if policy.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="策略版本已变化")
    try:
        normalized = validate_strategy_config(strategy_key, payload.config)
    except StrategyConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return envelope(request, {"valid": True, "config": normalized})


@router.post("/projects/{project_id}/strategies/{strategy_key}/dry-run")
def dry_run_project_strategy(project_id: uuid.UUID, strategy_key: str, request: Request, db: Session = Depends(get_db), actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR))):
    require_project(db, project_id)
    policy = _strategy_policy(db, project_id, strategy_key)
    draft = db.scalar(select(StrategyVersion).where(StrategyVersion.policy_id == policy.id, StrategyVersion.status == "draft"))
    version = draft or db.get(StrategyVersion, policy.active_version_id)
    if version is None:
        raise HTTPException(status_code=409, detail="策略没有可试运行版本")
    result = _strategy_dry_run_result(db, project_id, strategy_key, version.config)
    evaluation = StrategyEvaluation(policy_id=policy.id, version_id=version.id, config_hash=version.config_hash, result=result, evaluated_by=actor.username)
    db.add(evaluation)
    add_audit(db, project_id, actor, "strategy.dry_run", "strategy_policy", "试运行策略", str(policy.id), {"strategy_key": strategy_key, "candidate_count": result["candidate_count"]})
    db.commit()
    db.refresh(evaluation)
    return envelope(request, {"id": str(evaluation.id), "config_hash": evaluation.config_hash, "result": result, "created_at": evaluation.created_at})


@router.post("/projects/{project_id}/strategies/{strategy_key}/publish")
def publish_project_strategy(project_id: uuid.UUID, strategy_key: str, payload: StrategyPublishRequest, request: Request, db: Session = Depends(get_db), actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR))):
    require_project(db, project_id)
    policy = _strategy_policy(db, project_id, strategy_key)
    if policy.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="策略已被其他用户修改，请刷新后比较")
    draft = db.scalar(select(StrategyVersion).where(StrategyVersion.policy_id == policy.id, StrategyVersion.status == "draft"))
    evaluation = db.get(StrategyEvaluation, payload.evaluation_id)
    if draft is None or evaluation is None or evaluation.policy_id != policy.id or evaluation.version_id != draft.id or evaluation.config_hash != draft.config_hash:
        raise HTTPException(status_code=409, detail="草稿必须使用当前参数重新试运行后才能发布")
    draft.status = "published"
    draft.published_by = actor.username
    draft.published_at = datetime.now(UTC)
    policy.active_version_id = draft.id
    policy.revision += 1
    if strategy_key == KEYWORD_TIER_PREFERENCE_KEY:
        _upsert_keyword_tier_preference(db, project_id, draft.config, actor.username)
    if strategy_key in {"cost_judgment", "realtime_closure"}:
        preference_key = (
            ACCOUNT_JUDGMENT_PREFERENCE_KEY
            if strategy_key == "cost_judgment"
            else "settings"
        )
        preference = db.scalar(select(ProjectPreference).where(
            ProjectPreference.project_id == project_id,
            ProjectPreference.key == preference_key,
        ))
        if preference:
            preference.value = draft.config
            preference.updated_by = actor.username
            flag_modified(preference, "value")
        else:
            db.add(ProjectPreference(
                project_id=project_id,
                key=preference_key,
                value=draft.config,
                updated_by=actor.username,
            ))
    add_audit(db, project_id, actor, "strategy.publish", "strategy_policy", "发布策略版本", str(policy.id), {"strategy_key": strategy_key, "version": draft.version_number, "config_hash": draft.config_hash})
    db.commit()
    db.refresh(policy)
    return envelope(request, strategy_payload(db, policy))


@router.get("/projects/{project_id}/strategies/{strategy_key}/versions")
def list_project_strategy_versions(project_id: uuid.UUID, strategy_key: str, request: Request, db: Session = Depends(get_db), _: Actor = Depends(current_actor)):
    require_project(db, project_id)
    policy = _strategy_policy(db, project_id, strategy_key)
    rows = db.scalars(select(StrategyVersion).where(StrategyVersion.policy_id == policy.id, StrategyVersion.status == "published").order_by(StrategyVersion.version_number.desc())).all()
    return envelope(request, [serialize_version(row) for row in rows])


@router.post("/projects/{project_id}/strategies/{strategy_key}/restore-draft")
def restore_project_strategy_draft(project_id: uuid.UUID, strategy_key: str, payload: StrategyRestoreDraftRequest, request: Request, db: Session = Depends(get_db), actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR))):
    require_project(db, project_id)
    policy = _strategy_policy(db, project_id, strategy_key)
    source = db.scalar(select(StrategyVersion).where(StrategyVersion.id == payload.version_id, StrategyVersion.policy_id == policy.id, StrategyVersion.status == "published"))
    if source is None:
        raise HTTPException(status_code=404, detail="历史版本不存在")
    try:
        save_draft(db, policy, config=source.config, expected_revision=payload.expected_revision, actor=actor.username)
    except RuntimeError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="策略已被其他用户修改，请刷新后比较") from exc
    add_audit(db, project_id, actor, "strategy.restore_draft", "strategy_policy", "从历史版本创建草稿", str(policy.id), {"strategy_key": strategy_key, "source_version": source.version_number})
    db.commit()
    db.refresh(policy)
    return envelope(request, strategy_payload(db, policy))


@router.get("/baidu-regions")
def get_baidu_regions(request: Request, _: Actor = Depends(current_actor)):
    return envelope(request, baidu_region_catalog())


@router.get("/projects/{project_id}/ad-build-plan-settings")
def get_ad_build_plan_settings(
    project_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    _: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    return envelope(request, _ad_build_plan_settings_data(db, project_id))


@router.get("/projects/{project_id}/ad-build-plan-settings/material-plans")
def get_ad_build_material_plans(
    project_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    _: Actor = Depends(current_actor),
):
    require_project(db, project_id)
    return envelope(
        request,
        _ad_build_plan_settings_data(
            db,
            project_id,
            refresh_material_plans=True,
        ),
    )


@router.put("/projects/{project_id}/ad-build-plan-settings")
def update_ad_build_plan_settings(
    project_id: uuid.UUID,
    payload: AdBuildPlanSettingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    available_names = set(db.scalars(
        select(MaterialKeyword.campaign_name)
        .where(
            MaterialKeyword.project_id == project_id,
            MaterialKeyword.is_blacklisted.is_(False),
        )
        .distinct()
    ).all())
    submitted_names = {item.campaign_name.strip() for item in payload.plans}
    unknown = sorted(submitted_names - available_names)
    if unknown:
        raise HTTPException(
            status_code=409,
            detail=f"物料中心已不存在这些计划：{'、'.join(unknown)}，请重新读取计划",
        )
    value = {
        "plans": [
            {
                "campaign_name": item.campaign_name.strip(),
                "repeat_count": item.repeat_count,
            }
            for item in payload.plans
        ]
    }
    row = db.scalar(select(ProjectPreference).where(
        ProjectPreference.project_id == project_id,
        ProjectPreference.key == AD_BUILD_PLAN_REPEATS_DRAFT_KEY,
    ))
    if row:
        row.value = value
        row.updated_by = actor.username
    else:
        row = ProjectPreference(
            project_id=project_id,
            key=AD_BUILD_PLAN_REPEATS_DRAFT_KEY,
            value=value,
            updated_by=actor.username,
        )
        db.add(row)
    add_audit(
        db,
        project_id,
        actor,
        "ad_build.plan_settings.draft_update",
        "project_preference",
        "保存搭建计划单元重复次数草稿",
        AD_BUILD_PLAN_REPEATS_DRAFT_KEY,
        {"plans": value["plans"]},
    )
    db.commit()
    return envelope(request, _ad_build_plan_settings_data(db, project_id))


@router.post("/projects/{project_id}/ad-build-plan-settings/publish")
def publish_ad_build_plan_settings(
    project_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    draft = db.scalar(select(ProjectPreference).where(
        ProjectPreference.project_id == project_id,
        ProjectPreference.key == AD_BUILD_PLAN_REPEATS_DRAFT_KEY,
    ))
    if draft is None:
        raise HTTPException(status_code=409, detail="当前没有待发布的搭建设置草稿")
    published = db.scalar(select(ProjectPreference).where(
        ProjectPreference.project_id == project_id,
        ProjectPreference.key == AD_BUILD_PLAN_REPEATS_KEY,
    ))
    if published:
        published.value = draft.value
        published.updated_by = actor.username
    else:
        published = ProjectPreference(
            project_id=project_id,
            key=AD_BUILD_PLAN_REPEATS_KEY,
            value=draft.value,
            updated_by=actor.username,
        )
        db.add(published)
    published_value = draft.value
    db.delete(draft)
    add_audit(
        db,
        project_id,
        actor,
        "ad_build.plan_settings.publish",
        "project_preference",
        "发布搭建计划单元重复次数",
        AD_BUILD_PLAN_REPEATS_KEY,
        published_value,
    )
    db.commit()
    return envelope(request, _ad_build_plan_settings_data(db, project_id))


@router.get("/projects/{project_id}/preferences/{key}")
def get_preference(project_id: uuid.UUID, key: str, request: Request, db: Session = Depends(get_db), _: Actor = Depends(current_actor)):
    require_project(db, project_id)
    if key not in {"tracking", "settings", ACCOUNT_JUDGMENT_PREFERENCE_KEY, KEYWORD_TIER_PREFERENCE_KEY, AD_BUILD_REGION_PREFERENCE_KEY}:
        raise HTTPException(status_code=404, detail="配置项不存在")
    row = db.scalar(select(ProjectPreference).where(ProjectPreference.project_id == project_id, ProjectPreference.key == key))
    value = {**preference_defaults(key), **(row.value if row else {})}
    if key == ACCOUNT_JUDGMENT_PREFERENCE_KEY:
        value = normalize_account_judgment_preference(value)
    if key == "tracking":
        value.update({
            "runtime_enabled": settings.hduofen_capture_enabled,
            "credentials_configured": bool(settings.hduofen_username and settings.hduofen_password),
            "session_key_configured": bool(settings.hduofen_session_encryption_key),
        })
    return envelope(request, value)


@router.patch("/projects/{project_id}/preferences/{key}")
def update_preference(
    project_id: uuid.UUID,
    key: str,
    payload: PreferenceUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    if key not in {"tracking", "settings", ACCOUNT_JUDGMENT_PREFERENCE_KEY, KEYWORD_TIER_PREFERENCE_KEY, AD_BUILD_REGION_PREFERENCE_KEY}:
        raise HTTPException(status_code=404, detail="配置项不存在")
    allowed = {
        "tracking": {"enabled", "interval_minutes", "attribution_window_hours"},
        "settings": {"report_refresh_minutes", "timezone", "automation_guard"},
        ACCOUNT_JUDGMENT_PREFERENCE_KEY: {"mode", "add_cash", "copy_cash"},
        KEYWORD_TIER_PREFERENCE_KEY: {
            "a_add_cost_max",
            "b_next_add_cost_max",
            "c_add_growth_factor",
            "c_projected_cost_max",
            "empty_spend_min",
            "d_spend_min",
        },
        AD_BUILD_REGION_PREFERENCE_KEY: {"region_target", "geo_location_status"},
    }[key]
    if not set(payload.value).issubset(allowed):
        raise HTTPException(status_code=400, detail="包含不允许修改的配置项")
    row = db.scalar(select(ProjectPreference).where(ProjectPreference.project_id == project_id, ProjectPreference.key == key))
    merged = {**preference_defaults(key), **(row.value if row else {}), **payload.value}
    if key == KEYWORD_TIER_PREFERENCE_KEY:
        try:
            merged = KeywordTierRuleConfig.model_validate(merged).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if key == ACCOUNT_JUDGMENT_PREFERENCE_KEY:
        try:
            merged = normalize_account_judgment_preference(merged)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if key == AD_BUILD_REGION_PREFERENCE_KEY:
        region_target = merged.get("region_target")
        if not isinstance(region_target, list) or not region_target or len(region_target) > 500:
            raise HTTPException(status_code=422, detail="推广地域必须选择 1 到 500 个省市")
        if any(not isinstance(value, int) or isinstance(value, bool) for value in region_target):
            raise HTTPException(status_code=422, detail="推广地域ID必须是整数")
        region_target = list(dict.fromkeys(region_target))
        unknown = sorted(set(region_target) - baidu_region_ids())
        if unknown:
            raise HTTPException(status_code=422, detail=f"包含未识别的百度省市地域ID：{unknown[:5]}")
        geo_location_status = merged.get("geo_location_status")
        if geo_location_status not in (0, 1):
            raise HTTPException(status_code=422, detail="地域匹配方式必须是 0 或 1")
        merged.update({
            "region_target": region_target,
            "geo_location_status": geo_location_status,
            "revision": int((row.value if row else {}).get("revision") or 0) + 1,
            "catalog_version": REGION_CATALOG_VERSION,
        })
    if key == "tracking" and merged.get("enabled") and not settings.hduofen_capture_enabled:
        raise HTTPException(status_code=409, detail="运行时采集总开关未开启，不能启用定时采集")
    if row:
        row.value = merged
        row.updated_by = actor.username
    else:
        row = ProjectPreference(project_id=project_id, key=key, value=merged, updated_by=actor.username)
        db.add(row)
    if key == KEYWORD_TIER_PREFERENCE_KEY:
        policy = _publish_keyword_tier_preference_to_strategy(
            db, project_id, merged, actor.username,
        )
        add_audit(
            db,
            project_id,
            actor,
            "strategy.keyword_tiers.sync",
            "strategy_policy",
            "同步关键词分级统一参数",
            str(policy.id),
            {"config_hash": config_hash(merged)},
        )
    add_audit(db, project_id, actor, f"preference.{key}.update", "project_preference", "更新项目配置", key, {"fields": sorted(payload.value)})
    db.commit()
    return envelope(request, merged)


@router.get("/projects/{project_id}/audit-events")
def list_audit_events(project_id: uuid.UUID, request: Request, db: Session = Depends(get_db), _: Actor = Depends(current_actor)):
    require_project(db, project_id)
    rows = db.scalars(select(AuditEvent).where(AuditEvent.project_id == project_id).order_by(desc(AuditEvent.created_at)).limit(200)).all()
    return envelope(request, [{
        "id": str(row.id), "actor": row.actor, "action": row.action,
        "target_type": row.target_type, "target_id": row.target_id,
        "summary": row.summary, "details": row.details, "created_at": row.created_at,
    } for row in rows])


@router.get("/projects/{project_id}/operations-center")
def project_operations_center(
    project_id: uuid.UUID,
    request: Request,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=10, le=100),
    db: Session = Depends(get_db),
    _: Actor = Depends(current_actor),
):
    """Return the four project-run views without performing any Baidu write."""
    require_project(db, project_id)
    reset_strategy_config = active_strategy_version(
        db, project_id, "budget_reset",
    ).config or DEFAULT_STRATEGY_CONFIGS["budget_reset"]
    reset_target_budget = Decimal(str(reset_strategy_config["target_budget"]))
    reset_minimum_difference = Decimal(str(reset_strategy_config.get("minimum_difference", "0.01")))
    reset_schedule_times = list(reset_strategy_config["schedule_times"])
    append_strategy_config = active_strategy_version(
        db, project_id, "budget_append",
    ).config or DEFAULT_STRATEGY_CONFIGS["budget_append"]
    append_round_amounts = normalize_budget_append_round_amounts(
        append_strategy_config,
    )
    append_utilization_limit = Decimal(str(append_strategy_config["utilization_limit"]))
    shanghai = ZoneInfo("Asia/Shanghai")
    today = datetime.now(shanghai).date()
    selected_to = date_to or today
    selected_from = date_from or (selected_to - timedelta(days=29))
    if selected_from > selected_to:
        raise HTTPException(status_code=422, detail="开始日期不能晚于结束日期")
    range_start = datetime.combine(selected_from, datetime.min.time(), tzinfo=shanghai).astimezone(UTC)
    range_end = (
        datetime.combine(selected_to, datetime.min.time(), tzinfo=shanghai) + timedelta(days=1)
    ).astimezone(UTC)

    now = datetime.now(UTC)
    settings_preference = db.scalar(select(ProjectPreference).where(
        ProjectPreference.project_id == project_id,
        ProjectPreference.key == "settings",
    ))
    settings_value = settings_preference.value if settings_preference and isinstance(settings_preference.value, dict) else {}
    loop_interval_minutes = max(15, min(1440, int(settings_value.get("report_refresh_minutes") or 60)))
    judgment_facts_value = judgment_facts(db, project_id)
    judgment_preference = load_account_judgment_preference(db, project_id)
    judgment_mode = judgment_preference["mode"]
    judgment_rules = judgment_preference[judgment_mode]
    conversion_name = "复制" if judgment_mode == "copy_cash" else "加粉"
    append_cost_limit = Decimal(str(judgment_rules["cost_limit"]))
    resolved_account_status = account_status_expression(judgment_facts_value)
    test_accounts = db.scalars(select(Account)
        .outerjoin(judgment_facts_value.lifetime_metrics, judgment_facts_value.lifetime_metrics.c.account_id == Account.id)
        .outerjoin(judgment_facts_value.recent_metrics, judgment_facts_value.recent_metrics.c.account_id == Account.id)
        .outerjoin(judgment_facts_value.campaign_facts, judgment_facts_value.campaign_facts.c.account_id == Account.id)
        .where(
        Account.project_id == project_id,
        resolved_account_status.in_((
            ACCOUNT_STATUS_ALL_PAUSED,
            ACCOUNT_STATUS_BUDGET_LOW,
            ACCOUNT_STATUS_ONLINE,
        )),
        Account.is_active.is_(True),
        Account.eliminated_at.is_(None),
    )).all()
    test_account_count = len(test_accounts)
    append_accounts = db.scalars(select(Account)
        .outerjoin(judgment_facts_value.lifetime_metrics, judgment_facts_value.lifetime_metrics.c.account_id == Account.id)
        .outerjoin(judgment_facts_value.recent_metrics, judgment_facts_value.recent_metrics.c.account_id == Account.id)
        .outerjoin(judgment_facts_value.campaign_facts, judgment_facts_value.campaign_facts.c.account_id == Account.id)
        .where(
        Account.project_id == project_id,
        resolved_account_status.in_(IN_USE_ACCOUNT_STATUSES),
        Account.is_active.is_(True),
        Account.eliminated_at.is_(None),
        Account.current_budget.is_not(None),
    )).all()

    loop_sources = (
        "baidu_account_report",
        "hduofen_capture",
        "baidu_budget_snapshot",
        "baidu_creative_review",
    )
    watermark_rows = db.scalars(select(SyncWatermark).where(
        SyncWatermark.scope == str(project_id),
        SyncWatermark.source.in_(loop_sources),
    )).all()
    watermarks = {row.source: row for row in watermark_rows}

    def watermark_state(source: str) -> dict:
        row = watermarks.get(source)
        fresh = bool(
            row
            and row.status == "succeeded"
            and snapshot_is_fresh(row.snapshot_at, now=now)
        )
        return {
            "status": row.status if row else "missing",
            "snapshot_at": row.snapshot_at if row else None,
            "fresh": fresh,
            "message": row.message if row else None,
        }

    loop_watermarks = {
        source: watermark_state(source) for source in loop_sources
    }
    baidu_watermark = loop_watermarks["baidu_account_report"]["snapshot_at"]
    hduofen_watermark = loop_watermarks["hduofen_capture"]["snapshot_at"]
    budget_watermark = loop_watermarks["baidu_budget_snapshot"]["snapshot_at"]
    creative_watermark = loop_watermarks["baidu_creative_review"]["snapshot_at"]
    blacklisted_count = int(db.scalar(
        select(func.count(Account.id)).where(
            Account.project_id == project_id,
            or_(
                Account.eliminated_at.is_not(None),
                Account.lifecycle_stage == "已淘汰",
                Account.lifecycle_override == "已淘汰",
            ),
        )
    ) or 0)

    performance_totals = (
        select(
            PerformanceDaily.account_id.label("account_id"),
            func.coalesce(func.sum(PerformanceDaily.spend), 0).label("spend"),
            func.coalesce(func.sum(PerformanceDaily.adds), 0).label("adds"),
            func.coalesce(func.sum(PerformanceDaily.copies), 0).label("copies"),
        )
        .group_by(PerformanceDaily.account_id)
        .subquery()
    )
    eliminated_time = func.coalesce(Account.eliminated_at, Account.lifecycle_evaluated_at)
    elimination_filters = (
        Account.project_id == project_id,
        Account.lifecycle_stage == "已淘汰",
        eliminated_time >= range_start,
        eliminated_time < range_end,
    )
    eliminated_total = int(db.scalar(
        select(func.count(Account.id)).where(*elimination_filters)
    ) or 0)
    eliminated_rows = db.execute(
        select(
            Account,
            func.coalesce(performance_totals.c.spend, 0),
            func.coalesce(performance_totals.c.adds, 0),
            func.coalesce(performance_totals.c.copies, 0),
        )
        .outerjoin(performance_totals, performance_totals.c.account_id == Account.id)
        .where(*elimination_filters)
        .order_by(desc(Account.eliminated_at), Account.login_name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    eliminated = []
    for account, spend_value, adds_value, copies_value in eliminated_rows:
        spend = Decimal(spend_value or 0)
        adds = int(adds_value or 0)
        copies = int(copies_value or 0)
        conversions = copies if judgment_mode == "copy_cash" else adds
        cash_spend = calculate_cash_spend(spend, Decimal(account.rebate_rate) if account.rebate_rate is not None else None)
        eliminated.append({
            "id": str(account.id),
            "eliminated_at": account.eliminated_at or account.lifecycle_evaluated_at,
            "account_id": account.baidu_account_id,
            "account_name": account.login_name,
            "spend": spend,
            "adds": adds,
            "add_cost": safe_divide(spend, adds),
            "conversions": conversions,
            "conversion_cost": safe_divide(cash_spend, conversions) if cash_spend is not None else None,
            "recharge_account": account.recharge_account,
            "reason": account.elimination_reason,
        })

    def budget_history(action: str, *, failures_only: bool = False) -> dict:
        history_filters = [
            AuditEvent.project_id == project_id,
            AuditEvent.action == action,
            AuditEvent.created_at >= range_start,
            AuditEvent.created_at < range_end,
        ]
        if failures_only:
            history_filters.append(AuditEvent.details["status"].astext == "failed")
        total = int(db.scalar(select(func.count(AuditEvent.id)).where(*history_filters)) or 0)
        rows = db.scalars(
            select(AuditEvent)
            .where(*history_filters)
            .order_by(desc(AuditEvent.created_at), desc(AuditEvent.id))
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
            "rows": [{
                "id": str(row.id),
                "created_at": row.created_at,
                "account_id": row.target_id,
                "account_name": row.details.get("account_name") or row.target_id or "—",
                "before_budget": row.details.get("before_budget"),
                "after_budget": row.details.get("after_budget"),
                "append_round": row.details.get("append_round"),
                "append_amount": row.details.get("append_amount"),
                "status": row.details.get("status") or "succeeded",
                "error": row.details.get("error") or row.details.get("error_type"),
            } for row in rows],
        }

    loop_status = (
        "healthy"
        if all(item["fresh"] for item in loop_watermarks.values())
        else "waiting_data"
    )
    budget_snapshot_available = True
    budget_snapshot_status = "ready"
    budget_snapshot_fresh_count = 0
    budget_snapshot_missing_count = 0
    append_budget_snapshot = budget_snapshot_coverage(
        (account.budget_snapshot_at for account in append_accounts),
        now=now,
    )
    append_budget_snapshot_available = bool(append_budget_snapshot["available"])
    reset_candidate_count = (
        sum(
            1
            for account in test_accounts
            if needs_budget_reset(
                account.current_budget,
                target_budget=reset_target_budget,
                minimum_difference=reset_minimum_difference,
            )
        )
    )
    today_metrics = {
        account_id: (Decimal(spend or 0), int(adds or 0), int(copies or 0))
        for account_id, spend, adds, copies in db.execute(
            select(
                PerformanceDaily.account_id,
                func.coalesce(func.sum(PerformanceDaily.spend), 0),
                func.coalesce(func.sum(PerformanceDaily.adds), 0),
                func.coalesce(func.sum(PerformanceDaily.copies), 0),
            )
            .where(PerformanceDaily.report_date == today)
            .group_by(PerformanceDaily.account_id)
        ).all()
    }
    append_candidate_count = (
        sum(
            1
            for account in append_accounts
            if is_budget_append_candidate(
                spend=today_metrics.get(account.id, (Decimal("0"), 0, 0))[0],
                conversions=today_metrics.get(account.id, (Decimal("0"), 0, 0))[2 if judgment_mode == "copy_cash" else 1],
                cash_spend=calculate_cash_spend(today_metrics.get(account.id, (Decimal("0"), 0, 0))[0], Decimal(account.rebate_rate) if account.rebate_rate is not None else None),
                require_cash_spend=True,
                current_budget=account.current_budget,
                cost_limit=append_cost_limit,
                utilization_limit=append_utilization_limit,
            )
        )
        if append_budget_snapshot_available
        else None
    )
    return envelope(request, {
        "loop_check": {
            "interval_minutes": loop_interval_minutes,
            "status": loop_status,
            "baidu_watermark": baidu_watermark,
            "hduofen_watermark": hduofen_watermark,
            "budget_watermark": budget_watermark,
            "creative_watermark": creative_watermark,
            "sources": loop_watermarks,
            "next_action": "数据齐全后评估预算与淘汰规则",
        },
        "budget_reset": {
            "schedule": reset_schedule_times[0],
            "target_budget": reset_target_budget,
            "scope": "账户状态为计划全停、预算不足或上线",
            "test_account_count": test_account_count,
            "candidate_count": reset_candidate_count,
            "budget_snapshot_available": budget_snapshot_available,
            "budget_snapshot_status": budget_snapshot_status,
            "budget_snapshot_fresh_count": budget_snapshot_fresh_count,
            "budget_snapshot_missing_count": budget_snapshot_missing_count,
            "only_changed_accounts": True,
            "writes_enabled": settings.baidu_writes_enabled,
            "history": budget_history("account.budget.reset", failures_only=True),
        },
        "budget_append": {
            "interval_minutes": 60,
            "cost_mode": judgment_mode,
            "conversion_label": conversion_name,
            "cost_limit": append_cost_limit,
            "add_cost_limit": append_cost_limit,
            "utilization_threshold": append_utilization_limit * Decimal("100"),
            "round_amounts": append_round_amounts,
            "candidate_count": append_candidate_count,
            "budget_snapshot_available": append_budget_snapshot_available,
            "budget_snapshot_status": str(append_budget_snapshot["status"]),
            "budget_snapshot_fresh_count": int(append_budget_snapshot["fresh_count"]),
            "budget_snapshot_missing_count": int(append_budget_snapshot["missing_count"]),
            "marginal_recheck": True,
            "writes_enabled": settings.baidu_writes_enabled,
            "history": budget_history("account.budget.append"),
        },
        "eliminations": {
            "cost_mode": judgment_mode,
            "conversion_label": conversion_name,
            "total": eliminated_total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (eliminated_total + page_size - 1) // page_size),
            "rows": eliminated,
        },
        "filters": {"date_from": selected_from, "date_to": selected_to},
        "blacklist": {
            "account_count": blacklisted_count,
            "regular_api_calls": "blocked",
            "final_archive": "淘汰次日仅补取前一天数据一次",
        },
    })


@router.post("/projects/{project_id}/automation/rules/{rule_id}/dry-run")
def project_dry_run(
    project_id: uuid.UUID,
    rule_id: str,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    require_project(db, project_id)
    summary = dashboard_summary(db, project_id)
    data_stale = bool(summary.data_freshness.get("snapshot_stale"))
    protected = data_stale
    result = {
        "rule_id": rule_id, "mode": "alert_only", "protected": protected,
        "data_quality": "stale" if data_stale else "fresh",
        "automatic_writes_allowed": not data_stale,
        "matches": [], "reason": "系统性数据水位异常，相关策略已暂停" if protected else (
            "数据水位不完整，本次仅试算且不会产生自动写入" if data_stale else "当前没有命中账户"
        ),
        "evaluated_at": datetime.now(UTC),
    }
    add_audit(db, project_id, actor, "automation.dry_run", "automation_rule", "执行自动化规则试运行", rule_id, {"protected": protected})
    db.commit()
    return envelope(request, result)


@router.post("/automation/rules/{rule_id}/dry-run")
def dry_run(rule_id: str, request: Request, db: Session = Depends(get_db), _: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR))):
    summary = dashboard_summary(db)
    protected = bool(summary.data_freshness.get("snapshot_stale"))
    return envelope(request, {"rule_id": rule_id, "mode": "alert_only", "protected": protected, "matches": [] if protected else [{"reason": "演示规则不执行任何百度修改"}]})
