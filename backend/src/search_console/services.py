import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .metrics import calculate_metrics
from .models import (
    Account,
    Alert,
    BackgroundTask,
    Operation,
    OperationStatus,
    PerformanceDaily,
    SyncWatermark,
    TaskStatus,
)
from .schemas import DashboardSummary, MetricValue, OperationCreate

settings = get_settings()


def dashboard_summary(
    db: Session,
    project_id: uuid.UUID | None = None,
    *,
    allowed_operator_names: tuple[str, ...] | None = None,
) -> DashboardSummary:
    totals_query = (
        select(
            func.coalesce(func.sum(PerformanceDaily.spend), 0),
            func.coalesce(func.sum(PerformanceDaily.impressions), 0),
            func.coalesce(func.sum(PerformanceDaily.clicks), 0),
            func.coalesce(func.sum(PerformanceDaily.uv), 0),
            func.coalesce(func.sum(PerformanceDaily.copies), 0),
            func.coalesce(func.sum(PerformanceDaily.adds), 0),
            func.max(PerformanceDaily.source_watermark),
        )
        .select_from(PerformanceDaily)
        .join(Account, PerformanceDaily.account_id == Account.id)
    )
    if project_id is not None:
        totals_query = totals_query.where(Account.project_id == project_id)
    if allowed_operator_names is not None:
        totals_query = totals_query.where(Account.operator_name.in_(allowed_operator_names))
    totals = db.execute(totals_query).one()
    spend, impressions, clicks, uv, copies, adds, watermark = totals
    derived = calculate_metrics(Decimal(spend), clicks, uv, adds)
    active_query = select(func.count()).select_from(Account).where(Account.is_active.is_(True))
    alert_query = select(func.count()).select_from(Alert).join(Account, Alert.account_id == Account.id).where(Alert.status == "open")
    if project_id is not None:
        active_query = active_query.where(Account.project_id == project_id)
        alert_query = alert_query.where(Account.project_id == project_id)
    if allowed_operator_names is not None:
        active_query = active_query.where(Account.operator_name.in_(allowed_operator_names))
        alert_query = alert_query.where(Account.operator_name.in_(allowed_operator_names))
    active = db.scalar(active_query) or 0
    alerts = db.scalar(alert_query) or 0
    hduofen_query = select(func.max(SyncWatermark.source_at)).where(
        SyncWatermark.source == "hduofen"
    )
    if project_id is not None:
        hduofen_query = hduofen_query.where(SyncWatermark.scope == str(project_id))
    hduofen_watermark = db.scalar(hduofen_query)
    return DashboardSummary(
        spend=MetricValue(value=spend), impressions=MetricValue(value=impressions),
        clicks=MetricValue(value=clicks), uv=MetricValue(value=uv), copies=MetricValue(value=copies),
        adds=MetricValue(value=adds), cpc=MetricValue(value=derived["cpc"]),
        uv_cost=MetricValue(value=derived["uv_cost"]), add_cost=MetricValue(value=derived["add_cost"]),
        add_rate=MetricValue(value=derived["add_rate"]), active_accounts=active, alert_count=alerts,
        data_freshness={
            "baidu": watermark,
            "hduofen": hduofen_watermark,
            "snapshot_stale": watermark is None,
        },
    )


def preflight_operation(db: Session, request: OperationCreate, username: str) -> Operation:
    account = db.scalar(select(Account).where(Account.baidu_account_id == request.target_account_id))
    checks = {
        "target_account_exists": account is not None,
        "target_account_permission": bool(account and account.permission_status == "granted"),
        "writes_enabled": settings.baidu_writes_enabled,
        "payload_present": bool(request.payload),
    }
    if request.operation_type == "search_ad_build_workflow":
        account_type = request.payload.get("account_type")
        is_preembedded = account_type == "一跳预埋户"
        uses_keyword_url = account_type == "二跳账户"
        keyword_url_generation = request.payload.get("keyword_url_generation")
        require_empty = request.payload.get("selection_mode") != "specified_accounts"
        checks.update({
            "page_type_ready": bool(request.payload.get("page_type")),
            "promotion_page_ready": bool(request.payload.get("promotion_page")),
            "promotion_link_ready": is_preembedded or bool(request.payload.get("promotion_link")),
            "empty_lifecycle": not require_empty or request.payload.get("lifecycle_stage") == "空账户",
            "workflow_version_present": bool(request.payload.get("workflow_version")),
            "keyword_url_policy_valid": (
                request.payload.get("keyword_url_mode") == "per_keyword_utf8_encoded"
                and request.payload.get("keyword_landing_url") is None
                and isinstance(keyword_url_generation, dict)
                and keyword_url_generation.get("scope") == "per_keyword"
                and keyword_url_generation.get("encoding") == "utf-8"
                and keyword_url_generation.get("keyword_parameter") == "keyword"
                and keyword_url_generation.get("encoded_value_source") == "material_keywords.keyword_utf8_encoded"
                and keyword_url_generation.get("account_parameter") == "zhanghuid"
                and keyword_url_generation.get("account_value_source") == "target_account_id"
                and keyword_url_generation.get("position_parameter") == "e_adposition"
                and keyword_url_generation.get("position_macro") == "{adposition}"
                and keyword_url_generation.get("forbidden_parameter") == "kw_enc_utf8"
            ) if uses_keyword_url else (
                request.payload.get("keyword_url_mode") == "none"
                and request.payload.get("keyword_landing_url") is None
                and keyword_url_generation is None
            ),
        })
    existing = db.scalar(select(Operation).where(Operation.idempotency_key == request.idempotency_key))
    if existing:
        return existing
    operation = Operation(
        operation_type=request.operation_type,
        target_account_id=request.target_account_id,
        idempotency_key=request.idempotency_key,
        payload=request.payload,
        preflight_result=checks,
        requested_by=username,
        status=OperationStatus.AWAITING_CONFIRMATION,
    )
    db.add(operation)
    db.commit()
    db.refresh(operation)
    return operation


def confirm_operation(db: Session, operation_id: uuid.UUID, username: str) -> tuple[Operation, BackgroundTask]:
    operation = db.get(Operation, operation_id)
    if not operation:
        raise HTTPException(status_code=404, detail="操作申请不存在")
    if not settings.baidu_writes_enabled:
        raise HTTPException(status_code=409, detail="百度真实写操作当前处于关闭状态")
    failed = [name for name, passed in operation.preflight_result.items() if name != "writes_enabled" and not passed]
    if failed:
        raise HTTPException(status_code=409, detail=f"预检未通过：{', '.join(failed)}")
    operation.status = OperationStatus.QUEUED
    operation.confirmed_by = username
    operation.confirmed_at = datetime.now(UTC)
    account = db.scalar(select(Account).where(Account.baidu_account_id == operation.target_account_id))
    task = BackgroundTask(
        project_id=account.project_id if account is not None else None,
        operation_id=operation.id,
        task_type=operation.operation_type,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.commit()
    db.refresh(operation)
    db.refresh(task)
    return operation, task
