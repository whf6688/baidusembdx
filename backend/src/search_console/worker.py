import hashlib
import json
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from celery import Celery
from celery.schedules import crontab
from sqlalchemy import and_, delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm.attributes import flag_modified

from baidu_platform_core import BaiduCallContext, BaiduPlatformClient, FernetTokenCipher, WritePolicy
from baidu_platform_core.errors import RateLimitError, TokenUnavailableError

from .baidu_reports import (
    KEYWORD_REPORT_PAGE_SIZE,
    build_account_report_payload,
    build_keyword_report_payload,
    extract_report_rows,
    extract_report_total_row_count,
    normalize_account_report_rows,
    upsert_account_report_facts,
    upsert_matched_keyword_report_facts,
)

from .config import get_settings
from .code_sync import (
    active_code_sync_task,
    create_code_sync_task,
    execute_code_sync,
)
from .account_lifecycle import (
    EMPTY,
    ELIMINATED,
    REFUND_DUE,
    TESTING,
    elimination_reason,
    subject_accounts_are_all_eliminated,
)
from .account_judgment import (
    COST_STATUS_COLD_START,
    IN_USE_ACCOUNT_STATUSES,
    account_status_expression,
    cost_judgment_expressions,
    judgment_facts,
    load_account_judgment_preference,
)
from .ad_builds import (
    WORKFLOW_VERSION,
    build_plan_pause_schedule,
    build_plan_pause_schedule_from_windows,
)
from .ad_build_executor import (
    ADGROUP_READBACK_DELAY_SECONDS,
    DelayedReadbackPending,
    ReadbackVerificationTimeout,
    execute_ad_build_cleanup,
    execute_ad_build_workflow,
)
from .creative_persistence import record_second_hop_creative_rejection
from .creatives import (
    extract_main_reason,
    select_random_creative_combinations,
)
from .budgets import (
    TARGET_DAILY_BUDGET,
    budget_snapshot_coverage,
    is_budget_append_candidate,
    needs_budget_reset,
    snapshot_is_fresh,
)
from .db import SessionLocal, engine
from .models import (
    AdBuildBatch,
    AdBuildJob,
    Account,
    AccountManager,
    AccountType,
    AuditEvent,
    BackgroundTask,
    CampaignCache,
    CampaignBatchSetting,
    OcpcProjectCache,
    CreativeAssignment,
    CreativeCombination,
    CreativeSegment,
    DailyDataStatus,
    FinancePaymentRecord,
    Operation,
    OperationStatus,
    PerformanceDaily,
    Project,
    ProjectPreference,
    ReferenceTemplateVersion,
    StrategyPolicy,
    StrategyVersion,
    StrategyScheduleRun,
    SyncWatermark,
    TaskStatus,
    UnmatchedKeywordPerformanceDaily,
    Role,
)
from .permissions import is_system_owner, require_account_scope, require_project_permission
from .security import Actor
from .strategies import active_strategy_version, budget_append_amount
from .task_guard import ProjectScopeTask
from .notifications import (
    create_low_balance_notifications,
    create_refund_notifications,
    reconcile_all_projects,
)
from .reference_templates import REFERENCE_ACCOUNT_ID, analyze_reference_snapshot, chunks
from .manager_balance import resolve_manager_recharge_account


def _task_requester_access(db, task: BackgroundTask, request_details: dict, module: str):
    username = str(request_details.get("requested_by") or "").strip()
    if not username or task.project_id is None:
        raise RuntimeError("任务缺少可复核的发起成员")
    probe = Actor(username=username, role=Role.OPERATOR)
    actor = Actor(
        username=username,
        role=Role.ADMIN if is_system_owner(probe) else Role.OPERATOR,
    )
    return require_project_permission(db, task.project_id, actor, module, "manage")


def _block_for_permission_change(db, task: BackgroundTask, exc: Exception) -> dict:
    task.status = TaskStatus.BLOCKED
    task.current_node = "permission_recheck"
    task.last_error = f"成员权限或账户范围已变化，任务安全阻断：{exc}"
    task.heartbeat_at = datetime.now(UTC)
    db.commit()
    return {"status": "permission_blocked", "reason": task.last_error}


settings = get_settings()
AD_BUILD_WORKFLOW_EXECUTOR_REGISTERED = True
BAIDU_ENDPOINTS = {
    "account.get": "json/sms/service/AccountService/getAccountInfo",
    "account.update": "json/sms/service/AccountService/updateAccountInfo",
    "mcc.accounts.get": "json/feed/v1/MccFeedService/getUserListByMccid",
    "campaign.get": "json/sms/service/CampaignService/getCampaign",
    "campaign.add": "json/sms/service/CampaignService/addCampaign",
    "campaign.update": "json/sms/service/CampaignService/updateCampaign",
    "campaign.delete": "json/sms/service/CampaignService/deleteCampaign",
    "adgroup.get": "json/sms/service/AdgroupService/getAdgroup",
    "adgroup.add": "json/sms/service/AdgroupService/addAdgroup",
    "adgroup.update": "json/sms/service/AdgroupService/updateAdgroup",
    "keyword.get": "json/sms/service/KeywordService/getWord",
    "keyword.add": "json/sms/service/KeywordService/addWord",
    "creative.get": "json/sms/service/CreativeService/getCreative",
    "creative.add": "json/sms/service/CreativeService/addCreative",
    "creative.delete": "json/sms/service/CreativeService/deleteCreative",
    "ocpc.get": "json/sms/service/OcpcService/getTargetPackageList",
    "ocpc.add": "json/sms/service/OcpcService/addTargetPackage",
    "ocpc.delete": "json/sms/service/OcpcService/deleteTargetPackage",
    "crowd.get": "json/sms/service/CrowdService/getCrowd",
    "crowd.add": "json/sms/service/CrowdService/addCrowd",
    "crowd.delete": "json/sms/service/CrowdService/deleteCrowd",
    "crowd.bind.get": "json/sms/service/CrowdBindService/getBind",
    "crowd.bind.add": "json/sms/service/CrowdBindService/addBind",
    "crowd.bind.delete": "json/sms/service/CrowdBindService/deleteBind",
    "report.get": "json/sms/service/OpenApiReportService/getReportData",
    "payment.records.get": "json/sms/service/PaymentService/getPaymentRecord",
}
celery_app = Celery("search_console", broker=settings.redis_url, backend=settings.redis_url, task_cls=ProjectScopeTask)
celery_app.conf.update(
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    timezone="Asia/Shanghai",
    enable_utc=True,
)


def rate_limit_retry_seconds(exc: RateLimitError) -> int:
    """Use the limiter/Baidu supplied delay instead of a fixed batch sleep."""
    return max(1, min(300, int(exc.retry_after_seconds)))


def baidu_result_rows(result: dict) -> list[dict]:
    candidate = result.get("data")
    if not isinstance(candidate, list):
        body = result.get("body")
        candidate = body.get("data") if isinstance(body, dict) else []
    return [row for row in candidate if isinstance(row, dict)] if isinstance(candidate, list) else []


def platform_client(*, write_enabled: bool | None = None) -> BaiduPlatformClient:
    cipher = FernetTokenCipher(settings.platform_token_encryption_key)
    return BaiduPlatformClient(
        database_url=settings.effective_platform_database_url,
        base_url=settings.baidu_api_base_url,
        write_policy=WritePolicy(
            enabled=settings.baidu_writes_enabled if write_enabled is None else write_enabled
        ),
        token_decryptor=cipher.decrypt,
        token_encryptor=cipher.encrypt,
        oauth_app_id=settings.baidu_app_id,
        oauth_app_secret=settings.baidu_app_secret,
        oauth_refresh_url=settings.baidu_oauth_refresh_token_url,
        endpoints=BAIDU_ENDPOINTS,
        write_timeout_seconds=settings.baidu_write_timeout_seconds,
    )


def call_context(account: Account, *, batch: str, idempotency_key: str) -> BaiduCallContext:
    return BaiduCallContext(
        app_code="search",
        baidu_application_code=settings.baidu_application_code,
        manager_login_name=account.manager_login_name,
        target_account_id=account.baidu_account_id,
        target_login_name=account.login_name,
        request_batch=batch,
        idempotency_key=idempotency_key,
    )


def checkpoint(db, task: BackgroundTask, node: str, progress: int) -> None:
    task.status = TaskStatus.RUNNING
    task.current_node = node
    task.progress = progress
    task.heartbeat_at = datetime.now(UTC)
    db.commit()


def update_project_watermark(
    db,
    *,
    source: str,
    project_id: uuid.UUID,
    status: str,
    message: str | None = None,
    source_at: datetime | None = None,
) -> SyncWatermark:
    watermark = db.scalar(select(SyncWatermark).where(
        SyncWatermark.source == source,
        SyncWatermark.scope == str(project_id),
    ))
    if watermark is None:
        watermark = SyncWatermark(source=source, scope=str(project_id))
        db.add(watermark)
    watermark.status = status
    watermark.message = message
    watermark.snapshot_at = datetime.now(UTC)
    if source_at is not None:
        watermark.source_at = source_at
    return watermark


def extract_account_info(result: dict) -> dict | None:
    """Return the first AccountService row across known Baidu response envelopes."""
    candidates = [result.get("data")]
    body = result.get("body")
    if isinstance(body, dict):
        candidates.extend([body.get("data"), body.get("accountInfo")])
    for candidate in candidates:
        if isinstance(candidate, list) and candidate and isinstance(candidate[0], dict):
            return candidate[0]
        if isinstance(candidate, dict):
            return candidate
    return None


@celery_app.task
def sync_account_details(
    project_id: str,
    manager_id: str,
    run_id: str | None = None,
    after_account_id: int = 0,
    processed: int = 0,
    updated: int = 0,
    failed: int = 0,
):
    """Compatibility no-op: a manager now represents one shared subject."""
    return {
        "status": "disabled",
        "reason": "manager_shared_subject",
        "run_id": run_id,
        "processed": 0,
        "updated": 0,
        "failed": 0,
    }


BUDGET_SNAPSHOT_TASK_TYPE = "baidu_budget_snapshot"
BUDGET_SNAPSHOT_BATCH_SIZE = 80


def _persist_budget_snapshot_state(
    db,
    task: BackgroundTask,
    *,
    request_details: dict,
    state: dict,
    total_accounts: int,
) -> None:
    processed = int(state.get("processed_accounts") or 0)
    task.result = {"request": request_details, "state": state}
    flag_modified(task, "result")
    task.status = TaskStatus.RUNNING
    task.current_node = "fetch_account_budget_snapshot"
    task.progress = min(95, int(processed * 95 / max(1, total_accounts)))
    task.heartbeat_at = datetime.now(UTC)
    update_project_watermark(
        db,
        source="baidu_budget_snapshot",
        project_id=task.project_id,
        status="running",
        message=f"processed {processed}/{total_accounts}",
    )
    db.commit()


@celery_app.task
def sync_project_budget_snapshot(task_id: str):
    task_uuid = uuid.UUID(task_id)
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_uuid)
        if task is None or task.project_id is None:
            return {"status": "task_missing"}
        if task.status == TaskStatus.SUCCEEDED:
            return {"status": "already_succeeded", "task_id": task_id}
        task_payload = task.result if isinstance(task.result, dict) else {}
        request_details = (
            task_payload.get("request")
            if isinstance(task_payload.get("request"), dict)
            else {}
        )
        state = (
            task_payload.get("state")
            if isinstance(task_payload.get("state"), dict)
            else {}
        )
        state.setdefault("cursor_account_id", 0)
        state.setdefault("processed_accounts", 0)
        state.setdefault("updated_accounts", 0)
        state.setdefault("failed_accounts", {})
        account_scope = (
            Account.project_id == task.project_id,
            Account.is_active.is_(True),
            effective_balance_lifecycle_condition(),
            api_eligible_account_condition(),
        )
        total_accounts = int(
            db.scalar(select(func.count(Account.id)).where(*account_scope)) or 0
        )
        accounts = db.scalars(
            select(Account)
            .where(
                *account_scope,
                Account.baidu_account_id > int(state["cursor_account_id"]),
            )
            .order_by(Account.baidu_account_id)
            .limit(BUDGET_SNAPSHOT_BATCH_SIZE)
        ).all()
        _persist_budget_snapshot_state(
            db,
            task,
            request_details=request_details,
            state=state,
            total_accounts=total_accounts,
        )
        client = platform_client()
        for account in accounts:
            try:
                result = client.execute_read(
                    context=call_context(
                        account,
                        batch=f"budget-snapshot:{task_id}",
                        idempotency_key="",
                    ),
                    service="account.get",
                    payload={
                        "accountFields": [
                            "userId",
                            "balance",
                            "budget",
                            "budgetType",
                            "userStat",
                        ]
                    },
                )
                info = extract_account_info(result)
                if info is None or info.get("budget") is None:
                    raise ValueError("Baidu account response did not include budget")
                captured_at = datetime.now(UTC)
                account.current_budget = Decimal(str(info["budget"]))
                account.budget_type = int(info.get("budgetType") or 0)
                if info.get("userStat") is not None:
                    account.remote_status_code = int(info["userStat"])
                    account.remote_status_at = captured_at
                if info.get("balance") is not None:
                    account.balance = Decimal(str(info["balance"]))
                account.budget_snapshot_at = captured_at
                account.last_synced_at = captured_at
                state["updated_accounts"] = int(state["updated_accounts"]) + 1
            except RateLimitError as exc:
                task = db.get(BackgroundTask, task_uuid)
                _persist_budget_snapshot_state(
                    db,
                    task,
                    request_details=request_details,
                    state=state,
                    total_accounts=total_accounts,
                )
                sync_project_budget_snapshot.apply_async(
                    args=[task_id], countdown=rate_limit_retry_seconds(exc)
                )
                return {
                    "status": "rate_limited",
                    "task_id": task_id,
                    "processed": state["processed_accounts"],
                }
            except TokenUnavailableError as exc:
                task.status = TaskStatus.BLOCKED
                task.current_node = "budget_snapshot_blocked"
                task.last_error = str(exc)[:500]
                update_project_watermark(
                    db,
                    source="baidu_budget_snapshot",
                    project_id=task.project_id,
                    status="blocked",
                    message=task.last_error,
                )
                db.commit()
                return {"status": "blocked", "reason": task.last_error}
            except Exception as exc:
                failures = state["failed_accounts"]
                failures[str(account.baidu_account_id)] = (
                    f"{type(exc).__name__}: {str(exc)[:180]}"
                )
            state["processed_accounts"] = int(state["processed_accounts"]) + 1
            state["cursor_account_id"] = account.baidu_account_id

        task = db.get(BackgroundTask, task_uuid)
        _persist_budget_snapshot_state(
            db,
            task,
            request_details=request_details,
            state=state,
            total_accounts=total_accounts,
        )
        if accounts and int(state["processed_accounts"]) < total_accounts:
            sync_project_budget_snapshot.apply_async(args=[task_id], countdown=1)
            return {
                "status": "continued",
                "task_id": task_id,
                "processed": state["processed_accounts"],
                "total": total_accounts,
            }

        failures = state.get("failed_accounts") or {}
        completed_at = datetime.now(UTC)
        task.status = TaskStatus.SUCCEEDED if not failures else TaskStatus.FAILED
        task.current_node = (
            "budget_snapshot_complete" if not failures else "budget_snapshot_incomplete"
        )
        task.progress = 100
        task.heartbeat_at = completed_at
        task.last_error = (
            None
            if not failures
            else f"{len(failures)} account budget snapshots failed"
        )
        task.result = {"request": request_details, "state": state}
        flag_modified(task, "result")
        update_project_watermark(
            db,
            source="baidu_budget_snapshot",
            project_id=task.project_id,
            status="succeeded" if not failures else "failed",
            message=(
                f"updated {state['updated_accounts']}/{total_accounts}; "
                f"failed {len(failures)}"
            ),
            source_at=completed_at if not failures else None,
        )
        db.add(AuditEvent(
            project_id=task.project_id,
            actor="baidu-budget-worker",
            action="account.budget_snapshot.complete",
            target_type="background_task",
            target_id=task_id,
            summary="账户当前预算快照同步完成",
            details={
                "trigger": request_details.get("trigger"),
                "processed_accounts": state["processed_accounts"],
                "updated_accounts": state["updated_accounts"],
                "failed_accounts": len(failures),
            },
        ))
        low_balance_count = create_low_balance_notifications(
            db,
            task.project_id,
            snapshot_started_at=task.created_at,
        )
        db.commit()
        if not failures and request_details.get("trigger") == "midnight_reset":
            queue_budget_automation.delay(
                "reset", str(task.project_id), request_details.get("strategy_version_id"),
                request_details.get("schedule_run_id"),
            )
        return {
            "status": task.status.value,
            "task_id": task_id,
            "low_balance_notifications": low_balance_count,
            **state,
        }


@celery_app.task
def queue_due_budget_snapshot_syncs(
    trigger: str = "hourly_refresh",
    project_id: str | None = None,
    strategy_version_id: str | None = None,
    schedule_run_id: str | None = None,
):
    queued: list[str] = []
    with SessionLocal() as db:
        project_query = select(Project).where(Project.enabled.is_(True))
        if project_id:
            project_query = project_query.where(Project.id == uuid.UUID(project_id))
        projects = db.scalars(project_query).all()
        for project in projects:
            running = db.scalar(select(BackgroundTask.id).where(
                BackgroundTask.project_id == project.id,
                BackgroundTask.task_type == BUDGET_SNAPSHOT_TASK_TYPE,
                BackgroundTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
            ).limit(1))
            if running is not None:
                continue
            version_id = uuid.UUID(strategy_version_id) if strategy_version_id else None
            if version_id and db.scalar(select(StrategyVersion.id).join(
                StrategyPolicy, StrategyPolicy.id == StrategyVersion.policy_id
            ).where(
                StrategyVersion.id == version_id,
                StrategyPolicy.project_id == project.id,
                StrategyPolicy.strategy_key == "budget_reset",
            )) is None:
                continue
            task = BackgroundTask(
                project_id=project.id,
                strategy_version_id=version_id,
                task_type=BUDGET_SNAPSHOT_TASK_TYPE,
                current_node="queued",
                result={"request": {"trigger": trigger, "strategy_version_id": strategy_version_id, "schedule_run_id": schedule_run_id}, "state": {}},
            )
            db.add(task)
            db.flush()
            if schedule_run_id:
                schedule_run = db.get(StrategyScheduleRun, uuid.UUID(schedule_run_id))
                if schedule_run and schedule_run.project_id == project.id:
                    schedule_run.task_id = task.id
                    schedule_run.status = "queued"
            queued.append(str(task.id))
        db.commit()
    for task_id in queued:
        sync_project_budget_snapshot.delay(task_id)
    return {"status": "queued", "trigger": trigger, "task_ids": queued}


BUDGET_AUTOMATION_SOURCES = (
    "baidu_account_report",
    "hduofen_capture",
    "baidu_creative_review",
)


def _watermarks_are_fresh(
    db,
    project_id: uuid.UUID,
    *,
    sources: tuple[str, ...],
    now: datetime,
) -> tuple[bool, dict[str, dict]]:
    rows = db.scalars(select(SyncWatermark).where(
        SyncWatermark.scope == str(project_id),
        SyncWatermark.source.in_(sources),
    )).all()
    by_source = {row.source: row for row in rows}
    details: dict[str, dict] = {}
    healthy = True
    for source in sources:
        row = by_source.get(source)
        fresh = bool(
            row
            and row.status == "succeeded"
            and snapshot_is_fresh(row.snapshot_at, now=now)
        )
        healthy = healthy and fresh
        details[source] = {
            "status": row.status if row else "missing",
            "snapshot_at": row.snapshot_at.isoformat() if row and row.snapshot_at else None,
            "fresh": fresh,
        }
    return healthy, details


def _budget_automation_candidates(
    db,
    project_id: uuid.UUID,
    *,
    mode: str,
    now: datetime,
    config: dict | None = None,
) -> list[tuple[Account, Decimal, dict]]:
    config = config or {}
    facts = judgment_facts(db, project_id)
    judgment_preference = load_account_judgment_preference(db, project_id)
    account_status = account_status_expression(facts)
    cost_status = cost_judgment_expressions(facts, judgment_preference)["status"]
    accounts = db.scalars(select(Account)
        .outerjoin(facts.lifetime_metrics, facts.lifetime_metrics.c.account_id == Account.id)
        .outerjoin(facts.recent_metrics, facts.recent_metrics.c.account_id == Account.id)
        .outerjoin(facts.campaign_facts, facts.campaign_facts.c.account_id == Account.id)
        .where(
        Account.project_id == project_id,
        Account.is_active.is_(True),
        account_status.in_(IN_USE_ACCOUNT_STATUSES),
        cost_status == COST_STATUS_COLD_START,
        api_eligible_account_condition(),
        Account.current_budget.is_not(None),
        Account.budget_snapshot_at.is_not(None),
    ).order_by(Account.baidu_account_id)).all()
    accounts = [
        account
        for account in accounts
        if snapshot_is_fresh(account.budget_snapshot_at, now=now)
    ]
    if mode == "reset":
        target_budget = Decimal(str(config.get("target_budget", TARGET_DAILY_BUDGET)))
        return [
            (
                account,
                target_budget,
                {"current_budget": str(account.current_budget)},
            )
            for account in accounts
            if needs_budget_reset(account.current_budget, target_budget=target_budget)
        ]
    if mode != "append":
        raise ValueError("unsupported budget automation mode")

    report_date = now.astimezone(SHANGHAI).date()
    report_day_start = datetime.combine(
        report_date,
        time.min,
        tzinfo=SHANGHAI,
    ).astimezone(UTC)
    report_day_end = report_day_start + timedelta(days=1)
    successful_rounds = {
        str(target_id): int(count_value or 0)
        for target_id, count_value in db.execute(
            select(AuditEvent.target_id, func.count(AuditEvent.id))
            .where(
                AuditEvent.project_id == project_id,
                AuditEvent.action == "account.budget.append",
                AuditEvent.created_at >= report_day_start,
                AuditEvent.created_at < report_day_end,
                AuditEvent.details["status"].astext == "succeeded",
            )
            .group_by(AuditEvent.target_id)
        ).all()
    }
    metrics = {
        account_id: (Decimal(spend or 0), int(adds or 0))
        for account_id, spend, adds in db.execute(
            select(
                PerformanceDaily.account_id,
                func.coalesce(func.sum(PerformanceDaily.spend), 0),
                func.coalesce(func.sum(PerformanceDaily.adds), 0),
            )
            .where(PerformanceDaily.report_date == report_date)
            .group_by(PerformanceDaily.account_id)
        ).all()
    }
    candidates: list[tuple[Account, Decimal, dict]] = []
    add_cost_limit = Decimal(str(config.get("add_cost_limit", "100")))
    utilization_limit = Decimal(str(config.get("utilization_limit", "0.80")))
    for account in accounts:
        spend, adds = metrics.get(account.id, (Decimal("0"), 0))
        if not is_budget_append_candidate(
            spend=spend,
            adds=adds,
            current_budget=account.current_budget,
            add_cost_limit=add_cost_limit,
            utilization_limit=utilization_limit,
        ):
            continue
        append_round = successful_rounds.get(str(account.baidu_account_id), 0) + 1
        append_amount = budget_append_amount(config, append_round)
        candidates.append((
            account,
            Decimal(account.current_budget) + append_amount,
            {
                "spend": str(spend),
                "adds": adds,
                "add_cost": str(spend / Decimal(adds)),
                "budget_utilization": str(spend / Decimal(account.current_budget)),
                "append_round": append_round,
                "append_amount": str(append_amount),
            },
        ))
    return candidates


def _testing_budget_snapshot_health(
    db,
    project_id: uuid.UUID,
    *,
    now: datetime,
) -> tuple[bool, dict[str, int | str | bool | None]]:
    facts = judgment_facts(db, project_id)
    judgment_preference = load_account_judgment_preference(db, project_id)
    account_status = account_status_expression(facts)
    cost_status = cost_judgment_expressions(facts, judgment_preference)["status"]
    captured_at_values = db.scalars(select(Account.budget_snapshot_at)
        .outerjoin(facts.lifetime_metrics, facts.lifetime_metrics.c.account_id == Account.id)
        .outerjoin(facts.recent_metrics, facts.recent_metrics.c.account_id == Account.id)
        .outerjoin(facts.campaign_facts, facts.campaign_facts.c.account_id == Account.id)
        .where(
        Account.project_id == project_id,
        Account.is_active.is_(True),
        account_status.in_(IN_USE_ACCOUNT_STATUSES),
        cost_status == COST_STATUS_COLD_START,
        api_eligible_account_condition(),
    )).all()
    coverage = budget_snapshot_coverage(captured_at_values, now=now)
    latest_snapshot_at = max(
        (value for value in captured_at_values if value is not None),
        default=None,
    )
    return bool(coverage["available"]), {
        **coverage,
        "snapshot_at": (
            latest_snapshot_at.isoformat() if latest_snapshot_at else None
        ),
        "fresh": bool(coverage["available"]),
    }


@celery_app.task
def run_project_budget_automation(project_id: str, task_id: str, mode: str):
    project_uuid = uuid.UUID(project_id)
    task_uuid = uuid.UUID(task_id)
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_uuid)
        if task is None or task.project_id != project_uuid:
            return {"status": "task_missing"}
        if not settings.baidu_writes_enabled:
            task.status = TaskStatus.BLOCKED
            task.current_node = "baidu_writes_disabled"
            task.last_error = "BAIDU_WRITES_ENABLED=false"
            task.heartbeat_at = datetime.now(UTC)
            db.commit()
            return {"status": "blocked", "reason": task.last_error}

        now = datetime.now(UTC)
        required_sources = () if mode == "reset" else BUDGET_AUTOMATION_SOURCES
        healthy, watermark_details = _watermarks_are_fresh(
            db,
            project_uuid,
            sources=required_sources,
            now=now,
        )
        budget_healthy, budget_details = _testing_budget_snapshot_health(
            db,
            project_uuid,
            now=now,
        )
        watermark_details["baidu_budget_snapshot"] = budget_details
        healthy = healthy and budget_healthy
        if not healthy:
            task.status = TaskStatus.BLOCKED
            task.current_node = "data_freshness_guard"
            task.last_error = "required data snapshots are incomplete or stale"
            task.result = {"mode": mode, "watermarks": watermark_details}
            flag_modified(task, "result")
            task.heartbeat_at = now
            db.commit()
            return {"status": "blocked", "watermarks": watermark_details}

        strategy_version = db.get(StrategyVersion, task.strategy_version_id) if task.strategy_version_id else None
        strategy_config = strategy_version.config if strategy_version else {}
        candidates = _budget_automation_candidates(
            db,
            project_uuid,
            mode=mode,
            now=now,
            config=strategy_config,
        )
        task.status = TaskStatus.RUNNING
        task.current_node = f"budget_{mode}_execute"
        task.result = {
            "mode": mode,
            "candidate_count": len(candidates),
            "processed": 0,
            "succeeded": 0,
            "failed": {},
        }
        task.heartbeat_at = now
        db.commit()
        client = platform_client()
        local_now = now.astimezone(SHANGHAI)
        window_key = (
            local_now.strftime("%Y%m%d")
            if mode == "reset"
            else local_now.strftime("%Y%m%d%H")
        )
        action = f"account.budget.{mode}"
        for index, (account, target_budget, metrics) in enumerate(candidates, start=1):
            lock_key = int(account.baidu_account_id)
            lock_acquired = bool(db.scalar(select(func.pg_try_advisory_lock(lock_key))))
            if not lock_acquired:
                task.result["failed"][str(account.baidu_account_id)] = "account lock busy"
                continue
            before_budget = Decimal(account.current_budget)
            try:
                write_result = client.execute_write(
                    context=call_context(
                        account,
                        batch=f"budget-{mode}:{task_id}",
                        idempotency_key=(
                            f"budget-{mode}:{account.baidu_account_id}:{window_key}"
                        ),
                    ),
                    service="account.update",
                    payload={
                        "accountInfo": {
                            "budget": float(target_budget),
                            "budgetType": 1,
                        }
                    },
                )
                readback = client.execute_read(
                    context=call_context(
                        account,
                        batch=f"budget-{mode}-readback:{task_id}",
                        idempotency_key="",
                    ),
                    service="account.get",
                    payload={"accountFields": ["userId", "budget", "budgetType"]},
                )
                info = extract_account_info(readback)
                verified_budget = (
                    Decimal(str(info.get("budget")))
                    if info and info.get("budget") is not None
                    else None
                )
                if verified_budget != target_budget or int(info.get("budgetType") or 0) != 1:
                    raise RuntimeError("budget readback verification failed")
                account.current_budget = verified_budget
                account.budget_type = 1
                account.budget_snapshot_at = datetime.now(UTC)
                task.result["succeeded"] = int(task.result["succeeded"]) + 1
                db.add(AuditEvent(
                    project_id=project_uuid,
                    actor="budget-automation-worker",
                    action=action,
                    target_type="account",
                    target_id=str(account.baidu_account_id),
                    summary=(
                        f"账户预算恢复为{target_budget}元"
                        if mode == "reset"
                        else f"账户预算自动追加{target_budget - before_budget}元"
                    ),
                    details={
                        "account_name": account.login_name,
                        "before_budget": str(before_budget),
                        "after_budget": str(verified_budget),
                        "status": "succeeded",
                        "append_round": metrics.get("append_round") if mode == "append" else None,
                        "append_amount": metrics.get("append_amount") if mode == "append" else None,
                        "metrics": metrics,
                        "write_result_received": bool(write_result),
                    },
                ))
            except Exception as exc:
                task.result["failed"][str(account.baidu_account_id)] = (
                    f"{type(exc).__name__}: {str(exc)[:180]}"
                )
                db.add(AuditEvent(
                    project_id=project_uuid,
                    actor="budget-automation-worker",
                    action=action,
                    target_type="account",
                    target_id=str(account.baidu_account_id),
                    summary="账户预算自动化失败",
                    details={
                        "account_name": account.login_name,
                        "before_budget": str(before_budget),
                        "after_budget": str(target_budget),
                        "status": "failed",
                        "append_round": metrics.get("append_round") if mode == "append" else None,
                        "append_amount": metrics.get("append_amount") if mode == "append" else None,
                        "error_type": type(exc).__name__,
                        "metrics": metrics,
                    },
                ))
            finally:
                db.scalar(select(func.pg_advisory_unlock(lock_key)))
            task.result["processed"] = index
            task.progress = min(95, int(index * 95 / max(1, len(candidates))))
            task.heartbeat_at = datetime.now(UTC)
            flag_modified(task, "result")
            db.commit()

        failures = task.result.get("failed") or {}
        task.status = TaskStatus.SUCCEEDED if not failures else TaskStatus.FAILED
        task.current_node = f"budget_{mode}_complete"
        task.progress = 100
        task.last_error = None if not failures else f"{len(failures)} accounts failed"
        task.heartbeat_at = datetime.now(UTC)
        flag_modified(task, "result")
        db.commit()
        return {"status": task.status.value, **task.result}


@celery_app.task
def queue_budget_automation(
    mode: str,
    project_id: str | None = None,
    strategy_version_id: str | None = None,
    schedule_run_id: str | None = None,
):
    if mode not in {"reset", "append"}:
        raise ValueError("unsupported budget automation mode")
    queued: list[tuple[str, str]] = []
    task_type = f"budget_{mode}_automation"
    with SessionLocal() as db:
        project_query = select(Project).where(Project.enabled.is_(True))
        if project_id is not None:
            project_query = project_query.where(Project.id == uuid.UUID(project_id))
        projects = db.scalars(project_query).all()
        for project in projects:
            running = db.scalar(select(BackgroundTask.id).where(
                BackgroundTask.project_id == project.id,
                BackgroundTask.task_type == task_type,
                BackgroundTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
            ).limit(1))
            if running is not None:
                continue
            version = (
                db.get(StrategyVersion, uuid.UUID(strategy_version_id))
                if strategy_version_id else active_strategy_version(db, project.id, f"budget_{mode}")
            )
            version_is_valid = version and db.scalar(select(StrategyPolicy.id).where(
                StrategyPolicy.id == version.policy_id,
                StrategyPolicy.project_id == project.id,
                StrategyPolicy.strategy_key == f"budget_{mode}",
            )) is not None
            if not version_is_valid:
                continue
            task = BackgroundTask(
                project_id=project.id,
                strategy_version_id=version.id,
                task_type=task_type,
                current_node="queued",
                result={"mode": mode, "strategy_version": version.version_number},
            )
            db.add(task)
            db.flush()
            if schedule_run_id:
                schedule_run = db.get(StrategyScheduleRun, uuid.UUID(schedule_run_id))
                if schedule_run and schedule_run.project_id == project.id:
                    schedule_run.task_id = task.id
                    schedule_run.status = "queued"
            queued.append((str(project.id), str(task.id)))
        db.commit()
    for queued_project_id, task_id in queued:
        run_project_budget_automation.delay(queued_project_id, task_id, mode)
    return {"status": "queued", "mode": mode, "task_ids": [item[1] for item in queued]}


@celery_app.task(bind=True, max_retries=30)
def execute_operation(self, task_id: str):
    with SessionLocal() as db:
        task = db.get(BackgroundTask, uuid.UUID(task_id))
        if not task:
            return
        if isinstance(task.result, dict) and task.result.get("cancelled"):
            return {"status": "cancelled"}
        operation = db.get(Operation, task.operation_id)
        if not operation:
            task.status = TaskStatus.FAILED
            task.last_error = "操作申请不存在"
            db.commit()
            return
        if task.status == TaskStatus.SUCCEEDED or operation.status == OperationStatus.SUCCEEDED:
            return {"status": "already_succeeded"}
        if task.project_id:
            requester = Actor(
                username=operation.requested_by,
                role=Role.ADMIN if is_system_owner(Actor(operation.requested_by, Role.OPERATOR)) else Role.OPERATOR,
            )
            module = "auto_launch" if operation.operation_type.startswith("search_ad_build") else "account_list"
            try:
                access = require_project_permission(db, task.project_id, requester, module, "manage")
                target = db.scalar(select(Account).where(
                    Account.project_id == task.project_id,
                    Account.baidu_account_id == operation.target_account_id,
                ))
                if target is not None:
                    require_account_scope(access, target)
            except Exception as exc:
                task.status = TaskStatus.BLOCKED
                task.current_node = "permission_recheck"
                task.last_error = f"成员权限或账户范围已变化，任务安全阻断：{exc}"
                operation.status = OperationStatus.FAILED
                db.commit()
                return {"status": "permission_blocked"}
        try:
            if operation.operation_type in {"search_ad_build_workflow", "search_ad_build_cleanup", "account_retirement"}:
                lock_key = int(operation.target_account_id)
                lock_acquired = bool(db.scalar(
                    select(func.pg_try_advisory_lock(lock_key))
                ))
                if not lock_acquired:
                    return {"status": "account_execution_already_running"}
                operation.status = OperationStatus.RUNNING
                db.commit()
                try:
                    executor = (
                        execute_ad_build_workflow
                        if operation.operation_type == "search_ad_build_workflow"
                        else execute_ad_build_cleanup
                    )
                    state = executor(db, task, operation, platform_client())
                finally:
                    db.execute(select(func.pg_advisory_unlock(lock_key)))
                    db.commit()
                task.result = {"workflow_state": state}
                task.current_node = "complete"
                task.progress = 100
                task.status = TaskStatus.SUCCEEDED
                task.last_error = None
                operation.status = OperationStatus.SUCCEEDED
                batch_id = operation.payload.get("ad_build_batch_id")
                if batch_id:
                    batch = db.get(AdBuildBatch, uuid.UUID(str(batch_id)))
                    if batch is not None:
                        remaining = db.scalar(
                            select(func.count())
                            .select_from(Operation)
                            .where(
                                Operation.id.in_([uuid.UUID(str(item)) for item in batch.operation_ids]),
                                Operation.status != OperationStatus.SUCCEEDED,
                                Operation.id != operation.id,
                            )
                        )
                        if not remaining:
                            batch.status = "succeeded"
                            job = db.get(AdBuildJob, batch.job_id)
                            if job is not None:
                                other_batches = db.scalar(
                                    select(func.count())
                                    .select_from(AdBuildBatch)
                                    .where(
                                        AdBuildBatch.job_id == job.id,
                                        AdBuildBatch.status != "succeeded",
                                        AdBuildBatch.id != batch.id,
                                    )
                                )
                                if not other_batches:
                                    job.status = "succeeded"
                db.commit()
                return {"status": "succeeded", "readback": state.get("readback")}
            checkpoint(db, task, "permission_preflight", 10)
            context = BaiduCallContext(
                app_code="search",
                baidu_application_code=settings.baidu_application_code,
                manager_login_name=operation.payload.get("manager_login_name", ""),
                target_account_id=operation.target_account_id,
                target_login_name=operation.payload.get("target_login_name", ""),
                request_batch=str(operation.id),
                idempotency_key=operation.idempotency_key,
            )
            client = platform_client()
            checkpoint(db, task, "baidu_execute", 45)
            result = client.execute_write(context=context, service=operation.operation_type, payload=operation.payload)
            checkpoint(db, task, "readback_verification", 80)
            verified = client.verify_write(context=context, result=result)
            task.result = {"baidu": result, "verified": verified}
            task.current_node = "complete"
            task.progress = 100
            task.status = TaskStatus.SUCCEEDED
            operation.status = OperationStatus.SUCCEEDED
            db.commit()
        except DelayedReadbackPending as exc:
            task.status = TaskStatus.PENDING
            task.current_node = "adgroup_readback_wait"
            task.last_error = str(exc)[:1000]
            task.heartbeat_at = datetime.now(UTC)
            # Keep the operation running: the acknowledged write must never be
            # replayed. Celery retries this same task only to perform the
            # read-only verification checkpoint stored in workflow_state.
            operation.status = OperationStatus.RUNNING
            db.commit()
            raise self.retry(
                exc=exc,
                countdown=ADGROUP_READBACK_DELAY_SECONDS,
                max_retries=30,
            )
        except Exception as exc:
            task.status = TaskStatus.BLOCKED if not settings.baidu_writes_enabled else TaskStatus.FAILED
            task.last_error = str(exc)[:1000]
            task.retry_count += 1
            operation.status = OperationStatus.FAILED
            batch_id = operation.payload.get("ad_build_batch_id") if isinstance(operation.payload, dict) else None
            if batch_id:
                batch = db.get(AdBuildBatch, uuid.UUID(str(batch_id)))
                if batch is not None:
                    batch.status = "failed"
                    job = db.get(AdBuildJob, batch.job_id)
                    if job is not None:
                        job.status = "failed"
            db.commit()
            activation_required = "BAIDU_ACCOUNT_ACTIVATION_REQUIRED" in str(exc)
            manual_readback_check = isinstance(exc, ReadbackVerificationTimeout)
            if (
                settings.baidu_writes_enabled
                and task.retry_count < 3
                and not activation_required
                and not manual_readback_check
            ):
                raise self.retry(exc=exc, countdown=30 * task.retry_count)


CAMPAIGN_BATCH_ACCOUNT_CHUNK = 10
CAMPAIGN_BATCH_AUTO_RETRY_DELAYS = (60, 300, 900)
CAMPAIGN_BATCH_RETRY_DISPATCH_TIMEOUT = timedelta(minutes=5)
BACKGROUND_TASK_HEARTBEAT_TIMEOUT = timedelta(minutes=15)
BACKGROUND_TASK_INTENTIONAL_WAIT_NODES = {
    "campaign_batch_auto_retry_wait",
    "scheduled_ad_build_wait",
}


def _task_heartbeat_expired(
    task: BackgroundTask,
    now: datetime,
    timeout: timedelta = BACKGROUND_TASK_HEARTBEAT_TIMEOUT,
) -> bool:
    if task.status not in {TaskStatus.PENDING, TaskStatus.RUNNING}:
        return False
    if task.current_node in BACKGROUND_TASK_INTENTIONAL_WAIT_NODES:
        return False
    last_seen = task.heartbeat_at or task.updated_at or task.created_at
    return last_seen is None or last_seen <= now - timeout


@celery_app.task
def close_stale_background_tasks():
    """Turn abandoned active rows into an explicit, resumable terminal state."""

    now = datetime.now(UTC)
    closed: list[str] = []
    with SessionLocal() as db:
        tasks = db.scalars(
            select(BackgroundTask)
            .where(BackgroundTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]))
            .order_by(BackgroundTask.created_at)
        ).all()
        for task in tasks:
            if not _task_heartbeat_expired(task, now):
                continue
            previous_node = task.current_node
            previous_heartbeat = task.heartbeat_at or task.updated_at or task.created_at
            task.status = TaskStatus.BLOCKED
            task.current_node = "heartbeat_timeout"
            task.last_error = (
                "任务心跳超过15分钟未更新，系统已停止将其显示为运行中；"
                "请核对百度实际状态后再决定是否安全续跑"
            )
            task.heartbeat_at = now
            result = task.result if isinstance(task.result, dict) else {}
            result["heartbeat_timeout"] = {
                "detected_at": now.isoformat(),
                "previous_node": previous_node,
                "previous_heartbeat_at": (
                    previous_heartbeat.isoformat() if previous_heartbeat else None
                ),
            }
            task.result = result
            flag_modified(task, "result")

            operation = db.get(Operation, task.operation_id) if task.operation_id else None
            if operation is not None and operation.status in {
                OperationStatus.QUEUED,
                OperationStatus.RUNNING,
            }:
                operation.status = OperationStatus.FAILED
                batch_id = (
                    operation.payload.get("ad_build_batch_id")
                    if isinstance(operation.payload, dict)
                    else None
                )
                if batch_id:
                    batch = db.get(AdBuildBatch, uuid.UUID(str(batch_id)))
                    if batch is not None:
                        batch.status = "failed"
                        job = db.get(AdBuildJob, batch.job_id)
                        if job is not None:
                            job.status = "failed"
            if task.project_id is not None:
                db.add(AuditEvent(
                    project_id=task.project_id,
                    actor="task-heartbeat-watchdog",
                    action="background_task.heartbeat_timeout",
                    target_type="background_task",
                    target_id=str(task.id),
                    summary="任务心跳超时，已转为需要处理",
                    details={
                        "previous_node": previous_node,
                        "previous_heartbeat_at": (
                            previous_heartbeat.isoformat() if previous_heartbeat else None
                        ),
                    },
                ))
            closed.append(str(task.id))
        db.commit()
    return {"status": "complete", "closed_task_ids": closed, "closed_count": len(closed)}


def _campaign_auto_retry_plan(
    request_details: dict,
    failed_baidu_account_ids: list[int],
) -> dict[str, int] | None:
    if not failed_baidu_account_ids:
        return None
    current_attempt = int(request_details.get("auto_retry_attempt") or 0)
    if current_attempt >= len(CAMPAIGN_BATCH_AUTO_RETRY_DELAYS):
        return None
    return {
        "attempt": current_attempt + 1,
        "delay_seconds": CAMPAIGN_BATCH_AUTO_RETRY_DELAYS[current_attempt],
    }


def _campaign_retry_not_before(request_details: dict) -> datetime | None:
    raw = request_details.get("auto_retry_not_before")
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalized_campaign_schedule(value) -> list[tuple[int, int, int]]:
    if not isinstance(value, list):
        return []
    result = []
    for row in value:
        if not isinstance(row, dict):
            continue
        try:
            result.append((int(row["weekDay"]), int(row["startHour"]), int(row["endHour"])))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(set(result))


def _campaign_cache_is_fresh(account: Account, *, now: datetime | None = None) -> bool:
    # Campaign IDs are stable until a rebuild/cleanup. Those workflows mark
    # this cache stale explicitly, so a time-based six-hour expiry only causes
    # expensive duplicate reads and does not improve identity correctness.
    # Schedule/pause writes still perform readback and refresh cached state.
    return bool(
        account.campaign_cache_status == "succeeded"
        and account.campaign_cache_synced_at is not None
    )


def _campaign_rows_from_cache(db, account: Account) -> list[dict]:
    rows = db.scalars(select(CampaignCache).where(
        CampaignCache.project_id == account.project_id,
        CampaignCache.account_id == account.id,
        CampaignCache.is_active.is_(True),
    ).order_by(CampaignCache.baidu_campaign_id)).all()
    return [
        {
            "campaignId": row.baidu_campaign_id,
            "campaignName": row.campaign_name,
            "pause": row.pause,
            "schedule": row.schedule or [],
            "status": row.remote_status,
            "adType": row.ad_type,
        }
        for row in rows
    ]


def _store_campaign_cache_rows(
    db,
    account: Account,
    remote_rows: list[dict],
    *,
    full_sync: bool,
    synced_at: datetime | None = None,
) -> None:
    observed_at = synced_at or datetime.now(UTC)
    existing = {
        row.baidu_campaign_id: row
        for row in db.scalars(select(CampaignCache).where(
            CampaignCache.project_id == account.project_id,
            CampaignCache.account_id == account.id,
        )).all()
    }
    if full_sync:
        for row in existing.values():
            row.is_active = False
    for remote in remote_rows:
        if remote.get("campaignId") is None:
            continue
        campaign_id = int(remote["campaignId"])
        row = existing.get(campaign_id)
        if row is None:
            row = CampaignCache(
                project_id=account.project_id,
                account_id=account.id,
                baidu_campaign_id=campaign_id,
            )
            db.add(row)
            existing[campaign_id] = row
        if "campaignName" in remote:
            row.campaign_name = str(remote.get("campaignName") or "") or None
        if "pause" in remote:
            row.pause = bool(remote.get("pause"))
        if "schedule" in remote:
            row.schedule = remote.get("schedule") if isinstance(remote.get("schedule"), list) else []
        if "status" in remote:
            try:
                row.remote_status = int(remote["status"]) if remote.get("status") is not None else None
            except (TypeError, ValueError):
                row.remote_status = None
        if "adType" in remote:
            try:
                row.ad_type = int(remote.get("adType") or 0)
            except (TypeError, ValueError):
                row.ad_type = 0
        row.is_active = True
        row.last_seen_at = observed_at
        row.updated_at = observed_at
    if full_sync:
        account.campaign_cache_synced_at = observed_at
        account.campaign_cache_status = "succeeded"


def _store_ocpc_project_cache_rows(
    db,
    account: Account,
    remote_rows: list[dict],
    *,
    synced_at: datetime | None = None,
) -> None:
    """Persist the latest verified oCPC inventory; the UI never reads Baidu directly."""
    observed_at = synced_at or datetime.now(UTC)
    existing = {
        row.baidu_ocpc_project_id: row
        for row in db.scalars(select(OcpcProjectCache).where(
            OcpcProjectCache.project_id == account.project_id,
            OcpcProjectCache.account_id == account.id,
        )).all()
    }
    for row in existing.values():
        row.is_active = False
    for remote in remote_rows:
        if remote.get("targetPackageId") is None:
            continue
        project_id = int(remote["targetPackageId"])
        row = existing.get(project_id)
        if row is None:
            row = OcpcProjectCache(
                project_id=account.project_id,
                account_id=account.id,
                baidu_ocpc_project_id=project_id,
            )
            db.add(row)
        row.project_name = str(remote.get("targetPackageName") or "") or None
        try:
            row.ocpc_bid = Decimal(str(remote["ocpcBid"])) if remote.get("ocpcBid") is not None else None
        except (ArithmeticError, TypeError, ValueError):
            row.ocpc_bid = None
        for source, attribute in (("ocpcBidType", "bid_type"), ("packageStatus", "remote_status")):
            try:
                setattr(row, attribute, int(remote[source]) if remote.get(source) is not None else None)
            except (TypeError, ValueError):
                setattr(row, attribute, None)
        row.scope = remote.get("scope") if isinstance(remote.get("scope"), list) else []
        row.is_active = True
        row.last_seen_at = observed_at
        row.updated_at = observed_at
    account.ocpc_cache_synced_at = observed_at
    account.ocpc_cache_status = "succeeded"


def _persist_campaign_batch_state(db, task: BackgroundTask, request_details: dict, state: dict) -> None:
    task.result = {"request": request_details, "state": state}
    flag_modified(task, "result")
    task.heartbeat_at = datetime.now(UTC)
    db.commit()


def _campaign_account_matches_task_scope(account: Account, request_details: dict) -> bool:
    """Recheck the queued snapshot while preserving optional wildcard filters."""
    requested_account_type = str(request_details.get("account_type") or "")
    requested_page_type = str(request_details.get("page_type") or "")
    return (
        account.is_active
        and account.eliminated_at is None
        and (
            not requested_account_type
            or account.account_type.value == requested_account_type
        )
        and (not requested_page_type or account.page_type == requested_page_type)
    )


def _update_campaign_setting_status(
    db,
    task: BackgroundTask,
    request_details: dict,
    status: str,
    plan_count: int | None = None,
) -> None:
    action = str(request_details.get("action") or "")
    if action not in {"schedule", "pause"} or task.project_id is None:
        return
    setting = db.scalar(select(CampaignBatchSetting).where(
        CampaignBatchSetting.project_id == task.project_id,
        CampaignBatchSetting.account_type == str(request_details.get("account_type") or ""),
        CampaignBatchSetting.page_type == str(request_details.get("page_type") or ""),
    ))
    if setting is None or getattr(setting, f"{action}_task_id") != task.id:
        return
    setattr(setting, f"{action}_status", status)
    if plan_count is not None:
        setattr(setting, f"{action}_plan_count", plan_count)
    setting.updated_at = datetime.now(UTC)


def _run_campaign_batch_update(task_id: str):
    task_uuid = uuid.UUID(task_id)
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_uuid)
        if task is None or task.project_id is None:
            return {"status": "task_missing"}
        payload = task.result if isinstance(task.result, dict) else {}
        request_details = payload.get("request") if isinstance(payload.get("request"), dict) else {}
        try:
            permission_access = _task_requester_access(
                db, task, request_details, "account_list"
            )
        except Exception as exc:
            return _block_for_permission_change(db, task, exc)
        retry_not_before = _campaign_retry_not_before(request_details)
        if retry_not_before and datetime.now(UTC) < retry_not_before:
            task.status = TaskStatus.PENDING
            task.current_node = "campaign_batch_auto_retry_wait"
            task.last_error = "失败账户已进入安全续跑等待窗口"
            task.heartbeat_at = datetime.now(UTC)
            db.commit()
            return {
                "status": "retry_wait",
                "retry_not_before": retry_not_before.isoformat(),
            }
        account_ids = request_details.get("account_ids")
        action = str(request_details.get("action") or "")
        if not isinstance(account_ids, list) or not account_ids or action not in {"schedule", "pause"}:
            task.status = TaskStatus.BLOCKED
            task.current_node = "invalid_request"
            task.last_error = "计划批量设置任务参数无效"
            db.commit()
            return {"status": "blocked", "reason": task.last_error}
        if not settings.baidu_writes_enabled:
            task.status = TaskStatus.BLOCKED
            task.current_node = "waiting_writes"
            task.last_error = "百度写入开关未开启，任务未调用百度接口"
            _update_campaign_setting_status(db, task, request_details, "blocked")
            db.commit()
            return {"status": "blocked", "reason": task.last_error}

        state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
        state.setdefault("cursor", 0)
        state.setdefault("processed_accounts", 0)
        state.setdefault("skipped_accounts", 0)
        state.setdefault("discovered_plan_count", 0)
        state.setdefault("updated_plan_count", 0)
        state.setdefault("unchanged_plan_count", 0)
        state.setdefault("campaign_cache_hits", 0)
        state.setdefault("campaign_cache_refreshes", 0)
        state.setdefault("failed_accounts", {})
        _update_campaign_setting_status(db, task, request_details, "running")
        db.commit()
        desired_schedule = None
        if action == "schedule":
            raw_online_schedule = request_details.get("online_schedule")
            desired_schedule = (
                build_plan_pause_schedule_from_windows(True, raw_online_schedule)
                if isinstance(raw_online_schedule, list)
                else build_plan_pause_schedule(
                    True,
                    [int(day) for day in request_details.get("online_weekdays") or []],
                    int(request_details.get("online_start_hour")),
                    int(request_details.get("online_end_hour")),
                )
            )
        desired_pause = bool(request_details.get("pause")) if action == "pause" else None
        force_remote_read = bool(request_details.get("auto_retry_attempt"))
        client = platform_client()
        start = int(state["cursor"])
        stop = min(len(account_ids), start + CAMPAIGN_BATCH_ACCOUNT_CHUNK)
        for index in range(start, stop):
            raw_account_id = account_ids[index]
            try:
                account = db.get(Account, uuid.UUID(str(raw_account_id)))
            except (TypeError, ValueError):
                account = None
            if (
                account is None
                or account.project_id != task.project_id
                or not _campaign_account_matches_task_scope(account, request_details)
            ):
                state["skipped_accounts"] = int(state["skipped_accounts"]) + 1
                state["cursor"] = index + 1
                task.current_node = "scope_recheck_skipped"
                task.progress = min(95, int((index + 1) * 100 / len(account_ids)))
                _persist_campaign_batch_state(db, task, request_details, state)
                continue
            try:
                require_account_scope(permission_access, account)
            except Exception as exc:
                return _block_for_permission_change(db, task, exc)

            lock_key = int(account.baidu_account_id)
            lock_acquired = False
            try:
                lock_acquired = bool(
                    db.scalar(select(func.pg_try_advisory_lock(lock_key)))
                )
                if not lock_acquired:
                    raise RuntimeError("账户正在执行其他写任务")
                task.status = TaskStatus.RUNNING
                task.current_node = f"read_campaigns_{account.baidu_account_id}"
                task.progress = min(95, int(index * 100 / len(account_ids)))
                _persist_campaign_batch_state(db, task, request_details, state)
                context = call_context(
                    account,
                    batch=f"campaign-batch:{task_id}",
                    idempotency_key="",
                )
                cache_source = "cache"
                if _campaign_cache_is_fresh(account) and not force_remote_read:
                    campaign_rows = _campaign_rows_from_cache(db, account)
                    state["campaign_cache_hits"] = int(state["campaign_cache_hits"]) + 1
                else:
                    cache_source = "baidu_refresh"
                    campaign_rows = baidu_result_rows(client.execute_read(
                        context,
                        "campaign.get",
                        {
                            "campaignFields": [
                                "campaignId", "campaignName", "pause", "schedule", "status", "adType",
                            ],
                            "campaignIds": [],
                            "adType": 0,
                        },
                    ))
                    _store_campaign_cache_rows(db, account, campaign_rows, full_sync=True)
                    state["campaign_cache_refreshes"] = (
                        int(state["campaign_cache_refreshes"]) + 1
                    )
                    db.commit()
                state["discovered_plan_count"] = (
                    int(state["discovered_plan_count"]) + len(campaign_rows)
                )
                changed_rows = []
                for campaign in campaign_rows:
                    if campaign.get("campaignId") is None:
                        continue
                    if action == "schedule":
                        changed = _normalized_campaign_schedule(campaign.get("schedule")) != (
                            _normalized_campaign_schedule(desired_schedule)
                        )
                    else:
                        changed = bool(campaign.get("pause")) != desired_pause
                    if changed:
                        changed_rows.append(campaign)
                    else:
                        state["unchanged_plan_count"] = int(state["unchanged_plan_count"]) + 1

                for batch_number, campaign_batch in enumerate(chunks(changed_rows, 100), start=1):
                    update_types = []
                    for campaign in campaign_batch:
                        item = {"campaignId": int(campaign["campaignId"])}
                        if action == "schedule":
                            item["schedule"] = desired_schedule
                        else:
                            item["pause"] = desired_pause
                        update_types.append(item)
                    fingerprint = hashlib.sha256(json.dumps(
                        update_types,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")).hexdigest()[:20]
                    client.execute_write(
                        context=call_context(
                            account,
                            batch=f"campaign-batch:{task_id}",
                            idempotency_key=(
                                f"campaign-batch:{task_id}:{account.baidu_account_id}:"
                                f"{action}:{batch_number}:{fingerprint}"
                            ),
                        ),
                        service="campaign.update",
                        payload={"campaignTypes": update_types},
                    )
                    readback_rows = baidu_result_rows(client.execute_read(
                        context,
                        "campaign.get",
                        {
                            "campaignFields": ["campaignId", "pause", "schedule"],
                            "campaignIds": [item["campaignId"] for item in update_types],
                            "adType": 0,
                        },
                    ))
                    readback = {
                        int(row["campaignId"]): row
                        for row in readback_rows
                        if row.get("campaignId") is not None
                    }
                    for item in update_types:
                        remote = readback.get(item["campaignId"])
                        if remote is None:
                            raise RuntimeError(f"计划 {item['campaignId']} 更新后未回读到")
                        if action == "schedule" and _normalized_campaign_schedule(
                            remote.get("schedule")
                        ) != _normalized_campaign_schedule(desired_schedule):
                            raise RuntimeError(f"计划 {item['campaignId']} 时段回读不一致")
                        if action == "pause" and bool(remote.get("pause")) != desired_pause:
                            raise RuntimeError(f"计划 {item['campaignId']} 启停状态回读不一致")
                    _store_campaign_cache_rows(
                        db,
                        account,
                        list(readback.values()),
                        full_sync=False,
                    )
                    state["updated_plan_count"] = (
                        int(state["updated_plan_count"]) + len(update_types)
                    )

                state["processed_accounts"] = int(state["processed_accounts"]) + 1
                state["cursor"] = index + 1
                db.add(AuditEvent(
                    project_id=task.project_id,
                    actor=str(request_details.get("requested_by") or "campaign-batch-worker"),
                    action="campaign.batch_update.account",
                    target_type="account",
                    target_id=str(account.baidu_account_id),
                    summary="批量更新账户计划时段" if action == "schedule" else "批量更新账户计划启停状态",
                    details={
                        "task_id": task_id,
                        "account_name": account.login_name,
                        "discovered_plan_count": len(campaign_rows),
                        "updated_plan_count": len(changed_rows),
                        "action": action,
                        "campaign_source": cache_source,
                    },
                ))
                task = db.get(BackgroundTask, task_uuid)
                task.current_node = f"verified_{account.baidu_account_id}"
                task.progress = min(95, int((index + 1) * 100 / len(account_ids)))
                _persist_campaign_batch_state(db, task, request_details, state)
            except RateLimitError as exc:
                db.rollback()
                task = db.get(BackgroundTask, task_uuid)
                task.status = TaskStatus.PENDING
                task.current_node = "rate_limited"
                task.last_error = "百度接口限频，稍后从当前账户续跑"
                _update_campaign_setting_status(db, task, request_details, "pending")
                _persist_campaign_batch_state(db, task, request_details, state)
                run_campaign_batch_update.apply_async(
                    args=[task_id], countdown=rate_limit_retry_seconds(exc)
                )
                return {"status": "rate_limited", "task_id": task_id, "cursor": state["cursor"]}
            except TokenUnavailableError as exc:
                db.rollback()
                task = db.get(BackgroundTask, task_uuid)
                task.status = TaskStatus.BLOCKED
                task.current_node = "authorization_blocked"
                task.last_error = str(exc)[:500]
                _update_campaign_setting_status(db, task, request_details, "blocked")
                _persist_campaign_batch_state(db, task, request_details, state)
                return {"status": "blocked", "reason": task.last_error}
            except Exception as exc:
                db.rollback()
                task = db.get(BackgroundTask, task_uuid)
                stale_account = db.get(Account, account.id)
                if stale_account is not None:
                    stale_account.campaign_cache_status = "stale"
                failures = state["failed_accounts"]
                failures[str(account.baidu_account_id)] = (
                    f"{type(exc).__name__}: {str(exc)[:220]}"
                )
                state["cursor"] = index + 1
                task.current_node = "account_failed"
                task.last_error = failures[str(account.baidu_account_id)]
                _persist_campaign_batch_state(db, task, request_details, state)
            finally:
                if lock_acquired:
                    db.scalar(select(func.pg_advisory_unlock(lock_key)))
                    db.commit()

        task = db.get(BackgroundTask, task_uuid)
        if int(state["cursor"]) < len(account_ids):
            task.status = TaskStatus.PENDING
            task.current_node = "next_account_batch"
            task.last_error = None
            _persist_campaign_batch_state(db, task, request_details, state)
            run_campaign_batch_update.delay(task_id)
            return {"status": "continued", "task_id": task_id, "cursor": state["cursor"]}

        failures = state.get("failed_accounts") or {}
        task.status = TaskStatus.FAILED if failures else TaskStatus.SUCCEEDED
        task.current_node = "campaign_batch_incomplete" if failures else "complete"
        task.progress = 100
        task.last_error = f"{len(failures)} 个账户执行失败，可在任务中心续跑" if failures else None
        setting_plan_count = (
            None
            if request_details.get("auto_retry_attempt")
            else int(state["discovered_plan_count"])
        )
        _update_campaign_setting_status(
            db,
            task,
            request_details,
            "partial_failed" if failures else "succeeded",
            setting_plan_count,
        )
        db.add(AuditEvent(
            project_id=task.project_id,
            actor=str(request_details.get("requested_by") or "campaign-batch-worker"),
            action="campaign.batch_update.complete",
            target_type="background_task",
            target_id=task_id,
            summary="账户计划批量设置完成" if not failures else "账户计划批量设置部分失败",
            details={
                "action": action,
                "processed_accounts": state["processed_accounts"],
                "updated_plan_count": state["updated_plan_count"],
                "unchanged_plan_count": state["unchanged_plan_count"],
                "failed_account_count": len(failures),
            },
        ))
        auto_retry_task_id = None
        if failures:
            failed_baidu_account_ids = []
            for value in failures:
                try:
                    failed_baidu_account_ids.append(int(value))
                except (TypeError, ValueError):
                    continue
            retry_plan = _campaign_auto_retry_plan(
                request_details,
                failed_baidu_account_ids,
            )
            retry_accounts = []
            if retry_plan:
                retry_accounts = db.scalars(select(Account).where(
                    Account.project_id == task.project_id,
                    Account.baidu_account_id.in_(failed_baidu_account_ids),
                    Account.is_active.is_(True),
                ).order_by(Account.baidu_account_id)).all()
            if retry_plan and retry_accounts:
                scheduled_at = datetime.now(UTC) + timedelta(
                    seconds=retry_plan["delay_seconds"]
                )
                retry_request = {
                    **request_details,
                    "account_ids": [str(account.id) for account in retry_accounts],
                    "auto_retry_attempt": retry_plan["attempt"],
                    "auto_retry_not_before": scheduled_at.isoformat(),
                    "auto_retry_root_task_id": str(
                        request_details.get("auto_retry_root_task_id") or task_id
                    ),
                    "auto_retry_previous_task_id": task_id,
                    "original_account_count": int(
                        request_details.get("original_account_count")
                        or len(account_ids)
                    ),
                }
                retry_task = BackgroundTask(
                    project_id=task.project_id,
                    task_type="campaign_batch_update",
                    status=TaskStatus.PENDING,
                    current_node="campaign_batch_auto_retry_wait",
                    progress=0,
                    retry_count=retry_plan["attempt"],
                    result={"request": retry_request, "state": {}},
                    heartbeat_at=datetime.now(UTC),
                )
                db.add(retry_task)
                db.flush()
                auto_retry_task_id = str(retry_task.id)
                state["auto_retry"] = {
                    "task_id": auto_retry_task_id,
                    "attempt": retry_plan["attempt"],
                    "account_count": len(retry_accounts),
                    "scheduled_at": scheduled_at.isoformat(),
                }
                task.current_node = "campaign_batch_auto_retry_scheduled"
                task.last_error = (
                    f"{len(failures)} 个账户执行失败，已安排第 "
                    f"{retry_plan['attempt']} 次自动安全续跑"
                )
                setting = db.scalar(select(CampaignBatchSetting).where(
                    CampaignBatchSetting.project_id == task.project_id,
                    CampaignBatchSetting.account_type == str(
                        request_details.get("account_type") or ""
                    ),
                    CampaignBatchSetting.page_type == str(
                        request_details.get("page_type") or ""
                    ),
                ))
                if (
                    setting is not None
                    and getattr(setting, f"{action}_task_id") == task.id
                ):
                    setattr(setting, f"{action}_task_id", retry_task.id)
                    setattr(setting, f"{action}_status", "retry_pending")
                    setting.updated_at = datetime.now(UTC)
                db.add(AuditEvent(
                    project_id=task.project_id,
                    actor="campaign-batch-worker",
                    action="campaign.batch_update.auto_retry_scheduled",
                    target_type="background_task",
                    target_id=auto_retry_task_id,
                    summary="计划批量设置失败账户已安排自动安全续跑",
                    details={
                        "previous_task_id": task_id,
                        "action": action,
                        "attempt": retry_plan["attempt"],
                        "account_count": len(retry_accounts),
                        "scheduled_at": scheduled_at.isoformat(),
                    },
                ))
        _persist_campaign_batch_state(db, task, request_details, state)
        return {
            "status": task.status.value,
            "task_id": task_id,
            "auto_retry_task_id": auto_retry_task_id,
            **state,
        }


@celery_app.task
def run_campaign_batch_update(task_id: str):
    task_uuid = uuid.UUID(task_id)
    lock_key = task_uuid.int & 0x7FFFFFFFFFFFFFFF
    with engine.connect() as lock_connection:
        acquired = bool(lock_connection.execute(
            text("SELECT pg_try_advisory_lock(:lock_key)"),
            {"lock_key": lock_key},
        ).scalar_one())
        if not acquired:
            return {"status": "duplicate_ignored", "task_id": task_id}
        try:
            return _run_campaign_batch_update(task_id)
        finally:
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(:lock_key)"),
                {"lock_key": lock_key},
            )


MANAGER_CAMPAIGN_CLEANUP_ACCOUNT_CHUNK = 10


def _persist_manager_campaign_cleanup_state(
    db,
    task: BackgroundTask,
    request_details: dict,
    state: dict,
) -> None:
    task.result = {"request": request_details, "state": state}
    flag_modified(task, "result")
    task.heartbeat_at = datetime.now(UTC)
    db.commit()


def _run_manager_campaign_cleanup(task_id: str) -> dict:
    task_uuid = uuid.UUID(task_id)
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_uuid)
        if task is None or task.project_id is None:
            return {"status": "task_missing"}
        payload = task.result if isinstance(task.result, dict) else {}
        request_details = payload.get("request") if isinstance(payload.get("request"), dict) else {}
        try:
            permission_access = _task_requester_access(
                db, task, request_details, "account_management"
            )
            if not permission_access.is_owner and permission_access.data_scope != "project":
                raise RuntimeError("账户管家级操作要求项目全部数据范围")
        except Exception as exc:
            return _block_for_permission_change(db, task, exc)
        account_ids = request_details.get("account_ids")
        manager_id = request_details.get("manager_id")
        if not isinstance(account_ids, list) or not account_ids or not manager_id:
            task.status = TaskStatus.BLOCKED
            task.current_node = "invalid_request"
            task.last_error = "清空账户管家计划任务参数无效"
            db.commit()
            return {"status": "blocked", "reason": task.last_error}
        if not settings.baidu_writes_enabled:
            task.status = TaskStatus.BLOCKED
            task.current_node = "waiting_writes"
            task.last_error = "百度写入开关未开启，任务未调用百度接口"
            db.commit()
            return {"status": "blocked", "reason": task.last_error}

        state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
        state.setdefault("cursor", 0)
        state.setdefault("processed_accounts", 0)
        state.setdefault("accounts_without_campaigns", 0)
        state.setdefault("accounts_with_campaigns", 0)
        state.setdefault("discovered_campaign_count", 0)
        state.setdefault("deleted_campaign_count", 0)
        state.setdefault("failed_accounts", {})
        client = platform_client()
        start = int(state["cursor"])
        stop = min(len(account_ids), start + MANAGER_CAMPAIGN_CLEANUP_ACCOUNT_CHUNK)
        for index in range(start, stop):
            try:
                account = db.get(Account, uuid.UUID(str(account_ids[index])))
            except (TypeError, ValueError):
                account = None
            if (
                account is None
                or account.project_id != task.project_id
                or str(account.manager_id) != str(manager_id)
            ):
                state["failed_accounts"][str(account_ids[index])] = "账户不再属于任务指定的账户管家"
                state["cursor"] = index + 1
                _persist_manager_campaign_cleanup_state(db, task, request_details, state)
                continue

            lock_key = int(account.baidu_account_id)
            lock_acquired = False
            try:
                lock_acquired = bool(db.scalar(select(func.pg_try_advisory_lock(lock_key))))
                if not lock_acquired:
                    raise RuntimeError("账户正在执行其他写任务")
                task.status = TaskStatus.RUNNING
                task.current_node = f"read_campaigns_{account.baidu_account_id}"
                task.progress = min(95, int(index * 100 / len(account_ids)))
                _persist_manager_campaign_cleanup_state(db, task, request_details, state)
                context = call_context(
                    account,
                    batch=f"manager-campaign-cleanup:{task_id}",
                    idempotency_key="",
                )
                campaign_payload = {
                    "campaignFields": ["campaignId", "campaignName", "status", "adType"],
                    "campaignIds": [],
                    "adType": 0,
                }
                campaign_rows = baidu_result_rows(
                    client.execute_read(context, "campaign.get", campaign_payload)
                )
                campaign_ids = sorted({
                    int(row["campaignId"])
                    for row in campaign_rows
                    if row.get("campaignId") is not None
                })
                state["discovered_campaign_count"] = (
                    int(state["discovered_campaign_count"]) + len(campaign_ids)
                )
                if campaign_ids:
                    state["accounts_with_campaigns"] = int(state["accounts_with_campaigns"]) + 1
                else:
                    state["accounts_without_campaigns"] = int(state["accounts_without_campaigns"]) + 1
                for batch_number, campaign_batch in enumerate(chunks(campaign_ids, 100), start=1):
                    fingerprint = hashlib.sha256(
                        ",".join(str(item) for item in campaign_batch).encode("ascii")
                    ).hexdigest()[:20]
                    client.execute_write(
                        context=call_context(
                            account,
                            batch=f"manager-campaign-cleanup:{task_id}",
                            idempotency_key=(
                                f"manager-campaign-cleanup:{task_id}:{account.baidu_account_id}:"
                                f"{batch_number}:{fingerprint}"
                            ),
                        ),
                        service="campaign.delete",
                        payload={"campaignIds": campaign_batch},
                    )
                remaining_rows = baidu_result_rows(
                    client.execute_read(context, "campaign.get", campaign_payload)
                )
                remaining_ids = sorted({
                    int(row["campaignId"])
                    for row in remaining_rows
                    if row.get("campaignId") is not None
                })
                if remaining_ids:
                    raise RuntimeError(f"删除后仍存在计划：{','.join(str(value) for value in remaining_ids[:20])}")
                _store_campaign_cache_rows(db, account, [], full_sync=True)
                state["deleted_campaign_count"] = (
                    int(state["deleted_campaign_count"]) + len(campaign_ids)
                )
                state["processed_accounts"] = int(state["processed_accounts"]) + 1
                state["cursor"] = index + 1
                db.add(AuditEvent(
                    project_id=task.project_id,
                    actor=str(request_details.get("requested_by") or "manager-campaign-cleanup-worker"),
                    action="manager.campaign_cleanup.account",
                    target_type="account",
                    target_id=str(account.baidu_account_id),
                    summary="清空账户全部计划并完成百度回读",
                    details={
                        "task_id": task_id,
                        "account_name": account.login_name,
                        "deleted_campaign_count": len(campaign_ids),
                        "readback_remaining": 0,
                    },
                ))
                task.current_node = f"verified_{account.baidu_account_id}"
                task.progress = min(95, int((index + 1) * 100 / len(account_ids)))
                _persist_manager_campaign_cleanup_state(db, task, request_details, state)
            except RateLimitError as exc:
                db.rollback()
                task = db.get(BackgroundTask, task_uuid)
                task.status = TaskStatus.PENDING
                task.current_node = "rate_limited"
                task.last_error = "百度接口限频，稍后从当前账户续跑"
                _persist_manager_campaign_cleanup_state(db, task, request_details, state)
                run_manager_campaign_cleanup.apply_async(
                    args=[task_id], countdown=rate_limit_retry_seconds(exc)
                )
                return {"status": "rate_limited", "task_id": task_id, "cursor": state["cursor"]}
            except Exception as exc:
                db.rollback()
                task = db.get(BackgroundTask, task_uuid)
                stale_account = db.get(Account, account.id) if account is not None else None
                if stale_account is not None:
                    stale_account.campaign_cache_status = "stale"
                account_key = str(account.baidu_account_id) if account else str(account_ids[index])
                state["failed_accounts"][account_key] = f"{type(exc).__name__}: {str(exc)[:300]}"
                state["cursor"] = index + 1
                task.current_node = "account_failed"
                task.last_error = state["failed_accounts"][account_key]
                _persist_manager_campaign_cleanup_state(db, task, request_details, state)
            finally:
                if lock_acquired:
                    db.scalar(select(func.pg_advisory_unlock(lock_key)))
                    db.commit()

        task = db.get(BackgroundTask, task_uuid)
        if int(state["cursor"]) < len(account_ids):
            task.status = TaskStatus.PENDING
            task.current_node = "next_account_batch"
            task.last_error = None
            _persist_manager_campaign_cleanup_state(db, task, request_details, state)
            run_manager_campaign_cleanup.delay(task_id)
            return {"status": "continued", "task_id": task_id, "cursor": state["cursor"]}

        failures = state.get("failed_accounts") or {}
        task.status = TaskStatus.FAILED if failures else TaskStatus.SUCCEEDED
        task.current_node = "cleanup_incomplete" if failures else "cleanup_complete"
        task.progress = 100
        task.last_error = f"{len(failures)} 个账户清空失败，可在任务中心续跑" if failures else None
        db.add(AuditEvent(
            project_id=task.project_id,
            actor=str(request_details.get("requested_by") or "manager-campaign-cleanup-worker"),
            action="manager.campaign_cleanup.complete",
            target_type="background_task",
            target_id=task_id,
            summary="账户管家全部计划清空完成" if not failures else "账户管家计划清空部分失败",
            details={
                "manager_id": manager_id,
                "manager_login_name": request_details.get("manager_login_name"),
                "account_count": len(account_ids),
                "processed_accounts": state["processed_accounts"],
                "deleted_campaign_count": state["deleted_campaign_count"],
                "failed_account_count": len(failures),
            },
        ))
        _persist_manager_campaign_cleanup_state(db, task, request_details, state)
        return {"status": task.status.value, "task_id": task_id, **state}


@celery_app.task
def run_manager_campaign_cleanup(task_id: str):
    task_uuid = uuid.UUID(task_id)
    lock_key = task_uuid.int & 0x7FFFFFFFFFFFFFFF
    with engine.connect() as lock_connection:
        acquired = bool(lock_connection.execute(
            text("SELECT pg_try_advisory_lock(:lock_key)"),
            {"lock_key": lock_key},
        ).scalar_one())
        if not acquired:
            return {"status": "duplicate_ignored", "task_id": task_id}
        try:
            return _run_manager_campaign_cleanup(task_id)
        finally:
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(:lock_key)"),
                {"lock_key": lock_key},
            )


@celery_app.task
def dispatch_due_campaign_batch_auto_retries():
    now = datetime.now(UTC)
    queued: list[str] = []
    with SessionLocal() as db:
        tasks = db.scalars(select(BackgroundTask).where(
            BackgroundTask.task_type == "campaign_batch_update",
            BackgroundTask.status == TaskStatus.PENDING,
            BackgroundTask.current_node.in_([
                "campaign_batch_auto_retry_wait",
                "campaign_batch_auto_retry_dispatched",
            ]),
        ).order_by(BackgroundTask.created_at)).all()
        for task in tasks:
            payload = task.result if isinstance(task.result, dict) else {}
            request_details = (
                payload.get("request")
                if isinstance(payload.get("request"), dict)
                else {}
            )
            not_before = _campaign_retry_not_before(request_details)
            waiting_is_due = (
                task.current_node == "campaign_batch_auto_retry_wait"
                and (not_before is None or not_before <= now)
            )
            dispatched_is_stale = (
                task.current_node == "campaign_batch_auto_retry_dispatched"
                and (
                    task.heartbeat_at is None
                    or task.heartbeat_at <= (
                        now - CAMPAIGN_BATCH_RETRY_DISPATCH_TIMEOUT
                    )
                )
            )
            if not waiting_is_due and not dispatched_is_stale:
                continue
            task.current_node = "campaign_batch_auto_retry_dispatched"
            task.last_error = None
            task.heartbeat_at = now
            queued.append(str(task.id))
        db.commit()
    for task_id in queued:
        run_campaign_batch_update.delay(task_id)
    return {"status": "queued", "task_ids": queued}


@celery_app.task
def sync_campaign_cache(task_id: str):
    task_uuid = uuid.UUID(task_id)
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_uuid)
        if task is None or task.project_id is None:
            return {"status": "task_missing"}
        payload = task.result if isinstance(task.result, dict) else {}
        request_details = payload.get("request") if isinstance(payload.get("request"), dict) else {}
        try:
            permission_access = _task_requester_access(
                db, task, request_details, "account_list"
            )
        except Exception as exc:
            return _block_for_permission_change(db, task, exc)
        account_ids = request_details.get("account_ids")
        if not isinstance(account_ids, list) or not account_ids:
            task.status = TaskStatus.BLOCKED
            task.current_node = "invalid_request"
            task.last_error = "计划缓存同步任务参数无效"
            db.commit()
            return {"status": "blocked", "reason": task.last_error}
        state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
        state.setdefault("cursor", 0)
        state.setdefault("processed_accounts", 0)
        state.setdefault("cached_plan_count", 0)
        state.setdefault("cached_ocpc_project_count", 0)
        state.setdefault("failed_accounts", {})
        client = platform_client(write_enabled=False)
        start = int(state["cursor"])
        stop = min(len(account_ids), start + CAMPAIGN_BATCH_ACCOUNT_CHUNK)
        for index in range(start, stop):
            try:
                account = db.get(Account, uuid.UUID(str(account_ids[index])))
            except (TypeError, ValueError):
                account = None
            if (
                account is None
                or account.project_id != task.project_id
                or not _campaign_account_matches_task_scope(account, {})
            ):
                state["cursor"] = index + 1
                continue
            try:
                require_account_scope(permission_access, account)
            except Exception as exc:
                return _block_for_permission_change(db, task, exc)
            try:
                task.status = TaskStatus.RUNNING
                task.current_node = f"sync_campaigns_{account.baidu_account_id}"
                task.progress = min(95, int(index * 100 / len(account_ids)))
                _persist_campaign_batch_state(db, task, request_details, state)
                rows = baidu_result_rows(client.execute_read(
                    call_context(account, batch=f"campaign-cache:{task_id}", idempotency_key=""),
                    "campaign.get",
                    {
                        "campaignFields": [
                            "campaignId", "campaignName", "pause", "schedule", "status", "adType",
                        ],
                        "campaignIds": [],
                        "adType": 0,
                    },
                ))
                _store_campaign_cache_rows(db, account, rows, full_sync=True)
                ocpc_rows = baidu_result_rows(client.execute_read(
                    call_context(account, batch=f"ocpc-cache:{task_id}", idempotency_key=""),
                    "ocpc.get",
                    {
                        "targetPackageTypeFields": [
                            "targetPackageId", "targetPackageName", "ocpcBid", "ocpcBidType",
                            "scope", "packageStatus",
                        ],
                        "ids": [account.baidu_account_id],
                        "level": 1,
                    },
                ))
                _store_ocpc_project_cache_rows(db, account, ocpc_rows)
                state["processed_accounts"] = int(state["processed_accounts"]) + 1
                state["cached_plan_count"] = int(state["cached_plan_count"]) + len(rows)
                state["cached_ocpc_project_count"] = int(state["cached_ocpc_project_count"]) + len(ocpc_rows)
                state["cursor"] = index + 1
                task.current_node = f"cached_{account.baidu_account_id}"
                task.progress = min(95, int((index + 1) * 100 / len(account_ids)))
                _persist_campaign_batch_state(db, task, request_details, state)
            except RateLimitError as exc:
                db.rollback()
                task = db.get(BackgroundTask, task_uuid)
                task.status = TaskStatus.PENDING
                task.current_node = "rate_limited"
                task.last_error = "百度接口限频，稍后继续同步计划缓存"
                _persist_campaign_batch_state(db, task, request_details, state)
                sync_campaign_cache.apply_async(
                    args=[task_id], countdown=rate_limit_retry_seconds(exc)
                )
                return {"status": "rate_limited", "task_id": task_id, "cursor": state["cursor"]}
            except TokenUnavailableError as exc:
                db.rollback()
                task = db.get(BackgroundTask, task_uuid)
                task.status = TaskStatus.BLOCKED
                task.current_node = "authorization_blocked"
                task.last_error = str(exc)[:500]
                _persist_campaign_batch_state(db, task, request_details, state)
                return {"status": "blocked", "reason": task.last_error}
            except Exception as exc:
                db.rollback()
                task = db.get(BackgroundTask, task_uuid)
                failures = state["failed_accounts"]
                failures[str(account.baidu_account_id)] = f"{type(exc).__name__}: {str(exc)[:220]}"
                state["cursor"] = index + 1
                task.current_node = "account_failed"
                task.last_error = failures[str(account.baidu_account_id)]
                _persist_campaign_batch_state(db, task, request_details, state)

        task = db.get(BackgroundTask, task_uuid)
        if int(state["cursor"]) < len(account_ids):
            task.status = TaskStatus.PENDING
            task.current_node = "next_account_batch"
            task.last_error = None
            _persist_campaign_batch_state(db, task, request_details, state)
            sync_campaign_cache.delay(task_id)
            return {"status": "continued", "task_id": task_id, "cursor": state["cursor"]}

        failures = state.get("failed_accounts") or {}
        task.status = TaskStatus.FAILED if failures else TaskStatus.SUCCEEDED
        task.current_node = "campaign_cache_incomplete" if failures else "complete"
        task.progress = 100
        task.last_error = f"{len(failures)} 个账户缓存同步失败" if failures else None
        db.add(AuditEvent(
            project_id=task.project_id,
            actor=str(request_details.get("requested_by") or "campaign-cache-worker"),
            action="campaign.cache.sync.complete",
            target_type="background_task",
            target_id=task_id,
            summary="账户计划缓存同步完成" if not failures else "账户计划缓存同步部分失败",
            details={
                "processed_accounts": state["processed_accounts"],
                "cached_plan_count": state["cached_plan_count"],
                "failed_account_count": len(failures),
            },
        ))
        _persist_campaign_batch_state(db, task, request_details, state)
        return {"status": task.status.value, "task_id": task_id, **state}


def _read_creative_review_chunk(
    client,
    account: Account,
    task_id: str,
    creative_ids: list[int],
    chunk_key: str,
) -> list[dict]:
    """Split a creative read when Baidu reports that one ID no longer exists."""
    if not creative_ids:
        return []
    try:
        result = client.execute_read(
            context=call_context(
                account,
                batch=f"creative-review:{task_id}:{chunk_key}",
                idempotency_key="",
            ),
            service="creative.get",
            payload={
                "creativeFields": [
                    "creativeId",
                    "status",
                    "title",
                    "description1",
                    "description2",
                    "offlineReasons",
                ],
                "idType": 7,
                "ids": creative_ids,
                "getTemp": 0,
            },
        )
        return baidu_result_rows(result)
    except RuntimeError as exc:
        if "90114" not in str(exc):
            raise
        if len(creative_ids) == 1:
            return []
        midpoint = len(creative_ids) // 2
        return [
            *_read_creative_review_chunk(
                client,
                account,
                task_id,
                creative_ids[:midpoint],
                f"{chunk_key}a",
            ),
            *_read_creative_review_chunk(
                client,
                account,
                task_id,
                creative_ids[midpoint:],
                f"{chunk_key}b",
            ),
        ]


@celery_app.task
def sync_project_creative_reviews(project_id: str, task_id: str):
    project_uuid = uuid.UUID(project_id)
    task_uuid = uuid.UUID(task_id)
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_uuid)
        if not task:
            return {"status": "task_missing"}
        try:
            checkpoint(db, task, "load_assignments", 5)
            assignments = db.scalars(
                select(CreativeAssignment)
                .join(Account, CreativeAssignment.account_id == Account.id)
                .where(
                    CreativeAssignment.project_id == project_uuid,
                    CreativeAssignment.baidu_creative_id.is_not(None),
                    CreativeAssignment.status.notin_([
                        "deleted", "replaced", "deleted_waiting_material", "deleted_waiting_payload",
                    ]),
                    effective_testing_condition(),
                    api_eligible_account_condition(),
                )
            ).all()
            if not assignments:
                task.status = TaskStatus.SUCCEEDED
                task.current_node = "complete"
                task.progress = 100
                task.result = {"checked": 0, "message": "暂无已登记百度创意ID的投放记录"}
                completed_at = datetime.now(UTC)
                task.heartbeat_at = completed_at
                update_project_watermark(
                    db,
                    source="baidu_creative_review",
                    project_id=project_uuid,
                    status="succeeded",
                    message="no eligible creative assignments",
                    source_at=completed_at,
                )
                db.commit()
                return task.result

            account_ids = {row.account_id for row in assignments}
            accounts = {
                row.id: row
                for row in db.scalars(select(Account).where(Account.id.in_(account_ids))).all()
            }
            grouped: dict[uuid.UUID, list[CreativeAssignment]] = {}
            for assignment in assignments:
                grouped.setdefault(assignment.account_id, []).append(assignment)

            client = platform_client()
            write_client = platform_client(
                write_enabled=settings.creative_auto_rebuild_enabled
            )
            checked = rejected = blacklisted = segment_blacklisted = deleted = replenished = pending_delete = 0
            account_total = max(1, len(grouped))
            for account_index, (account_id, account_assignments) in enumerate(grouped.items(), start=1):
                account = accounts.get(account_id)
                if not account:
                    continue
                checkpoint(db, task, f"query_account_{account.baidu_account_id}", 10 + int(45 * (account_index - 1) / account_total))
                creative_ids = [int(row.baidu_creative_id) for row in account_assignments if row.baidu_creative_id]
                remote_rows: list[dict] = []
                for offset in range(0, len(creative_ids), 3000):
                    chunk = creative_ids[offset: offset + 3000]
                    remote_rows.extend(_read_creative_review_chunk(
                        client,
                        account,
                        task_id,
                        chunk,
                        str(offset),
                    ))
                remote_map = {
                    int(row["creativeId"]): row
                    for row in remote_rows
                    if row.get("creativeId") is not None
                }
                rejected_for_rebuild: list[CreativeAssignment] = []
                for assignment in account_assignments:
                    creative = remote_map.get(int(assignment.baidu_creative_id))
                    assignment.review_checked_at = datetime.now(UTC)
                    checked += 1
                    if creative is None:
                        assignment.status = "remote_missing"
                        continue
                    main_reason, detail_reason = extract_main_reason(creative)
                    assignment.main_reason = main_reason
                    assignment.detail_reason = detail_reason
                    remote_status = creative.get("status")
                    if main_reason != "3":
                        assignment.status = "approved" if remote_status == 51 else "reviewing"
                        continue

                    rejected += 1
                    if account.account_type == AccountType.SECOND_HOP:
                        if not assignment.rejection_recorded:
                            combination = db.get(CreativeCombination, assignment.combination_id)
                            if combination:
                                combination_was_blacklisted, newly_blacklisted_segments = (
                                    record_second_hop_creative_rejection(db, combination)
                                )
                                if combination_was_blacklisted:
                                    blacklisted += 1
                                segment_blacklisted += newly_blacklisted_segments
                            assignment.rejection_recorded = True
                    assignment.status = "rejected_pending_delete"
                    rejected_for_rebuild.append(assignment)
                    pending_delete += 1
                db.commit()

                if not rejected_for_rebuild or not settings.creative_auto_rebuild_enabled:
                    continue
                checkpoint(db, task, f"delete_account_{account.baidu_account_id}", 55 + int(20 * account_index / account_total))
                for batch_number, assignment_batch in enumerate(
                    chunks(rejected_for_rebuild, 3000), start=1
                ):
                    delete_ids = [
                        int(row.baidu_creative_id)
                        for row in assignment_batch
                        if row.baidu_creative_id
                    ]
                    write_client.execute_write(
                        context=call_context(
                            account,
                            batch=f"creative-review:{task_id}",
                            idempotency_key=(
                                f"creative-delete:{task_id}:"
                                f"{account.baidu_account_id}:{batch_number}"
                            ),
                        ),
                        service="creative.delete",
                        payload={"creativeIds": delete_ids},
                    )
                    for assignment in assignment_batch:
                        assignment.status = "deleted"
                        assignment.deleted_at = datetime.now(UTC)
                        deleted += 1
                    db.commit()

                segments = db.scalars(select(CreativeSegment).where(CreativeSegment.project_id == project_uuid)).all()
                combinations = db.scalars(select(CreativeCombination).where(CreativeCombination.project_id == project_uuid)).all()
                combination_map = {row.combination_hash: row for row in combinations}
                combination_by_id = {row.id: row for row in combinations}
                blocked_hashes = {row.combination_hash for row in combinations if row.is_blacklisted}
                active_hashes = {
                    combination_by_id[row.combination_id].combination_hash
                    for row in db.scalars(select(CreativeAssignment).where(
                        CreativeAssignment.account_id == account.id,
                        CreativeAssignment.status.notin_([
                            "deleted", "replaced", "deleted_waiting_material", "deleted_waiting_payload",
                        ]),
                    )).all()
                    if row.combination_id in combination_by_id
                }
                replacement_rows: list[tuple[CreativeAssignment, CreativeAssignment, dict]] = []
                for old_assignment in rejected_for_rebuild:
                    candidates = select_random_creative_combinations(
                        segments,
                        blocked_hashes,
                        seed=f"replenish:{old_assignment.id}:{old_assignment.generation + 1}",
                        limit=50,
                    )
                    candidate = next((item for item in candidates if item.combination_hash not in active_hashes), None)
                    if candidate is None:
                        old_assignment.status = "deleted_waiting_material"
                        continue
                    source_payload = dict(old_assignment.creative_payload or {})
                    required = {"campaignId", "adgroupId", "mobileDestinationUrl", "mobileDisplayUrl", "pcDestinationUrl", "pcDisplayUrl"}
                    if not required.issubset(source_payload):
                        old_assignment.status = "deleted_waiting_payload"
                        continue
                    combination = combination_map.get(candidate.combination_hash)
                    if combination is None:
                        combination = CreativeCombination(
                            id=uuid.uuid4(),
                            project_id=project_uuid,
                            title_segment_id=candidate.title_id,
                            description1_segment_id=candidate.description1_id,
                            description2_segment_id=candidate.description2_id,
                            combination_hash=candidate.combination_hash,
                        )
                        db.add(combination)
                        combination_map[candidate.combination_hash] = combination
                    source_payload.update({
                        "title": candidate.title,
                        "description1": candidate.description1,
                        "description2": candidate.description2,
                    })
                    replacement = CreativeAssignment(
                        id=uuid.uuid4(),
                        project_id=project_uuid,
                        job_id=old_assignment.job_id,
                        account_id=old_assignment.account_id,
                        combination_id=combination.id,
                        slot_number=old_assignment.slot_number,
                        generation=old_assignment.generation + 1,
                        status="replacement_pending_submit",
                        creative_payload=source_payload,
                    )
                    db.add(replacement)
                    replacement_rows.append((old_assignment, replacement, source_payload))
                    active_hashes.add(candidate.combination_hash)
                db.flush()
                for batch_number, replacement_batch in enumerate(
                    chunks(replacement_rows, 3000), start=1
                ):
                    add_result = write_client.execute_write(
                        context=call_context(
                            account,
                            batch=f"creative-review:{task_id}",
                            idempotency_key=(
                                f"creative-replenish:{task_id}:"
                                f"{account.baidu_account_id}:{batch_number}"
                            ),
                        ),
                        service="creative.add",
                        payload={
                            "creativeTypes": [
                                payload for _, _, payload in replacement_batch
                            ]
                        },
                    )
                    added_rows = baidu_result_rows(add_result)
                    for index, (old_assignment, replacement, _) in enumerate(replacement_batch):
                        if index >= len(added_rows) or added_rows[index].get("creativeId") is None:
                            replacement.status = "replacement_result_unknown"
                            continue
                        replacement.baidu_creative_id = int(added_rows[index]["creativeId"])
                        replacement.status = "submitted"
                        replacement.submitted_at = datetime.now(UTC)
                        old_assignment.status = "replaced"
                        replenished += 1
                    db.commit()

            task.status = TaskStatus.SUCCEEDED
            task.current_node = "complete"
            task.progress = 100
            task.result = {
                "checked": checked,
                "rejected": rejected,
                "second_hop_blacklisted": blacklisted,
                "second_hop_segment_blacklisted": segment_blacklisted,
                "pending_delete": pending_delete - deleted,
                "deleted": deleted,
                "replenished": replenished,
                "creative_auto_rebuild_enabled": settings.creative_auto_rebuild_enabled,
            }
            completed_at = datetime.now(UTC)
            task.heartbeat_at = completed_at
            update_project_watermark(
                db,
                source="baidu_creative_review",
                project_id=project_uuid,
                status="succeeded",
                message=f"checked {checked}; rejected {rejected}",
                source_at=completed_at,
            )
            db.add(AuditEvent(
                project_id=project_uuid,
                actor="system",
                action="creative_review.sync.complete",
                target_type="background_task",
                target_id=task_id,
                summary="同步创意审核状态并执行审核治理",
                details=task.result,
            ))
            db.commit()
            return task.result
        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.current_node = "failed"
            task.last_error = str(exc)[:1000]
            task.retry_count += 1
            update_project_watermark(
                db,
                source="baidu_creative_review",
                project_id=project_uuid,
                status="failed",
                message=task.last_error,
            )
            db.commit()
            return {"status": "failed", "error": task.last_error}


@celery_app.task
def queue_due_creative_review_syncs():
    with SessionLocal() as db:
        project_ids = db.scalars(
            select(Project.id).where(Project.enabled.is_(True))
        ).all()
        queued: list[tuple[str, str]] = []
        for project_id in project_ids:
            running = db.scalar(select(BackgroundTask.id).where(
                BackgroundTask.project_id == project_id,
                BackgroundTask.task_type == "creative_review_sync",
                BackgroundTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
            ).limit(1))
            if running is not None:
                continue
            task = BackgroundTask(
                project_id=project_id,
                task_type="creative_review_sync",
                current_node="queued",
                progress=0,
            )
            db.add(task)
            db.flush()
            queued.append((str(project_id), str(task.id)))
        db.commit()
    for project_id, task_id in queued:
        sync_project_creative_reviews.delay(project_id, task_id)
    return {"status": "queued", "project_count": len(queued)}


@celery_app.task
def dispatch_ad_build_batch(batch_id: str):
    """Dispatch one persistent batch only when writes and the full workflow executor are ready."""
    with SessionLocal() as db:
        batch = db.get(AdBuildBatch, uuid.UUID(batch_id))
        if not batch:
            return {"status": "batch_missing"}
        job = db.get(AdBuildJob, batch.job_id)
        if not job:
            return {"status": "job_missing"}
        if job.workflow_version != WORKFLOW_VERSION:
            batch.status = "superseded"
            job.status = "superseded"
            db.commit()
            return {"status": "superseded", "workflow_version": job.workflow_version}
        now = datetime.now(UTC)
        if batch.scheduled_at > now:
            countdown = max(1, int((batch.scheduled_at - now).total_seconds()))
            dispatch_ad_build_batch.apply_async(args=[batch_id], countdown=min(countdown, 3600))
            return {"status": "not_due", "countdown": countdown}
        if not settings.baidu_writes_enabled:
            batch.status = "waiting_writes"
            job.status = "waiting_writes"
            db.commit()
            return {"status": "waiting_writes"}
        if not AD_BUILD_WORKFLOW_EXECUTOR_REGISTERED:
            batch.status = "waiting_baidu_api"
            job.status = "waiting_baidu_api"
            db.commit()
            return {"status": "waiting_baidu_api"}

        task_ids: list[str] = []
        for operation_id in batch.operation_ids:
            operation = db.scalar(
                select(Operation)
                .where(Operation.id == uuid.UUID(operation_id))
                .with_for_update()
            )
            if not operation or operation.status == OperationStatus.SUCCEEDED:
                continue
            if db.scalar(select(Account.id).where(Account.baidu_account_id == operation.target_account_id, Account.permission_status == 'archived')):
                continue
            task = db.scalar(
                select(BackgroundTask)
                .where(BackgroundTask.operation_id == operation.id)
                .order_by(BackgroundTask.created_at.desc(), BackgroundTask.id.desc())
                .limit(1)
            )
            if (
                task is not None
                and isinstance(task.result, dict)
                and task.result.get("cancelled")
            ):
                continue
            operation.status = OperationStatus.QUEUED
            if task is None or task.status != TaskStatus.PENDING:
                task = BackgroundTask(
                    project_id=job.project_id,
                    operation_id=operation.id,
                    task_type=operation.operation_type,
                    status=TaskStatus.PENDING,
                )
                db.add(task)
                db.flush()
            else:
                task.current_node = "queued"
                task.heartbeat_at = now
            task_ids.append(str(task.id))
        batch.status = "dispatched"
        batch.dispatched_at = now
        job.status = "running"
        db.commit()
        for task_id in task_ids:
            execute_operation.delay(task_id)
        return {"status": "dispatched", "task_count": len(task_ids)}


@celery_app.task
def dispatch_due_ad_build_batches():
    with SessionLocal() as db:
        now = datetime.now(UTC)
        rows = db.scalars(
            select(AdBuildBatch)
            .where(
                AdBuildBatch.status.in_(["ready", "scheduled", "waiting_writes", "waiting_baidu_api"]),
                AdBuildBatch.scheduled_at <= now,
            )
            .order_by(AdBuildBatch.scheduled_at)
            .limit(100)
        ).all()
        batch_ids = [str(row.id) for row in rows]
    for batch_id in batch_ids:
        dispatch_ad_build_batch.delay(batch_id)
    return {"status": "queued", "batch_count": len(batch_ids)}


@celery_app.task
def sync_reference_account_template(task_id: str, project_id: str, requested_by: str = "system"):
    """Distill reusable settings from account 86459649 without persisting its ad objects."""
    task_uuid = uuid.UUID(task_id)
    project_uuid = uuid.UUID(project_id)
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_uuid)
        account = db.scalar(select(Account).where(
            Account.project_id == project_uuid,
            Account.baidu_account_id == REFERENCE_ACCOUNT_ID,
        ))
        if task is None or account is None:
            return {"status": "missing_reference_account"}
        try:
            checkpoint(db, task, "read_account_and_campaigns", 5)
            client = platform_client()
            context = call_context(account, batch=f"reference-template:{task_id}", idempotency_key="")
            account_rows = baidu_result_rows(client.execute_read(context, "account.get", {
                "accountFields": ["userId", "budget", "budgetType", "regionTarget", "geoLocationStatus"],
            }))
            account_info = account_rows[0] if account_rows else {}
            campaigns = baidu_result_rows(client.execute_read(context, "campaign.get", {
                "campaignFields": [
                    "campaignId", "campaignName", "regionTarget", "negativeWords", "exactNegativeWords",
                    "pause", "schedule", "status", "equipmentType", "marketingTargetId", "businessPointId",
                    "businessPointName", "geoLocationStatus", "campaignBidType", "campaignBid",
                    "campaignOcpcBidType", "campaignOcpcBid", "campaignCvSources", "campaignTransTypes",
                    "transAsset", "transAssetId",
                ],
                "campaignIds": [], "adType": 0,
            }))
            campaign_ids = [int(row["campaignId"]) for row in campaigns if row.get("campaignId") is not None]

            checkpoint(db, task, "read_units", 20)
            adgroups: list[dict] = []
            for ids in chunks(campaign_ids, 100):
                adgroups.extend(baidu_result_rows(client.execute_read(context, "adgroup.get", {
                    "ids": ids, "idType": 3, "getTemp": 0,
                    "adgroupFields": [
                        "adgroupId", "campaignId", "adgroupName", "pause", "maxPrice", "negativeWords",
                        "exactNegativeWords", "status", "segmentRecommendStatus", "creativeTextOptimizationStatus",
                        "pcFinalUrl", "mobileFinalUrl", "adgroupAutoTargetingStatus",
                    ],
                })))
            checkpoint(db, task, "read_projects_and_audiences", 55)
            projects = baidu_result_rows(client.execute_read(context, "ocpc.get", {
                "targetPackageTypeFields": [
                    "targetPackageId", "targetPackageName", "ocpcBid", "ocpcBidType", "scope",
                    "dataFlowData", "assistTransTypes", "ocpcDeepCpa", "packageStatus", "deepTypeStat",
                    "deepTransTypeMode", "transAsset", "transAssetId", "assetType", "crowdDefinedOcpcBidRatio",
                ],
                "ids": [int(account_info.get("userId") or REFERENCE_ACCOUNT_ID)], "level": 1,
            }))
            crowds = baidu_result_rows(client.execute_read(context, "crowd.get", {
                "crowdFields": [
                    "crowdId", "crowdName", "age", "customAge", "sex", "inPeople", "idPack",
                    "crowdDirectType", "effectType", "createTime", "conversionLevel", "recentDays",
                    "campaignIds", "creativeIds", "deviceProperty",
                ],
                "crowdDirectType": [0, 3, 4, 10], "limit": [1000], "desc": True,
            }))
            bindings: list[dict] = []
            for ids in chunks(campaign_ids, 100):
                bindings.extend(baidu_result_rows(client.execute_read(context, "crowd.bind.get", {
                    "crowdBindFields": ["bindId", "targetType", "targetId", "crowdPriceRatio", "campaignId", "crowdId"],
                    "idType": 3, "ids": ids,
                })))

            checkpoint(db, task, "freeze_and_analyze", 85)
            template_data, source_summary, analysis = analyze_reference_snapshot(
                account_info, campaigns, adgroups, [], [], projects, crowds, bindings,
            )
            version_number = (db.scalar(select(func.max(ReferenceTemplateVersion.version)).where(
                ReferenceTemplateVersion.project_id == project_uuid,
                ReferenceTemplateVersion.source_account_id == REFERENCE_ACCOUNT_ID,
            )) or 0) + 1

            for prior in db.scalars(select(ReferenceTemplateVersion).where(
                ReferenceTemplateVersion.project_id == project_uuid,
                ReferenceTemplateVersion.source_account_id == REFERENCE_ACCOUNT_ID,
                ReferenceTemplateVersion.is_active.is_(True),
            )).all():
                prior.is_active = False
            version = ReferenceTemplateVersion(
                project_id=project_uuid, source_account_id=REFERENCE_ACCOUNT_ID,
                source_login_name=account.login_name, manager_login_name=account.manager_login_name,
                version=version_number, status="ready", hierarchy_counts=source_summary,
                template_data=template_data, analysis=analysis, raw_data_path=None,
                raw_sha256=None, is_active=True, created_by=requested_by,
            )
            db.add(version)
            db.flush()

            task.status = TaskStatus.SUCCEEDED
            task.current_node = "template_ready"
            task.progress = 100
            task.last_error = None
            task.heartbeat_at = datetime.now(UTC)
            task.result = {"template_version_id": str(version.id), "version": version.version, "source_summary": source_summary, "analysis": analysis}
            db.add(AuditEvent(
                project_id=project_uuid, actor=requested_by, action="reference_template.sync",
                target_type="reference_template_version", target_id=str(version.id),
                summary="固化参考账户86459649可复用设置", details={"version": version.version, **source_summary},
            ))
            db.commit()
            return {"status": "succeeded", "template_version_id": str(version.id), "version": version.version, **source_summary}
        except Exception as exc:
            db.rollback()
            task = db.get(BackgroundTask, task_uuid)
            if task is not None:
                task.status = TaskStatus.FAILED
                task.current_node = "reference_sync_failed"
                task.progress = 0
                task.last_error = f"参考账户同步失败：{type(exc).__name__}: {str(exc)[:300]}"
                task.heartbeat_at = datetime.now(UTC)
                db.commit()
            return {"status": "failed", "error_type": type(exc).__name__}


SHANGHAI = ZoneInfo("Asia/Shanghai")
ACCOUNT_REFRESH_TASK_TYPES = (
    "baidu_account_backfill",
    "baidu_account_hourly_refresh",
    "baidu_account_final_archive",
)
HOURLY_ACCOUNT_SELECTION = "testing_only"
FINAL_ARCHIVE_ACCOUNT_SELECTION = "testing_as_of_previous_day"
KEYWORD_REPORT_SCOPE = "keyword_daily_second_hop_material_exact"
KEYWORD_REFRESH_TASK_TYPES = (
    "baidu_keyword_backfill",
    "baidu_keyword_daily_archive",
)


def effective_testing_condition():
    return or_(
        Account.lifecycle_override == TESTING,
        and_(Account.lifecycle_override.is_(None), Account.lifecycle_stage == TESTING),
    )


def effective_balance_lifecycle_condition():
    """Only empty and testing accounts may be queried for live balance."""
    return or_(
        Account.lifecycle_override.in_([EMPTY, TESTING]),
        and_(
            Account.lifecycle_override.is_(None),
            Account.lifecycle_stage.in_([EMPTY, TESTING]),
        ),
    )


def eliminated_api_blacklist_condition():
    return or_(
        Account.eliminated_at.is_not(None),
        Account.lifecycle_stage == ELIMINATED,
        Account.lifecycle_override == ELIMINATED,
    )


def api_eligible_account_condition():
    return and_(
        Account.eliminated_at.is_(None),
        or_(Account.lifecycle_stage.is_(None), Account.lifecycle_stage != ELIMINATED),
        or_(Account.lifecycle_override.is_(None), Account.lifecycle_override != ELIMINATED),
    )


def local_day_utc_bounds(target_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(target_date, time.min, tzinfo=SHANGHAI).astimezone(UTC)
    return start, start + timedelta(days=1)


def account_report_conditions(project_id: uuid.UUID, request_details: dict) -> tuple:
    conditions: list = [Account.project_id == project_id, Account.is_active.is_(True)]
    trigger = str(request_details.get("trigger") or "")
    if trigger == "final_archive":
        final_date = date.fromisoformat(str(request_details.get("date_to") or request_details.get("eliminated_on")))
        final_start, final_end = local_day_utc_bounds(final_date)
        conditions.append(or_(
            api_eligible_account_condition(),
            and_(Account.eliminated_at >= final_start, Account.eliminated_at < final_end),
        ))
    else:
        # Eliminated accounts are a durable API blacklist. Only the next-day
        # final archive above may read their final day once.
        conditions.append(api_eligible_account_condition())
    account_ids = request_details.get("account_ids")
    if isinstance(account_ids, list):
        parsed_ids = []
        for value in account_ids:
            try:
                parsed_ids.append(uuid.UUID(str(value)))
            except (TypeError, ValueError):
                continue
        conditions.append(Account.id.in_(parsed_ids) if parsed_ids else Account.id.is_(None))
        return tuple(conditions)

    selection = str(request_details.get("account_selection") or "all_active")
    if selection == HOURLY_ACCOUNT_SELECTION:
        conditions.append(effective_testing_condition())
    elif selection in {
        FINAL_ARCHIVE_ACCOUNT_SELECTION,
        "testing_and_eliminated_on",  # Compatibility with already queued tasks.
    }:
        eliminated_on = date.fromisoformat(str(request_details["eliminated_on"]))
        start, end = local_day_utc_bounds(eliminated_on)
        conditions.append(or_(
            effective_testing_condition(),
            and_(Account.eliminated_at >= start, Account.eliminated_at < end),
        ))
    elif selection != "all_active":
        raise ValueError("unsupported account report selection")
    return tuple(conditions)


def keyword_report_conditions(project_id: uuid.UUID, request_details: dict) -> tuple:
    """Use the account-cycle snapshot but permanently exclude one-hop accounts."""
    return (
        *account_report_conditions(project_id, request_details),
        Account.account_type == AccountType.SECOND_HOP,
    )


def mark_daily_source_complete(
    db,
    project_id: uuid.UUID,
    report_date: date,
    source: str,
    *,
    completed_at: datetime | None = None,
) -> DailyDataStatus:
    completed_at = completed_at or datetime.now(UTC)
    row = db.scalar(select(DailyDataStatus).where(
        DailyDataStatus.project_id == project_id,
        DailyDataStatus.report_date == report_date,
    ))
    if row is None:
        row = DailyDataStatus(project_id=project_id, report_date=report_date)
        db.add(row)
    if source == "baidu":
        row.baidu_completed_at = completed_at
    elif source == "hduofen":
        row.hduofen_completed_at = completed_at
    elif source == "keyword":
        row.keyword_completed_at = completed_at
    else:
        raise ValueError("unsupported daily source")
    if (
        row.final_requested_at is not None
        and row.baidu_completed_at is not None
        and row.hduofen_completed_at is not None
        and row.keyword_completed_at is not None
        and row.baidu_completed_at >= row.final_requested_at
        and row.hduofen_completed_at >= row.final_requested_at
        and row.keyword_completed_at >= row.final_requested_at
    ):
        row.finalized_at = completed_at
    return row


def _preference_enabled(preferences: dict[tuple[uuid.UUID, str], ProjectPreference], project_id, key: str) -> bool:
    preference = preferences.get((project_id, key))
    return bool(
        preference
        and isinstance(preference.value, dict)
        and preference.value.get("enabled") is True
    )


def _queue_account_report(
    db,
    project_id: uuid.UUID,
    target_date: date,
    *,
    account_ids: list[uuid.UUID],
    task_type: str,
    trigger: str,
    account_selection: str,
) -> str | None:
    running = db.scalar(select(BackgroundTask.id).where(
        BackgroundTask.project_id == project_id,
        BackgroundTask.task_type.in_(ACCOUNT_REFRESH_TASK_TYPES),
        BackgroundTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
    ).limit(1))
    if running is not None:
        return None
    task = BackgroundTask(
        project_id=project_id,
        task_type=task_type,
        current_node="queued",
        result={
            "request": {
                "date_from": target_date.isoformat(),
                "date_to": target_date.isoformat(),
                "scope": "account_daily",
                "report_type": 170026,
                "trigger": trigger,
                "account_selection": account_selection,
                "account_ids": [str(item) for item in account_ids],
            },
            "state": {},
        },
    )
    db.add(task)
    db.flush()
    return str(task.id)


def _queue_hduofen_capture(
    db,
    project_id: uuid.UUID,
    target_date: date,
    *,
    account_ids: list[uuid.UUID],
    trigger: str,
) -> str | None:
    running = db.scalar(select(BackgroundTask.id).where(
        BackgroundTask.project_id == project_id,
        BackgroundTask.task_type == "hduofen_capture",
        BackgroundTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
    ).limit(1))
    if running is not None:
        return None
    task = BackgroundTask(
        project_id=project_id,
        task_type="hduofen_capture",
        current_node="queued",
        result={"request": {
            "date_from": target_date.isoformat(),
            "date_to": target_date.isoformat(),
            "trigger": trigger,
            "allowed_account_ids": [str(item) for item in account_ids],
        }},
    )
    db.add(task)
    db.flush()
    return str(task.id)


def _queue_keyword_report(
    db,
    project_id: uuid.UUID,
    target_date: date,
    *,
    account_ids: list[uuid.UUID],
    trigger: str,
    account_selection: str,
) -> str | None:
    running = db.scalar(select(BackgroundTask.id).where(
        BackgroundTask.project_id == project_id,
        BackgroundTask.task_type.in_(KEYWORD_REFRESH_TASK_TYPES),
        BackgroundTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
    ).limit(1))
    if running is not None:
        return None
    task = BackgroundTask(
        project_id=project_id,
        task_type="baidu_keyword_daily_archive",
        current_node="queued",
        result={
            "request": {
                "date_from": target_date.isoformat(),
                "date_to": target_date.isoformat(),
                "scope": KEYWORD_REPORT_SCOPE,
                "report_type": 2602783,
                "trigger": trigger,
                "account_selection": account_selection,
                "account_type": AccountType.SECOND_HOP.value,
                "account_ids": [str(item) for item in account_ids],
                "match_mode": "exact_after_deleted_marker_removal",
            },
            "state": {},
        },
    )
    db.add(task)
    db.flush()
    return str(task.id)


def _queue_finance_payment_sync(
    db,
    project_id: uuid.UUID,
    target_date: date,
    *,
    trigger: str,
) -> str | None:
    running = db.scalar(select(BackgroundTask.id).where(
        BackgroundTask.project_id == project_id,
        BackgroundTask.task_type == "baidu_finance_payment_sync",
        BackgroundTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
    ).limit(1))
    if running is not None:
        return None
    has_recharge_account = db.scalar(select(AccountManager.id).where(
        AccountManager.project_id == project_id,
        AccountManager.is_active.is_(True),
        AccountManager.recharge_account.is_not(None),
    ).limit(1))
    if has_recharge_account is None:
        return None
    task = BackgroundTask(
        project_id=project_id,
        task_type="baidu_finance_payment_sync",
        current_node="queued",
        result={
            "request": {
                "date_from": target_date.isoformat(),
                "date_to": target_date.isoformat(),
                "trigger": trigger,
                "fund_types": [1, 2, 21, 22, 23],
            },
            "state": {},
        },
    )
    db.add(task)
    db.flush()
    return str(task.id)


def _queue_data_cycle(target_date: date, *, final: bool, project_ids: list[uuid.UUID] | None = None) -> dict:
    baidu_tasks: list[str] = []
    hduofen_tasks: list[tuple[str, str]] = []
    keyword_tasks: list[str] = []
    finance_tasks: list[str] = []
    trigger = "final_archive" if final else "hourly_refresh"
    selection = (
        FINAL_ARCHIVE_ACCOUNT_SELECTION
        if final
        else HOURLY_ACCOUNT_SELECTION
    )
    with SessionLocal() as db:
        project_query = select(Project).where(Project.enabled.is_(True))
        if project_ids:
            project_query = project_query.where(Project.id.in_(project_ids))
        projects = db.scalars(project_query).all()
        preference_rows = db.scalars(select(ProjectPreference).where(
            ProjectPreference.key.in_(["baidu_account_report", "tracking"])
        )).all()
        preferences = {(row.project_id, row.key): row for row in preference_rows}
        for project in projects:
            request_details = {
                "account_selection": selection,
                "trigger": trigger,
                "date_from": target_date.isoformat(),
                "date_to": target_date.isoformat(),
            }
            if final:
                request_details["eliminated_on"] = target_date.isoformat()
                status = db.scalar(select(DailyDataStatus).where(
                    DailyDataStatus.project_id == project.id,
                    DailyDataStatus.report_date == target_date,
                ))
                if status is not None and status.finalized_at is not None:
                    # A completed final archive is immutable. Do not enqueue
                    # duplicate Baidu or Hduofen calls for the same data date.
                    continue
                if status is None:
                    status = DailyDataStatus(project_id=project.id, report_date=target_date)
                    db.add(status)
                status.final_requested_at = datetime.now(UTC)
                status.finalized_at = None
            account_ids = list(db.scalars(
                select(Account.id)
                .where(*account_report_conditions(project.id, request_details))
                .order_by(Account.baidu_account_id)
            ).all())
            keyword_account_ids = list(db.scalars(
                select(Account.id)
                .where(
                    Account.project_id == project.id,
                    Account.id.in_(account_ids),
                    Account.account_type == AccountType.SECOND_HOP,
                )
                .order_by(Account.baidu_account_id)
            ).all()) if final else []
            if _preference_enabled(preferences, project.id, "baidu_account_report"):
                task_id = _queue_account_report(
                    db,
                    project.id,
                    target_date,
                    account_ids=account_ids,
                    task_type=(
                        "baidu_account_final_archive" if final
                        else "baidu_account_hourly_refresh"
                    ),
                    trigger=trigger,
                    account_selection=selection,
                )
                if task_id:
                    baidu_tasks.append(task_id)
            if _preference_enabled(preferences, project.id, "tracking"):
                task_id = _queue_hduofen_capture(
                    db,
                    project.id,
                    target_date,
                    account_ids=account_ids,
                    trigger=trigger,
                )
                if task_id:
                    hduofen_tasks.append((task_id, str(project.id)))
            if final:
                task_id = _queue_keyword_report(
                    db,
                    project.id,
                    target_date,
                    account_ids=keyword_account_ids,
                    trigger=trigger,
                    account_selection=selection,
                )
                if task_id:
                    keyword_tasks.append(task_id)
            finance_task_id = _queue_finance_payment_sync(
                db,
                project.id,
                target_date,
                trigger=trigger,
            )
            if finance_task_id:
                finance_tasks.append(finance_task_id)
        db.commit()
    for task_id in baidu_tasks:
        sync_baidu_account_backfill.delay(task_id)
    for task_id, project_id in hduofen_tasks:
        capture_hduofen_for_task.delay(
            task_id,
            project_id,
            target_date.isoformat(),
            target_date.isoformat(),
        )
    for task_id in keyword_tasks:
        sync_baidu_keyword_backfill.delay(task_id)
    for task_id in finance_tasks:
        sync_finance_payments.delay(task_id)
    return {
        "status": "queued",
        "trigger": trigger,
        "date": target_date.isoformat(),
        "baidu_task_ids": baidu_tasks,
        "hduofen_task_ids": [item[0] for item in hduofen_tasks],
        "keyword_task_ids": keyword_tasks,
        "finance_task_ids": finance_tasks,
    }


FINANCE_FUND_TYPES = (1, 2, 21, 22, 23)
FINANCE_PAYMENT_PAGE_SIZE = 500


def _payment_result_rows(result: dict) -> list[dict]:
    candidates: list[object] = [result.get("list")]
    for key in ("body", "data"):
        value = result.get(key)
        if isinstance(value, dict):
            candidates.extend([value.get("list"), value.get("data")])
        elif isinstance(value, list):
            candidates.append(value)
    for candidate in candidates:
        if isinstance(candidate, list):
            return [row for row in candidate if isinstance(row, dict)]
    return []


def _finance_datetime(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(UTC)


def _decimal_amount(value: object) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0.00")


def _upsert_finance_payment_rows(
    db,
    *,
    project_id: uuid.UUID,
    manager: AccountManager,
    account: Account,
    fund_type: int,
    rows: list[dict],
    fetched_at: datetime,
) -> tuple[int, int]:
    upserted = 0
    last_remote_id = 0
    for raw in rows:
        try:
            remote_id = int(raw.get("id") or 0)
        except (TypeError, ValueError):
            continue
        pay_time = _finance_datetime(raw.get("paytime"))
        if remote_id <= 0 or pay_time is None:
            continue
        local_pay_date = pay_time.astimezone(SHANGHAI).date()
        if fund_type == 23:
            cash_amount = _decimal_amount(raw.get("cash"))
            bonus_amount = _decimal_amount(raw.get("bonus"))
            account_currency = cash_amount + bonus_amount
        else:
            account_currency = _decimal_amount(raw.get("fund"))
            cash_amount = account_currency if fund_type in (1, 21) else Decimal("0.00")
            bonus_amount = account_currency if fund_type in (2, 22) else Decimal("0.00")
        values = {
            "id": uuid.uuid4(),
            "project_id": project_id,
            "manager_id": manager.id,
            "account_id": account.id,
            "fund_type": fund_type,
            "remote_record_id": remote_id,
            "pay_date": local_pay_date,
            "pay_time": pay_time,
            "actual_time": _finance_datetime(raw.get("acttime")),
            "movement_type": "recharge" if account_currency >= 0 else "refund",
            "account_currency": account_currency,
            "cash_amount": cash_amount,
            "bonus_amount": bonus_amount,
            "pay_method_name": str(raw.get("paymethodName") or "")[:200] or None,
            "product_name": str(raw.get("productName") or "")[:200] or None,
            "pending_type_name": str(raw.get("cachetypeName") or "")[:200] or None,
            "payment_status": int(raw["actflag"]) if raw.get("actflag") is not None else None,
            "payment_status_name": str(raw.get("billStatus") or "")[:100] or None,
            "order_row": str(raw.get("orderrow") or "")[:200] or None,
            "raw_payload": raw,
            "source_watermark": fetched_at,
            "created_at": fetched_at,
            "updated_at": fetched_at,
        }
        excluded = pg_insert(FinancePaymentRecord).excluded
        statement = pg_insert(FinancePaymentRecord).values(**values).on_conflict_do_update(
            index_elements=["project_id", "manager_id", "fund_type", "remote_record_id"],
            set_={
                "account_id": excluded.account_id,
                "pay_date": excluded.pay_date,
                "pay_time": excluded.pay_time,
                "actual_time": excluded.actual_time,
                "movement_type": excluded.movement_type,
                "account_currency": excluded.account_currency,
                "cash_amount": excluded.cash_amount,
                "bonus_amount": excluded.bonus_amount,
                "pay_method_name": excluded.pay_method_name,
                "product_name": excluded.product_name,
                "pending_type_name": excluded.pending_type_name,
                "payment_status": excluded.payment_status,
                "payment_status_name": excluded.payment_status_name,
                "order_row": excluded.order_row,
                "raw_payload": excluded.raw_payload,
                "source_watermark": excluded.source_watermark,
                "updated_at": excluded.updated_at,
            },
        )
        db.execute(statement)
        upserted += 1
        last_remote_id = max(last_remote_id, remote_id)
    return upserted, last_remote_id


def _finish_finance_payment_task(db, task: BackgroundTask, request_details: dict, state: dict) -> dict:
    failures = state.get("failures") or {}
    task.result = {"request": request_details, "state": state}
    flag_modified(task, "result")
    task.status = TaskStatus.SUCCEEDED if not failures else TaskStatus.FAILED
    task.current_node = "finance_payment_sync_complete" if not failures else "finance_payment_sync_incomplete"
    task.progress = 100
    task.heartbeat_at = datetime.now(UTC)
    task.last_error = None if not failures else f"{len(failures)} 个管家/资金类型读取失败"
    update_project_watermark(
        db,
        source="baidu_finance_payments",
        project_id=task.project_id,
        status="succeeded" if not failures else "failed",
        message=f"已写入 {state.get('rows_upserted', 0)} 条付款流水；失败 {len(failures)} 项",
        source_at=datetime.now(UTC) if not failures else None,
    )
    db.add(AuditEvent(
        project_id=task.project_id,
        actor="baidu-finance-worker",
        action="baidu.finance.payment.sync",
        target_type="background_task",
        target_id=str(task.id),
        summary=f"充值对账同步{task.status.value}",
        details={
            "date_from": request_details.get("date_from"),
            "date_to": request_details.get("date_to"),
            "rows_upserted": state.get("rows_upserted", 0),
            "failures": failures,
        },
    ))
    db.commit()
    return {"status": task.status.value, "task_id": str(task.id), **state}


@celery_app.task
def sync_finance_payments(task_id: str):
    """Read one audited payment page at a time so retries resume safely."""
    task_uuid = uuid.UUID(task_id)
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_uuid)
        if task is None or task.project_id is None:
            return {"status": "task_missing"}
        payload = task.result if isinstance(task.result, dict) else {}
        request_details = payload.get("request") if isinstance(payload.get("request"), dict) else {}
        state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
        state.setdefault("manager_index", 0)
        state.setdefault("fund_index", 0)
        state.setdefault("offset_id", 0)
        state.setdefault("rows_upserted", 0)
        state.setdefault("failures", {})
        try:
            start_date = date.fromisoformat(str(request_details["date_from"]))
            end_date = date.fromisoformat(str(request_details["date_to"]))
        except (KeyError, TypeError, ValueError) as exc:
            state["failures"]["request"] = f"日期配置无效：{exc}"
            return _finish_finance_payment_task(db, task, request_details, state)
        managers = db.scalars(select(AccountManager).where(
            AccountManager.project_id == task.project_id,
            AccountManager.is_active.is_(True),
        ).order_by(AccountManager.login_name)).all()
        targets: list[tuple[AccountManager, Account]] = []
        for manager in managers:
            account = resolve_manager_recharge_account(db, manager)
            if account is not None:
                targets.append((manager, account))
        manager_index = int(state["manager_index"])
        fund_index = int(state["fund_index"])
        if manager_index >= len(targets):
            return _finish_finance_payment_task(db, task, request_details, state)
        manager, account = targets[manager_index]
        fund_type = FINANCE_FUND_TYPES[fund_index]
        condition = {
            "paytime": {
                "gte": f"{start_date.isoformat()} 00:00:00",
                "lte": f"{end_date.isoformat()} 23:59:59",
            },
        }
        if fund_type == 23:
            condition["status"] = {"in": [0, 1, 2]}
        api_payload = {
            "fundtype": fund_type,
            "condition": condition,
            "chunkSize": FINANCE_PAYMENT_PAGE_SIZE,
            "offset": {"id": {"gt": int(state["offset_id"])}},
            "sort": {"in": ["id asc"]},
        }
        task.status = TaskStatus.RUNNING
        task.current_node = f"finance_payment:{manager.login_name}:{fund_type}"
        task.progress = min(95, int((manager_index * len(FINANCE_FUND_TYPES) + fund_index) * 100 / max(1, len(targets) * len(FINANCE_FUND_TYPES))))
        task.heartbeat_at = datetime.now(UTC)
        update_project_watermark(
            db,
            source="baidu_finance_payments",
            project_id=task.project_id,
            status="running",
            message=f"正在同步 {manager.display_name or manager.login_name} 的资金类型 {fund_type}",
        )
        db.commit()
        try:
            result = platform_client().execute_read(
                context=call_context(
                    account,
                    batch=f"finance-payment:{task_id}",
                    idempotency_key="",
                ),
                service="payment.records.get",
                payload=api_payload,
            )
            rows = _payment_result_rows(result)
            fetched_at = datetime.now(UTC)
            count, last_id = _upsert_finance_payment_rows(
                db,
                project_id=task.project_id,
                manager=manager,
                account=account,
                fund_type=fund_type,
                rows=rows,
                fetched_at=fetched_at,
            )
            state["rows_upserted"] = int(state["rows_upserted"]) + count
            if len(rows) >= FINANCE_PAYMENT_PAGE_SIZE and last_id > int(state["offset_id"]):
                state["offset_id"] = last_id
            else:
                state["offset_id"] = 0
                state["fund_index"] = fund_index + 1
                if int(state["fund_index"]) >= len(FINANCE_FUND_TYPES):
                    state["fund_index"] = 0
                    state["manager_index"] = manager_index + 1
        except RateLimitError as exc:
            task = db.get(BackgroundTask, task_uuid)
            task.result = {"request": request_details, "state": state}
            flag_modified(task, "result")
            task.heartbeat_at = datetime.now(UTC)
            db.commit()
            sync_finance_payments.apply_async(args=[task_id], countdown=rate_limit_retry_seconds(exc))
            return {"status": "rate_limited", "task_id": task_id}
        except TokenUnavailableError as exc:
            db.rollback()
            task = db.get(BackgroundTask, task_uuid)
            state["failures"][f"{manager.login_name}:{fund_type}"] = str(exc)
            task.status = TaskStatus.BLOCKED
            task.current_node = "authorization_blocked"
            task.last_error = str(exc)[:500]
            task.result = {"request": request_details, "state": state}
            flag_modified(task, "result")
            update_project_watermark(db, source="baidu_finance_payments", project_id=task.project_id, status="blocked", message=task.last_error)
            db.commit()
            return {"status": "blocked", "task_id": task_id, "reason": task.last_error}
        except Exception as exc:
            db.rollback()
            task = db.get(BackgroundTask, task_uuid)
            state["failures"][f"{manager.login_name}:{fund_type}"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            state["offset_id"] = 0
            state["fund_index"] = fund_index + 1
            if int(state["fund_index"]) >= len(FINANCE_FUND_TYPES):
                state["fund_index"] = 0
                state["manager_index"] = manager_index + 1
        task = db.get(BackgroundTask, task_uuid)
        task.result = {"request": request_details, "state": state}
        flag_modified(task, "result")
        task.heartbeat_at = datetime.now(UTC)
        db.commit()
        if int(state["manager_index"]) >= len(targets):
            task = db.get(BackgroundTask, task_uuid)
            return _finish_finance_payment_task(db, task, request_details, state)
    sync_finance_payments.delay(task_id)
    return {"status": "continued", "task_id": task_id, **state}


@celery_app.task
def queue_hourly_data_refresh():
    result = _queue_data_cycle(datetime.now(SHANGHAI).date(), final=False)
    result["creative_review"] = queue_due_creative_review_syncs.run()
    result["budget_snapshot"] = queue_due_budget_snapshot_syncs.run(
        trigger="hourly_refresh"
    )
    return result


@celery_app.task
def dispatch_due_data_cycles():
    """Dispatch each project's closed-loop refresh from its saved interval."""
    local_now = datetime.now(SHANGHAI).replace(second=0, microsecond=0)
    due_projects: list[uuid.UUID] = []
    with SessionLocal() as db:
        projects = db.scalars(select(Project).where(Project.enabled.is_(True))).all()
        setting_rows = db.scalars(select(ProjectPreference).where(
            ProjectPreference.key == "settings",
            ProjectPreference.project_id.in_([project.id for project in projects]),
        )).all() if projects else []
        settings_by_project = {row.project_id: row.value for row in setting_rows}
        for project in projects:
            configured = settings_by_project.get(project.id) or {}
            interval = max(15, min(1440, int(configured.get("report_refresh_minutes") or 60)))
            slot = int(local_now.timestamp() // (interval * 60))
            locked = db.scalar(
                text("select pg_try_advisory_xact_lock(hashtext(:lock_key))"),
                {"lock_key": f"search:data-cycle:{project.id}"},
            )
            if not locked:
                continue
            runtime = db.scalar(select(ProjectPreference).where(
                ProjectPreference.project_id == project.id,
                ProjectPreference.key == "data_cycle_runtime",
            ).with_for_update())
            if runtime is not None and int((runtime.value or {}).get("last_slot") or -1) == slot:
                continue
            runtime_value = {
                "last_slot": slot,
                "interval_minutes": interval,
                "scheduled_at": local_now.astimezone(UTC).isoformat(),
            }
            if runtime is None:
                runtime = ProjectPreference(
                    project_id=project.id,
                    key="data_cycle_runtime",
                    value=runtime_value,
                    updated_by="system",
                )
                db.add(runtime)
            else:
                runtime.value = runtime_value
                runtime.updated_by = "system"
                flag_modified(runtime, "value")
            due_projects.append(project.id)
            db.commit()
    results = []
    for project_id in due_projects:
        results.append(_queue_data_cycle(local_now.date(), final=False, project_ids=[project_id]))
        queue_due_budget_snapshot_syncs.delay("closed_loop_refresh", str(project_id))
    if due_projects:
        queue_due_creative_review_syncs.delay()
    return {
        "status": "dispatched",
        "scheduled_at": local_now.astimezone(UTC).isoformat(),
        "project_count": len(due_projects),
        "projects": [str(project_id) for project_id in due_projects],
        "results": results,
    }


@celery_app.task
def queue_final_daily_archive():
    return _queue_data_cycle(datetime.now(SHANGHAI).date() - timedelta(days=1), final=True)


@celery_app.task
def sync_baidu_reports():
    """Compatibility entry point for an immediate current-hour data cycle."""
    return queue_hourly_data_refresh.run()


@celery_app.task
def reconcile_notifications():
    """Create DB-only task/refund reminders without calling an external API."""
    with SessionLocal() as db:
        result = reconcile_all_projects(db)
        db.commit()
        return {"status": "complete", "projects": result}


def strategy_schedule_slots(local_now: datetime, config: dict) -> bool:
    """Return whether a published strategy is due in this Beijing minute."""
    return local_now.strftime("%H:%M") in set(config.get("schedule_times") or [])


@celery_app.task
def dispatch_due_strategy_schedules():
    local_now = datetime.now(SHANGHAI).replace(second=0, microsecond=0)
    scheduled_for = local_now.astimezone(UTC)
    dispatches: list[tuple[str, str, str, str]] = []
    with SessionLocal() as db:
        projects = db.scalars(select(Project).where(Project.enabled.is_(True))).all()
        for project in projects:
            for key in ("budget_reset", "budget_append", "elimination"):
                version = active_strategy_version(db, project.id, key)
                if not strategy_schedule_slots(local_now, version.config):
                    continue
                statement = (
                    pg_insert(StrategyScheduleRun)
                    .values(
                        id=uuid.uuid4(), project_id=project.id, strategy_key=key,
                        strategy_version_id=version.id, scheduled_for=scheduled_for,
                        status="dispatching",
                    )
                    .on_conflict_do_nothing(
                        index_elements=["project_id", "strategy_key", "scheduled_for"]
                    )
                    .returning(StrategyScheduleRun.id)
                )
                run_id = db.scalar(statement)
                if run_id:
                    dispatches.append((key, str(project.id), str(version.id), str(run_id)))
        db.commit()
    for key, project_id, version_id, run_id in dispatches:
        if key == "budget_reset":
            queue_due_budget_snapshot_syncs.delay("midnight_reset", project_id, version_id, run_id)
        elif key == "budget_append":
            queue_budget_automation.delay("append", project_id, version_id, run_id)
        else:
            queue_account_elimination_cycles.delay(project_id, version_id, run_id)
    return {"status": "dispatched", "scheduled_for": scheduled_for.isoformat(), "count": len(dispatches)}


@celery_app.task
def run_code_sync(task_id: str):
    with SessionLocal() as db:
        task = db.get(BackgroundTask, uuid.UUID(task_id))
        if task is None or task.task_type != "code_sync":
            return {"status": "task_missing"}
        if task.status == TaskStatus.SUCCEEDED:
            return {"status": "already_succeeded", "task_id": task_id}
        return execute_code_sync(db, task, settings)


@celery_app.task
def queue_daily_code_sync():
    if not settings.code_sync_enabled:
        return {"status": "disabled"}
    with SessionLocal() as db:
        active = active_code_sync_task(db)
        if active is not None:
            return {"status": "already_running", "task_id": str(active.id)}
        task = create_code_sync_task(
            db,
            requested_by="system-scheduler",
            trigger="scheduled",
        )
        task_id = str(task.id)
    run_code_sync.delay(task_id)
    return {"status": "queued", "task_id": task_id}


celery_app.conf.beat_schedule = {
    "daily-search-code-sync-0200": {
        "task": "search_console.worker.queue_daily_code_sync",
        "schedule": crontab(minute=0, hour=2),
    },
    "minute-configurable-data-cycle-dispatch": {
        "task": "search_console.worker.dispatch_due_data_cycles",
        "schedule": crontab(minute="*"),
    },
    "final-previous-day-archive-0030": {
        "task": "search_console.worker.queue_final_daily_archive",
        "schedule": crontab(minute=30, hour=0),
    },
    "hourly-analytics-snapshot": {
        "task": "search_console.worker.rebuild_analytics_snapshot",
        "schedule": crontab(minute=10, hour="1-23"),
    },
    "daily-automation-dry-run": {
        "task": "search_console.worker.evaluate_alert_rules",
        "schedule": crontab(minute=15, hour=23),
    },
    "minute-ad-build-dispatch": {
        "task": "search_console.worker.dispatch_due_ad_build_batches",
        "schedule": crontab(minute="*"),
    },
    "minute-campaign-batch-auto-retry-dispatch": {
        "task": "search_console.worker.dispatch_due_campaign_batch_auto_retries",
        "schedule": crontab(minute="*"),
    },
    "minute-notification-reconcile": {
        "task": "search_console.worker.reconcile_notifications",
        "schedule": crontab(minute="*"),
    },
    "minute-background-task-heartbeat-watchdog": {
        "task": "search_console.worker.close_stale_background_tasks",
        "schedule": crontab(minute="*"),
    },
    "minute-strategy-schedule-dispatch": {
        "task": "search_console.worker.dispatch_due_strategy_schedules",
        "schedule": crontab(minute="*"),
    },
}


ACCOUNT_REPORT_BATCH_SIZE = 80


def _account_report_watermark(db, project_id: uuid.UUID, *, status: str, message: str | None = None, source_at: datetime | None = None) -> SyncWatermark:
    watermark = db.scalar(select(SyncWatermark).where(
        SyncWatermark.source == "baidu_account_report",
        SyncWatermark.scope == str(project_id),
    ))
    if watermark is None:
        watermark = SyncWatermark(source="baidu_account_report", scope=str(project_id))
        db.add(watermark)
    watermark.status = status
    watermark.message = message
    watermark.snapshot_at = datetime.now(UTC)
    if source_at is not None:
        watermark.source_at = source_at
    return watermark


def _persist_account_report_state(
    db,
    task: BackgroundTask,
    *,
    request_details: dict,
    state: dict,
    total_accounts: int,
) -> None:
    processed = int(state.get("processed_accounts") or 0)
    task.result = {"request": request_details, "state": state}
    flag_modified(task, "result")
    task.status = TaskStatus.RUNNING
    task.current_node = "fetch_account_daily_reports"
    task.progress = min(95, int(processed * 95 / max(1, total_accounts)))
    task.heartbeat_at = datetime.now(UTC)
    db.commit()


def _block_account_report_task(db, task: BackgroundTask, state: dict, request_details: dict, reason: str) -> dict:
    task.status = TaskStatus.BLOCKED
    task.current_node = "authorization_blocked"
    task.last_error = reason[:500]
    task.result = {"request": request_details, "state": state}
    flag_modified(task, "result")
    task.heartbeat_at = datetime.now(UTC)
    _account_report_watermark(db, task.project_id, status="blocked", message=task.last_error)
    db.commit()
    return {"status": "blocked", "task_id": str(task.id), "reason": task.last_error}


def _run_baidu_account_backfill(task_id: str):
    """Backfill only account-level daily search metrics through the audited platform client."""
    task_uuid = uuid.UUID(task_id)
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_uuid)
        if task is None or task.project_id is None:
            return {"status": "task_missing"}
        task_payload = task.result if isinstance(task.result, dict) else {}
        request_details = task_payload.get("request") if isinstance(task_payload.get("request"), dict) else {}
        if request_details.get("scope") != "account_daily":
            return _block_account_report_task(db, task, {}, request_details, "任务范围不是账户级日报，已拒绝执行")
        try:
            start_date = date.fromisoformat(str(request_details["date_from"]))
            end_date = date.fromisoformat(str(request_details["date_to"]))
            report_payload = build_account_report_payload(start_date, end_date)
        except (KeyError, TypeError, ValueError) as exc:
            return _block_account_report_task(db, task, {}, request_details, f"报表日期配置无效：{exc}")
        if request_details.get("trigger") != "final_archive":
            finalized_date = db.scalar(select(DailyDataStatus.report_date).where(
                DailyDataStatus.project_id == task.project_id,
                DailyDataStatus.report_date.between(start_date, end_date),
                DailyDataStatus.finalized_at.is_not(None),
            ).limit(1))
            if finalized_date is not None:
                return _block_account_report_task(
                    db,
                    task,
                    {},
                    request_details,
                    f"{finalized_date} 已完成最终存档，普通刷新禁止覆盖",
                )

        state = task_payload.get("state") if isinstance(task_payload.get("state"), dict) else {}
        state.setdefault("cursor_account_id", 0)
        state.setdefault("processed_accounts", 0)
        state.setdefault("rows_upserted", 0)
        state.setdefault("empty_accounts", 0)
        state.setdefault("failed_accounts", {})
        state.setdefault("consecutive_errors", 0)
        try:
            account_scope = account_report_conditions(task.project_id, request_details)
        except (KeyError, TypeError, ValueError) as exc:
            return _block_account_report_task(
                db, task, state, request_details, f"账户选择范围无效：{exc}"
            )
        total_accounts = int(
            db.scalar(select(func.count(Account.id)).where(*account_scope)) or 0
        )
        state["total_accounts"] = total_accounts
        _account_report_watermark(db, task.project_id, status="running", message=f"正在补齐 {start_date} 至 {end_date} 账户日报")
        _persist_account_report_state(db, task, request_details=request_details, state=state, total_accounts=total_accounts)

        accounts = db.scalars(
            select(Account)
            .where(
                *account_scope,
                Account.baidu_account_id > int(state["cursor_account_id"]),
            )
            .order_by(Account.baidu_account_id)
            .limit(ACCOUNT_REPORT_BATCH_SIZE)
        ).all()
        client = platform_client()
        for account in accounts:
            try:
                result = client.execute_read(
                    context=call_context(
                        account,
                        batch=f"account-report:{task_id}",
                        idempotency_key="",
                    ),
                    service="report.get",
                    payload=report_payload,
                )
                facts = normalize_account_report_rows(
                    extract_report_rows(result),
                    target_account_id=account.baidu_account_id,
                    target_login_name=account.login_name,
                    start_date=start_date,
                    end_date=end_date,
                )
                state["rows_upserted"] = int(state["rows_upserted"]) + upsert_account_report_facts(db, account, facts)
                if not facts:
                    state["empty_accounts"] = int(state["empty_accounts"]) + 1
                state["consecutive_errors"] = 0
            except RateLimitError as exc:
                _persist_account_report_state(db, task, request_details=request_details, state=state, total_accounts=total_accounts)
                sync_baidu_account_backfill.apply_async(
                    args=[task_id], countdown=rate_limit_retry_seconds(exc)
                )
                return {"status": "rate_limited", "task_id": task_id, "processed": state["processed_accounts"]}
            except TokenUnavailableError as exc:
                db.rollback()
                task = db.get(BackgroundTask, task_uuid)
                return _block_account_report_task(db, task, state, request_details, str(exc))
            except Exception as exc:
                db.rollback()
                task = db.get(BackgroundTask, task_uuid)
                failures = state["failed_accounts"]
                failures[str(account.baidu_account_id)] = {
                    "attempts": int((failures.get(str(account.baidu_account_id)) or {}).get("attempts") or 0) + 1,
                    "error": f"{type(exc).__name__}: {str(exc)[:180]}",
                }
                state["consecutive_errors"] = int(state["consecutive_errors"]) + 1
                if state["consecutive_errors"] >= 3:
                    return _block_account_report_task(
                        db,
                        task,
                        state,
                        request_details,
                        "连续3个账户读取失败，任务已保护性停止；请检查百度报表权限或授权状态",
                    )
            state["processed_accounts"] = int(state["processed_accounts"]) + 1
            state["cursor_account_id"] = account.baidu_account_id
            task = db.get(BackgroundTask, task_uuid)
            _persist_account_report_state(db, task, request_details=request_details, state=state, total_accounts=total_accounts)

        if accounts and int(state["processed_accounts"]) < total_accounts:
            sync_baidu_account_backfill.delay(task_id)
            return {"status": "continued", "task_id": task_id, "processed": state["processed_accounts"], "total": total_accounts}

        task = db.get(BackgroundTask, task_uuid)
        failures = state.get("failed_accounts") or {}
        task.result = {"request": request_details, "state": state}
        flag_modified(task, "result")
        task.heartbeat_at = datetime.now(UTC)
        task.progress = 100
        task.current_node = "account_daily_backfill_complete" if not failures else "account_daily_backfill_incomplete"
        task.status = TaskStatus.SUCCEEDED if not failures else TaskStatus.FAILED
        task.last_error = None if not failures else f"{len(failures)} 个账户读取失败，可在任务中心续跑"
        source_at = datetime.combine(end_date, time.min, tzinfo=UTC)
        _account_report_watermark(
            db,
            task.project_id,
            status="succeeded" if not failures else "failed",
            message=f"已写入 {state['rows_upserted']} 条账户日报；失败账户 {len(failures)} 个",
            source_at=source_at if not failures else None,
        )
        if not failures and start_date == end_date:
            mark_daily_source_complete(db, task.project_id, end_date, "baidu")
        db.add(AuditEvent(
            project_id=task.project_id,
            actor="baidu-report-worker",
            action="baidu.account_report.backfill",
            target_type="background_task",
            target_id=task_id,
            summary=f"账户日报补齐{task.status.value}",
            details={
                "date_from": start_date.isoformat(),
                "date_to": end_date.isoformat(),
                "processed_accounts": state["processed_accounts"],
                "rows_upserted": state["rows_upserted"],
                "failed_accounts": len(failures),
                "scope": "account_daily",
            },
        ))
        db.commit()
        return {"status": task.status.value, "task_id": task_id, **state}


@celery_app.task
def sync_baidu_account_backfill(task_id: str):
    """Ensure only one process advances a backfill task cursor at a time."""
    task_uuid = uuid.UUID(task_id)
    lock_key = task_uuid.int & 0x7FFFFFFFFFFFFFFF
    with engine.connect() as lock_connection:
        acquired = bool(lock_connection.execute(
            text("SELECT pg_try_advisory_lock(:lock_key)"),
            {"lock_key": lock_key},
        ).scalar_one())
        if not acquired:
            return {"status": "duplicate_ignored", "task_id": task_id}
        try:
            return _run_baidu_account_backfill(task_id)
        finally:
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(:lock_key)"),
                {"lock_key": lock_key},
            )


KEYWORD_REPORT_BATCH_SIZE = 40


def _keyword_report_watermark(
    db,
    project_id: uuid.UUID,
    *,
    status: str,
    message: str | None = None,
    source_at: datetime | None = None,
) -> SyncWatermark:
    watermark = db.scalar(select(SyncWatermark).where(
        SyncWatermark.source == "baidu_keyword_report",
        SyncWatermark.scope == str(project_id),
    ))
    if watermark is None:
        watermark = SyncWatermark(source="baidu_keyword_report", scope=str(project_id))
        db.add(watermark)
    watermark.status = status
    watermark.message = message
    watermark.snapshot_at = datetime.now(UTC)
    if source_at is not None:
        watermark.source_at = source_at
    return watermark


def _persist_keyword_report_state(
    db,
    task: BackgroundTask,
    *,
    request_details: dict,
    state: dict,
    total_accounts: int,
) -> None:
    processed = int(state.get("processed_accounts") or 0)
    task.result = {"request": request_details, "state": state}
    flag_modified(task, "result")
    task.status = TaskStatus.RUNNING
    task.current_node = "fetch_second_hop_keyword_daily_reports"
    task.progress = min(95, int(processed * 95 / max(1, total_accounts)))
    task.heartbeat_at = datetime.now(UTC)
    db.commit()


def _block_keyword_report_task(
    db,
    task: BackgroundTask,
    state: dict,
    request_details: dict,
    reason: str,
) -> dict:
    task.status = TaskStatus.BLOCKED
    task.current_node = "keyword_report_blocked"
    task.last_error = reason[:500]
    task.result = {"request": request_details, "state": state}
    flag_modified(task, "result")
    task.heartbeat_at = datetime.now(UTC)
    _keyword_report_watermark(db, task.project_id, status="blocked", message=task.last_error)
    db.commit()
    return {"status": "blocked", "task_id": str(task.id), "reason": task.last_error}


def _run_baidu_keyword_backfill(task_id: str):
    """Backfill material-matched keyword facts for active second-hop accounts only."""
    task_uuid = uuid.UUID(task_id)
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_uuid)
        if task is None or task.project_id is None:
            return {"status": "task_missing"}
        task_payload = task.result if isinstance(task.result, dict) else {}
        request_details = task_payload.get("request") if isinstance(task_payload.get("request"), dict) else {}
        if request_details.get("scope") != KEYWORD_REPORT_SCOPE:
            return _block_keyword_report_task(db, task, {}, request_details, "任务范围不是二跳账户物料关键词日报，已拒绝执行")
        try:
            start_date = date.fromisoformat(str(request_details["date_from"]))
            end_date = date.fromisoformat(str(request_details["date_to"]))
            build_keyword_report_payload(start_date, end_date)
        except (KeyError, TypeError, ValueError) as exc:
            return _block_keyword_report_task(db, task, {}, request_details, f"关键词报表日期配置无效：{exc}")

        state = task_payload.get("state") if isinstance(task_payload.get("state"), dict) else {}
        state.setdefault("cursor_account_id", 0)
        state.setdefault("processed_accounts", 0)
        state.setdefault("empty_accounts", 0)
        state.setdefault("report_pages", 0)
        state.setdefault("rows_seen", 0)
        state.setdefault("rows_matched", 0)
        state.setdefault("rows_unmatched", 0)
        state.setdefault("rows_non_keyword", 0)
        state.setdefault("deleted_marker_rows", 0)
        state.setdefault("rows_upserted", 0)
        state.setdefault("unmatched_keyword_samples", [])
        state.setdefault("failed_accounts", {})
        state.setdefault("consecutive_errors", 0)
        try:
            account_scope = keyword_report_conditions(task.project_id, request_details)
        except (KeyError, TypeError, ValueError) as exc:
            return _block_keyword_report_task(
                db,
                task,
                state,
                request_details,
                f"关键词账户范围无效：{exc}",
            )
        total_accounts = int(db.scalar(select(func.count(Account.id)).where(*account_scope)) or 0)
        state["total_accounts"] = total_accounts
        _keyword_report_watermark(
            db,
            task.project_id,
            status="running",
            message=f"正在补齐 {start_date} 至 {end_date} 二跳账户关键词日报",
        )
        _persist_keyword_report_state(
            db,
            task,
            request_details=request_details,
            state=state,
            total_accounts=total_accounts,
        )

        accounts = db.scalars(
            select(Account)
            .where(*account_scope, Account.baidu_account_id > int(state["cursor_account_id"]))
            .order_by(Account.baidu_account_id)
            .limit(KEYWORD_REPORT_BATCH_SIZE)
        ).all()
        client = platform_client()
        for account in accounts:
            account_totals = {
                "report_pages": 0,
                "rows_seen": 0,
                "rows_matched": 0,
                "rows_unmatched": 0,
                "rows_non_keyword": 0,
                "deleted_marker_rows": 0,
                "rows_upserted": 0,
            }
            account_unmatched: set[str] = set()
            try:
                db.execute(
                    delete(UnmatchedKeywordPerformanceDaily).where(
                        UnmatchedKeywordPerformanceDaily.account_id == account.id,
                        UnmatchedKeywordPerformanceDaily.report_date >= start_date,
                        UnmatchedKeywordPerformanceDaily.report_date <= end_date,
                    )
                )
                start_row = 0
                while True:
                    report_payload = build_keyword_report_payload(
                        start_date,
                        end_date,
                        start_row=start_row,
                    )
                    result = client.execute_read(
                        context=call_context(
                            account,
                            batch=f"keyword-report:{task_id}",
                            idempotency_key="",
                        ),
                        service="report.get",
                        payload=report_payload,
                    )
                    rows = extract_report_rows(result)
                    total_row_count = extract_report_total_row_count(result)
                    written = upsert_matched_keyword_report_facts(
                        db,
                        account,
                        rows,
                        start_date=start_date,
                        end_date=end_date,
                        write_matched=not bool(
                            request_details.get("capture_unmatched_only")
                        ),
                    )
                    account_totals["report_pages"] += 1
                    account_totals["rows_seen"] += written.rows_seen
                    account_totals["rows_matched"] += written.rows_matched
                    account_totals["rows_unmatched"] += written.rows_unmatched
                    account_totals["rows_non_keyword"] += written.rows_non_keyword
                    account_totals["deleted_marker_rows"] += written.deleted_marker_rows
                    account_totals["rows_upserted"] += written.rows_upserted
                    account_unmatched.update(written.unmatched_keywords)
                    next_row = start_row + len(rows)
                    if not rows or len(rows) < KEYWORD_REPORT_PAGE_SIZE:
                        break
                    if total_row_count is not None and next_row >= total_row_count:
                        break
                    if next_row <= start_row:
                        raise RuntimeError("百度关键词报告分页游标未前进")
                    start_row = next_row

                for key, value in account_totals.items():
                    state[key] = int(state[key]) + value
                if account_totals["rows_seen"] == 0:
                    state["empty_accounts"] = int(state["empty_accounts"]) + 1
                samples = list(state.get("unmatched_keyword_samples") or [])
                for keyword in sorted(account_unmatched):
                    if len(samples) >= 200:
                        break
                    if keyword not in samples:
                        samples.append(keyword)
                state["unmatched_keyword_samples"] = samples
                state["consecutive_errors"] = 0
            except RateLimitError as exc:
                db.rollback()
                task = db.get(BackgroundTask, task_uuid)
                _persist_keyword_report_state(
                    db,
                    task,
                    request_details=request_details,
                    state=state,
                    total_accounts=total_accounts,
                )
                sync_baidu_keyword_backfill.apply_async(
                    args=[task_id], countdown=rate_limit_retry_seconds(exc)
                )
                return {"status": "rate_limited", "task_id": task_id, "processed": state["processed_accounts"]}
            except TokenUnavailableError as exc:
                db.rollback()
                task = db.get(BackgroundTask, task_uuid)
                return _block_keyword_report_task(db, task, state, request_details, str(exc))
            except Exception as exc:
                db.rollback()
                task = db.get(BackgroundTask, task_uuid)
                failures = state["failed_accounts"]
                failures[str(account.baidu_account_id)] = {
                    "attempts": int((failures.get(str(account.baidu_account_id)) or {}).get("attempts") or 0) + 1,
                    "error": f"{type(exc).__name__}: {str(exc)[:180]}",
                }
                state["consecutive_errors"] = int(state["consecutive_errors"]) + 1
                if state["consecutive_errors"] >= 3:
                    return _block_keyword_report_task(
                        db,
                        task,
                        state,
                        request_details,
                        "连续3个二跳账户读取失败，任务已保护性停止；请检查关键词报告权限或授权状态",
                    )
            state["processed_accounts"] = int(state["processed_accounts"]) + 1
            state["cursor_account_id"] = account.baidu_account_id
            task = db.get(BackgroundTask, task_uuid)
            _persist_keyword_report_state(
                db,
                task,
                request_details=request_details,
                state=state,
                total_accounts=total_accounts,
            )

        if accounts and int(state["processed_accounts"]) < total_accounts:
            sync_baidu_keyword_backfill.delay(task_id)
            return {
                "status": "continued",
                "task_id": task_id,
                "processed": state["processed_accounts"],
                "total": total_accounts,
            }

        task = db.get(BackgroundTask, task_uuid)
        failures = state.get("failed_accounts") or {}
        task.result = {"request": request_details, "state": state}
        flag_modified(task, "result")
        task.heartbeat_at = datetime.now(UTC)
        task.progress = 100
        task.current_node = "keyword_daily_backfill_complete" if not failures else "keyword_daily_backfill_incomplete"
        task.status = TaskStatus.SUCCEEDED if not failures else TaskStatus.FAILED
        task.last_error = None if not failures else f"{len(failures)} 个二跳账户读取失败，可在任务中心续跑"
        source_at = datetime.combine(end_date, time.min, tzinfo=UTC)
        _keyword_report_watermark(
            db,
            task.project_id,
            status="succeeded" if not failures else "failed",
            message=(
                f"精确匹配并写入 {state['rows_upserted']} 条关键词日报；"
                f"未匹配 {state['rows_unmatched']} 条；失败账户 {len(failures)} 个"
            ),
            source_at=source_at if not failures else None,
        )
        if (
            not failures
            and start_date == end_date
            and request_details.get("trigger") == "final_archive"
        ):
            mark_daily_source_complete(db, task.project_id, end_date, "keyword")
        db.add(AuditEvent(
            project_id=task.project_id,
            actor="baidu-report-worker",
            action="baidu.keyword_report.backfill",
            target_type="background_task",
            target_id=task_id,
            summary=f"二跳账户关键词日报补齐{task.status.value}",
            details={
                "date_from": start_date.isoformat(),
                "date_to": end_date.isoformat(),
                "processed_accounts": state["processed_accounts"],
                "rows_seen": state["rows_seen"],
                "rows_upserted": state["rows_upserted"],
                "rows_unmatched": state["rows_unmatched"],
                "deleted_marker_rows": state["deleted_marker_rows"],
                "failed_accounts": len(failures),
                "account_type": AccountType.SECOND_HOP.value,
                "match_mode": "exact_after_deleted_marker_removal",
            },
        ))
        db.commit()
        return {"status": task.status.value, "task_id": task_id, **state}


@celery_app.task
def sync_baidu_keyword_backfill(task_id: str):
    """Ensure only one process advances a keyword backfill cursor at a time."""
    task_uuid = uuid.UUID(task_id)
    lock_key = task_uuid.int & 0x7FFFFFFFFFFFFFFF
    with engine.connect() as lock_connection:
        acquired = bool(lock_connection.execute(
            text("SELECT pg_try_advisory_lock(:lock_key)"),
            {"lock_key": lock_key},
        ).scalar_one())
        if not acquired:
            return {"status": "duplicate_ignored", "task_id": task_id}
        try:
            return _run_baidu_keyword_backfill(task_id)
        finally:
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(:lock_key)"),
                {"lock_key": lock_key},
            )


@celery_app.task
def capture_hduofen():
    if not settings.hduofen_capture_enabled:
        return {"status": "disabled"}
    from .tracking import capture_tracking_pages
    with SessionLocal() as db:
        preferences = db.scalars(
            select(ProjectPreference).where(ProjectPreference.key == "tracking")
        ).all()
        project_ids = [
            str(row.project_id)
            for row in preferences
            if isinstance(row.value, dict) and row.value.get("enabled") is True
        ]
    if not project_ids:
        return {"status": "scheduled_disabled"}
    project_results = []
    for project_id in project_ids:
        result = capture_tracking_pages(settings, project_id=project_id)
        if result.get("status") == "captured":
            from .tracking_ingestion import ingest_hduofen_capture

            with SessionLocal() as db:
                result["ingestion"] = ingest_hduofen_capture(
                    db,
                    uuid.UUID(project_id),
                    None,
                    result.get("captures") or [],
                )
                result["committed_to_facts"] = True
                db.commit()
        project_results.append({"project_id": project_id, "result": result})
    return {"status": "captured", "projects": project_results}


@celery_app.task
def capture_hduofen_for_task(
    task_id: str,
    project_id: str,
    date_from: str,
    date_to: str,
):
    task_uuid = uuid.UUID(task_id)
    project_uuid = uuid.UUID(project_id)
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_uuid)
        if task is None or task.project_id != project_uuid:
            return {"status": "task_missing"}
        task_payload = task.result if isinstance(task.result, dict) else {}
        stored_request = (
            task_payload.get("request")
            if isinstance(task_payload.get("request"), dict)
            else {}
        )
        request_details = {
            **stored_request,
            "date_from": date_from,
            "date_to": date_to,
        }
        allowed_account_ids: set[uuid.UUID] | None = None
        if isinstance(request_details.get("allowed_account_ids"), list):
            allowed_account_ids = set()
            for value in request_details["allowed_account_ids"]:
                try:
                    allowed_account_ids.add(uuid.UUID(str(value)))
                except (TypeError, ValueError):
                    continue
        if not settings.hduofen_capture_enabled:
            task.status = TaskStatus.BLOCKED
            task.current_node = "runtime_disabled"
            task.last_error = "好多粉运行时采集总开关未开启"
            task.result = {"request": request_details}
            task.heartbeat_at = datetime.now(UTC)
            update_project_watermark(
                db,
                source="hduofen_capture",
                project_id=project_uuid,
                status="blocked",
                message=task.last_error,
            )
            db.commit()
            return {"status": "blocked", "reason": "runtime_disabled"}

        if request_details.get("trigger") != "final_archive":
            parsed_from = date.fromisoformat(date_from)
            parsed_to = date.fromisoformat(date_to)
            finalized_date = db.scalar(select(DailyDataStatus.report_date).where(
                DailyDataStatus.project_id == project_uuid,
                DailyDataStatus.report_date.between(parsed_from, parsed_to),
                DailyDataStatus.finalized_at.is_not(None),
            ).limit(1))
            if finalized_date is not None:
                task.status = TaskStatus.BLOCKED
                task.current_node = "final_archive_protected"
                task.last_error = f"{finalized_date} 已完成最终存档，普通采集禁止覆盖"
                task.result = {"request": request_details}
                task.heartbeat_at = datetime.now(UTC)
                db.commit()
                return {"status": "blocked", "reason": "final_archive_protected"}

        checkpoint(db, task, "login_and_capture", 10)
        try:
            from .tracking import capture_tracking_pages

            result = capture_tracking_pages(
                settings,
                date_from=date.fromisoformat(date_from),
                date_to=date.fromisoformat(date_to),
                project_id=project_id,
            )
            if result.get("status") == "captured":
                checkpoint(db, task, "attribute_and_aggregate", 80)
                from .tracking_ingestion import ingest_hduofen_capture

                result["ingestion"] = ingest_hduofen_capture(
                    db,
                    project_uuid,
                    task_uuid,
                    result.get("captures") or [],
                    allowed_account_ids=allowed_account_ids,
                )
                result["committed_to_facts"] = True
        except Exception as exc:  # Worker must persist a recoverable task state.
            db.rollback()
            task = db.get(BackgroundTask, task_uuid)
            if task is None:
                return {"status": "task_missing"}
            task.status = TaskStatus.FAILED
            task.current_node = "capture_failed"
            task.last_error = f"好多粉采集失败：{type(exc).__name__}"
            task.result = {"request": request_details}
            task.heartbeat_at = datetime.now(UTC)
            update_project_watermark(
                db,
                source="hduofen_capture",
                project_id=project_uuid,
                status="failed",
                message=task.last_error,
            )
            db.commit()
            return {"status": "failed", "error_type": type(exc).__name__}

        task.result = {"request": request_details, "capture": result}
        task.heartbeat_at = datetime.now(UTC)
        if result.get("status") == "captured":
            task.status = TaskStatus.SUCCEEDED
            task.current_node = "capture_complete"
            task.progress = 100
            task.last_error = None
            parsed_from = date.fromisoformat(date_from)
            parsed_to = date.fromisoformat(date_to)
            if parsed_from == parsed_to:
                mark_daily_source_complete(db, project_uuid, parsed_to, "hduofen")
        elif result.get("status") == "blocked":
            task.status = TaskStatus.BLOCKED
            task.current_node = str(result.get("reason") or "capture_blocked")
            task.last_error = "好多粉登录或安全检查阻止了采集"
        else:
            task.status = TaskStatus.FAILED
            task.current_node = "incomplete_dataset"
            task.last_error = "好多粉返回的数据不完整，未写入正式事实表"
        completed_at = datetime.now(UTC)
        update_project_watermark(
            db,
            source="hduofen_capture",
            project_id=project_uuid,
            status=(
                "succeeded"
                if task.status == TaskStatus.SUCCEEDED
                else task.status.value
            ),
            message=task.last_error,
            source_at=(
                completed_at if task.status == TaskStatus.SUCCEEDED else None
            ),
        )
        db.add(AuditEvent(
            project_id=project_uuid,
            actor="tracking-worker",
            action="hduofen.capture.complete",
            target_type="background_task",
            target_id=task_id,
            summary=f"好多粉日期采集{task.status.value}",
            details={
                **request_details,
                "status": task.status.value,
                "ingestion": result.get("ingestion") or {},
            },
        ))
        db.commit()
        return {"status": task.status.value, "task_id": task_id}


ELIMINATION_TASK_TYPE = "account_elimination_cycle"
ELIMINATION_ACCOUNT_BATCH_SIZE = 20


def _effective_lifecycle(account: Account) -> str | None:
    return account.lifecycle_override or account.lifecycle_stage


def _elimination_candidates(db, project_id: uuid.UUID, config: dict | None = None) -> list[dict]:
    config = config or {}
    spend_limit = Decimal(str(config.get("spend_without_add_limit", "100")))
    add_cost_limit = Decimal(str(config.get("add_cost_limit", "120")))
    rows = db.execute(
        select(
            Account.id,
            Account.baidu_account_id,
            func.coalesce(func.sum(PerformanceDaily.spend), 0),
            func.coalesce(func.sum(PerformanceDaily.adds), 0),
        )
        .outerjoin(PerformanceDaily, PerformanceDaily.account_id == Account.id)
        .where(
            Account.project_id == project_id,
            Account.is_active.is_(True),
            api_eligible_account_condition(),
            effective_testing_condition(),
        )
        .group_by(Account.id, Account.baidu_account_id)
        .order_by(Account.baidu_account_id)
    ).all()
    candidates = []
    for account_id, baidu_account_id, spend, adds in rows:
        spend_value = Decimal(spend or 0)
        adds_value = int(adds or 0)
        reason = elimination_reason(
            spend_value,
            adds_value,
            spend_without_add_limit=spend_limit,
            add_cost_limit=add_cost_limit,
        )
        if reason:
            candidates.append({
                "account_id": str(account_id),
                "baidu_account_id": int(baidu_account_id),
                "spend": str(spend_value.quantize(Decimal("0.01"))),
                "adds": adds_value,
                "reason": reason,
            })
    return candidates


def _refresh_is_closed(db, project_id: uuid.UUID, target_date: date) -> tuple[bool, str]:
    status = db.scalar(select(DailyDataStatus).where(
        DailyDataStatus.project_id == project_id,
        DailyDataStatus.report_date == target_date,
    ))
    if status is None:
        return False, "当天双数据源状态不存在"
    cutoff = datetime.combine(target_date, time(hour=23), tzinfo=SHANGHAI).astimezone(UTC)
    if status.baidu_completed_at is None or status.baidu_completed_at < cutoff:
        return False, "23:00百度账户日报尚未完成"
    if status.hduofen_completed_at is None or status.hduofen_completed_at < cutoff:
        return False, "23:00好多粉采集尚未完成"
    return True, "双数据源已闭合"


def _persist_elimination_task(db, task: BackgroundTask, state: dict) -> None:
    task.result = {**(task.result if isinstance(task.result, dict) else {}), "state": state}
    flag_modified(task, "result")
    task.heartbeat_at = datetime.now(UTC)
    db.commit()


def _promote_refund_due_after_elimination(
    db,
    account: Account,
    task: BackgroundTask,
) -> list[Account]:
    """Promote one subject only after an account elimination event.

    Manual lifecycle overrides deliberately block automatic promotion.  This
    preserves manual ``退户`` decisions and prevents an observation or a list
    query from silently changing lifecycle state.
    """
    subject = (account.account_subject or "").strip()
    if not subject:
        return []
    normalized_subject = subject.casefold()
    subject_accounts = [
        row
        for row in db.scalars(select(Account).where(
            Account.project_id == account.project_id,
        )).all()
        if (row.account_subject or "").strip().casefold() == normalized_subject
    ]
    stages = [
        row.lifecycle_stage if row.lifecycle_override is None else None
        for row in subject_accounts
    ]
    if not subject_accounts_are_all_eliminated(stages):
        return []

    evaluated_at = datetime.now(UTC)
    for row in subject_accounts:
        row.lifecycle_stage = REFUND_DUE
        row.lifecycle_evaluated_at = evaluated_at
    db.flush()
    db.add(AuditEvent(
        project_id=account.project_id,
        actor="account-elimination-worker",
        action="account.subject.refund_due",
        target_type="account_subject",
        target_id=subject,
        summary="同一账号主体下账户均已淘汰，进入应退款生命周期",
        details={
            "account_subject": subject,
            "account_ids": [row.baidu_account_id for row in subject_accounts],
            "trigger_account_id": account.baidu_account_id,
            "task_id": str(task.id),
        },
    ))
    create_refund_notifications(db, account.project_id)
    return subject_accounts


def _finish_elimination_task(db, task: BackgroundTask, state: dict) -> dict:
    failures = state.get("failed_accounts") or {}
    task.status = TaskStatus.SUCCEEDED if not failures else TaskStatus.FAILED
    task.current_node = "elimination_complete" if not failures else "elimination_incomplete"
    task.progress = 100
    task.last_error = None if not failures else f"{len(failures)} 个账户淘汰失败"
    task.result = {**(task.result if isinstance(task.result, dict) else {}), "state": state}
    flag_modified(task, "result")
    task.heartbeat_at = datetime.now(UTC)
    db.add(AuditEvent(
        project_id=task.project_id,
        actor="account-elimination-worker",
        action="account.elimination.cycle.complete",
        target_type="background_task",
        target_id=str(task.id),
        summary=f"23:20账户淘汰闭环{task.status.value}",
        details={
            "candidate_count": len(state.get("candidates") or []),
            "eliminated_count": int(state.get("eliminated_count") or 0),
            "deleted_campaign_count": int(state.get("deleted_campaign_count") or 0),
            "refund_due_subject_count": int(state.get("refund_due_subject_count") or 0),
            "failed_account_count": len(failures),
        },
    ))
    db.commit()
    return {"status": task.status.value, "task_id": str(task.id), **state}


def _run_account_elimination_cycle(task_id: str) -> dict:
    task_uuid = uuid.UUID(task_id)
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_uuid)
        if task is None or task.project_id is None:
            return {"status": "task_missing"}
        payload = task.result if isinstance(task.result, dict) else {}
        request_details = payload.get("request") if isinstance(payload.get("request"), dict) else {}
        try:
            target_date = date.fromisoformat(str(request_details["date"]))
        except (KeyError, TypeError, ValueError):
            task.status = TaskStatus.BLOCKED
            task.current_node = "invalid_request"
            task.last_error = "淘汰任务日期无效"
            db.commit()
            return {"status": "blocked", "reason": task.last_error}

        state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
        if not isinstance(state.get("candidates"), list):
            strategy_version = db.get(StrategyVersion, task.strategy_version_id) if task.strategy_version_id else None
            strategy_config = strategy_version.config if strategy_version else {}
            state["candidates"] = _elimination_candidates(db, task.project_id, strategy_config)
            state["cursor"] = 0
            state["eliminated_count"] = 0
            state["deleted_campaign_count"] = 0
            state["refund_due_subject_count"] = 0
            state["failed_accounts"] = {}
        candidates = state["candidates"]
        if not candidates:
            task.status = TaskStatus.SUCCEEDED
            task.current_node = "no_matching_accounts"
            task.progress = 100
            _persist_elimination_task(db, task, state)
            return {"status": "succeeded", "task_id": task_id, "candidate_count": 0}
        if not settings.account_auto_elimination_enabled:
            task.status = TaskStatus.BLOCKED
            task.current_node = "automation_write_disabled"
            task.last_error = "账户自动淘汰专用写开关未开启"
            _persist_elimination_task(db, task, state)
            return {"status": "blocked", "reason": task.last_error}

        refresh_ready, refresh_message = _refresh_is_closed(db, task.project_id, target_date)
        if not refresh_ready:
            task.retry_count += 1
            task.current_node = "waiting_for_2300_data"
            task.last_error = refresh_message
            if task.retry_count > 3:
                task.status = TaskStatus.BLOCKED
                _persist_elimination_task(db, task, state)
                db.add(AuditEvent(
                    project_id=task.project_id,
                    actor="account-elimination-worker",
                    action="account.elimination.protected",
                    target_type="background_task",
                    target_id=task_id,
                    summary="数据水位未闭合，保护性停止账户淘汰",
                    details={"reason": refresh_message, "date": target_date.isoformat()},
                ))
                db.commit()
                return {"status": "blocked", "reason": refresh_message}
            task.status = TaskStatus.PENDING
            _persist_elimination_task(db, task, state)
            run_account_elimination_cycle.apply_async(args=[task_id], countdown=600)
            return {"status": "waiting", "reason": refresh_message, "retry": task.retry_count}

        task.status = TaskStatus.RUNNING
        task.current_node = "delete_account_campaigns"
        task.last_error = None
        client = platform_client(write_enabled=settings.account_auto_elimination_enabled)
        start_index = int(state.get("cursor") or 0)
        stop_index = min(len(candidates), start_index + ELIMINATION_ACCOUNT_BATCH_SIZE)
        for index in range(start_index, stop_index):
            candidate = candidates[index]
            account = db.get(Account, uuid.UUID(candidate["account_id"]))
            if account is None or _effective_lifecycle(account) != TESTING or (
                account.eliminated_at is not None or account.lifecycle_stage == ELIMINATED
            ):
                state["cursor"] = index + 1
                continue
            spend, adds = db.execute(
                select(
                    func.coalesce(func.sum(PerformanceDaily.spend), 0),
                    func.coalesce(func.sum(PerformanceDaily.adds), 0),
                ).where(PerformanceDaily.account_id == account.id)
            ).one()
            current_reason = elimination_reason(Decimal(spend or 0), int(adds or 0))
            if current_reason is None:
                state["cursor"] = index + 1
                continue
            try:
                context = call_context(
                    account,
                    batch=f"account-elimination:{task_id}",
                    idempotency_key="",
                )
                campaign_payload = {
                    "campaignFields": ["campaignId", "campaignName", "status"],
                    "campaignIds": [],
                }
                campaign_rows = baidu_result_rows(
                    client.execute_read(context, "campaign.get", campaign_payload)
                )
                campaign_ids = sorted({
                    int(row["campaignId"])
                    for row in campaign_rows
                    if row.get("campaignId") is not None
                })
                for batch_number, campaign_batch in enumerate(chunks(campaign_ids, 100), start=1):
                    fingerprint = hashlib.sha256(
                        ",".join(str(item) for item in campaign_batch).encode("ascii")
                    ).hexdigest()[:16]
                    client.execute_write(
                        context=call_context(
                            account,
                            batch=f"account-elimination:{task_id}",
                            idempotency_key=(
                                f"account-elimination:{target_date}:{account.baidu_account_id}:"
                                f"{batch_number}:{fingerprint}"
                            ),
                        ),
                        service="campaign.delete",
                        payload={"campaignIds": campaign_batch},
                    )
                remaining = baidu_result_rows(
                    client.execute_read(context, "campaign.get", campaign_payload)
                )
                if remaining:
                    raise RuntimeError("删除后仍回读到推广计划，拒绝更新账户生命周期")

                _store_campaign_cache_rows(db, account, [], full_sync=True)
                account.lifecycle_stage = ELIMINATED
                account.lifecycle_override = None
                account.active_keyword_count = 0
                account.lifecycle_evaluated_at = datetime.now(UTC)
                account.eliminated_at = datetime.now(UTC)
                account.elimination_reason = current_reason
                account.elimination_task_id = task.id
                state["eliminated_count"] = int(state["eliminated_count"]) + 1
                state["deleted_campaign_count"] = (
                    int(state["deleted_campaign_count"]) + len(campaign_ids)
                )
                db.add(AuditEvent(
                    project_id=task.project_id,
                    actor="account-elimination-worker",
                    action="account.campaigns.deleted_and_eliminated",
                    target_type="account",
                    target_id=str(account.baidu_account_id),
                    summary="删除账户全部计划并进入已淘汰生命周期",
                    details={
                        "reason": current_reason,
                        "spend": str(Decimal(spend or 0).quantize(Decimal("0.01"))),
                        "adds": int(adds or 0),
                        "deleted_campaign_count": len(campaign_ids),
                        "readback_remaining": 0,
                        "task_id": task_id,
                    },
                ))
                promoted_accounts = _promote_refund_due_after_elimination(db, account, task)
                if promoted_accounts:
                    state["refund_due_subject_count"] = (
                        int(state.get("refund_due_subject_count") or 0) + 1
                    )
                state["cursor"] = index + 1
                _persist_elimination_task(db, task, state)
            except RateLimitError as exc:
                db.rollback()
                task = db.get(BackgroundTask, task_uuid)
                task.status = TaskStatus.PENDING
                task.current_node = "rate_limited"
                task.last_error = "百度接口限频，稍后从当前账户续跑"
                _persist_elimination_task(db, task, state)
                run_account_elimination_cycle.apply_async(
                    args=[task_id], countdown=rate_limit_retry_seconds(exc)
                )
                return {"status": "rate_limited", "task_id": task_id, "cursor": state["cursor"]}
            except TokenUnavailableError as exc:
                db.rollback()
                task = db.get(BackgroundTask, task_uuid)
                task.status = TaskStatus.BLOCKED
                task.current_node = "authorization_blocked"
                task.last_error = str(exc)[:500]
                _persist_elimination_task(db, task, state)
                return {"status": "blocked", "reason": task.last_error}
            except Exception as exc:
                db.rollback()
                task = db.get(BackgroundTask, task_uuid)
                failures = state["failed_accounts"]
                failures[str(candidate["baidu_account_id"])] = (
                    f"{type(exc).__name__}: {str(exc)[:180]}"
                )
                state["cursor"] = index + 1
                _persist_elimination_task(db, task, state)

        task = db.get(BackgroundTask, task_uuid)
        if int(state.get("cursor") or 0) < len(candidates):
            task.status = TaskStatus.PENDING
            task.current_node = "next_account_batch"
            task.progress = min(95, int(int(state["cursor"]) * 100 / len(candidates)))
            _persist_elimination_task(db, task, state)
            run_account_elimination_cycle.delay(task_id)
            return {"status": "continued", "task_id": task_id, "cursor": state["cursor"]}
        return _finish_elimination_task(db, task, state)


@celery_app.task
def run_account_elimination_cycle(task_id: str):
    task_uuid = uuid.UUID(task_id)
    lock_key = task_uuid.int & 0x7FFFFFFFFFFFFFFF
    with engine.connect() as lock_connection:
        acquired = bool(lock_connection.execute(
            text("SELECT pg_try_advisory_lock(:lock_key)"), {"lock_key": lock_key}
        ).scalar_one())
        if not acquired:
            return {"status": "duplicate_ignored", "task_id": task_id}
        try:
            return _run_account_elimination_cycle(task_id)
        finally:
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(:lock_key)"), {"lock_key": lock_key}
            )


@celery_app.task
def queue_account_elimination_cycles(
    project_id: str | None = None,
    strategy_version_id: str | None = None,
    schedule_run_id: str | None = None,
):
    target_date = datetime.now(SHANGHAI).date()
    queued: list[str] = []
    with SessionLocal() as db:
        project_query = select(Project).where(Project.enabled.is_(True))
        if project_id:
            project_query = project_query.where(Project.id == uuid.UUID(project_id))
        for project in db.scalars(project_query).all():
            running = db.scalar(select(BackgroundTask.id).where(
                BackgroundTask.project_id == project.id,
                BackgroundTask.task_type == ELIMINATION_TASK_TYPE,
                BackgroundTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
            ).limit(1))
            if running is not None:
                continue
            version = (
                db.get(StrategyVersion, uuid.UUID(strategy_version_id))
                if strategy_version_id else active_strategy_version(db, project.id, "elimination")
            )
            version_is_valid = version and db.scalar(select(StrategyPolicy.id).where(
                StrategyPolicy.id == version.policy_id,
                StrategyPolicy.project_id == project.id,
                StrategyPolicy.strategy_key == "elimination",
            )) is not None
            if not version_is_valid:
                continue
            task = BackgroundTask(
                project_id=project.id,
                strategy_version_id=version.id,
                task_type=ELIMINATION_TASK_TYPE,
                current_node="queued_safety_check",
                result={
                    "request": {
                        "date": target_date.isoformat(),
                        "rules": {
                            "spend_without_add": f">{version.config['spend_without_add_limit']}",
                            "add_cost": f">{version.config['add_cost_limit']}",
                        },
                    },
                    "state": {},
                },
            )
            db.add(task)
            db.flush()
            if schedule_run_id:
                schedule_run = db.get(StrategyScheduleRun, uuid.UUID(schedule_run_id))
                if schedule_run and schedule_run.project_id == project.id:
                    schedule_run.task_id = task.id
                    schedule_run.status = "queued"
            queued.append(str(task.id))
        db.commit()
    for task_id in queued:
        run_account_elimination_cycle.delay(task_id)
    return {"status": "queued", "date": target_date.isoformat(), "task_ids": queued}


@celery_app.task
def evaluate_alert_rules():
    return {"mode": "alert_only", "destructive_action": False}


@celery_app.task
def rebuild_analytics_snapshot():
    from .analytics import rebuild_account_snapshot
    from .db import engine
    return rebuild_account_snapshot(engine, settings.duckdb_path)
