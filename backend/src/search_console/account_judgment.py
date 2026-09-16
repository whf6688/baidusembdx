from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import case, func, literal, or_, select
from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo

from .models import (
    Account,
    AdBuildBatch,
    AdBuildJob,
    CampaignCache,
    PerformanceDaily,
    ProjectPreference,
)


ACCOUNT_JUDGMENT_PREFERENCE_KEY = "account_judgment"

ACCOUNT_STATUS_REJECTED = "未通过审核"
ACCOUNT_STATUS_DISABLED = "被禁用"
ACCOUNT_STATUS_ALL_PAUSED = "计划全停"
ACCOUNT_STATUS_BUDGET_LOW = "预算不足"
ACCOUNT_STATUS_ONLINE = "上线"
ACCOUNT_STATUS_ELIMINATED = "已淘汰"
ACCOUNT_STATUS_PENDING = "待上线"
ACCOUNT_STATUS_EMPTY = "空账户"
ACCOUNT_STATUS_IN_USE = "current"

ACCOUNT_STATUS_VALUES = (
    ACCOUNT_STATUS_REJECTED,
    ACCOUNT_STATUS_DISABLED,
    ACCOUNT_STATUS_ALL_PAUSED,
    ACCOUNT_STATUS_BUDGET_LOW,
    ACCOUNT_STATUS_ONLINE,
    ACCOUNT_STATUS_ELIMINATED,
    ACCOUNT_STATUS_PENDING,
    ACCOUNT_STATUS_EMPTY,
)
IN_USE_ACCOUNT_STATUSES = (
    ACCOUNT_STATUS_REJECTED,
    ACCOUNT_STATUS_DISABLED,
    ACCOUNT_STATUS_ALL_PAUSED,
    ACCOUNT_STATUS_BUDGET_LOW,
    ACCOUNT_STATUS_ONLINE,
)

COST_MODE_ADD = "add_cash"
COST_MODE_COPY = "copy_cash"
COST_MODES = (COST_MODE_ADD, COST_MODE_COPY)
COST_STATUS_COLD_START = "冷启动期"
COST_STATUS_EMPTY_SPEND = "空耗"
COST_STATUS_HIGH = "成本高"
COST_STATUS_RISING = "成本上涨"
COST_STATUS_QUALIFIED = "成本合格"
COST_STATUS_PENDING = "待判断"
COST_STATUS_VALUES = (
    COST_STATUS_COLD_START,
    COST_STATUS_EMPTY_SPEND,
    COST_STATUS_HIGH,
    COST_STATUS_RISING,
    COST_STATUS_QUALIFIED,
    COST_STATUS_PENDING,
)

ACTIVE_ALLOCATION_BATCH_STATUSES = (
    "ready",
    "scheduled",
    "waiting_writes",
    "waiting_baidu_api",
    "dispatched",
)
ACTIVE_ALLOCATION_JOB_STATUSES = ("ready", "scheduled")


def default_account_judgment_preference() -> dict:
    return {
        "mode": COST_MODE_ADD,
        "add_cash": {
            "cold_start_spend_limit": "100.00",
            "cost_limit": "120.00",
        },
        "copy_cash": {
            "cold_start_spend_limit": "100.00",
            "cost_limit": "120.00",
        },
    }


def _decimal_setting(value: object, field_name: str) -> Decimal:
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}必须是有效金额") from exc
    if resolved < 0 or resolved > Decimal("1000000"):
        raise ValueError(f"{field_name}必须在 0–1000000 之间")
    return resolved.quantize(Decimal("0.01"))


def normalize_account_judgment_preference(value: dict | None) -> dict:
    defaults = default_account_judgment_preference()
    incoming = value if isinstance(value, dict) else {}
    mode = str(incoming.get("mode") or defaults["mode"])
    if mode not in COST_MODES:
        raise ValueError("成本判断方式无效")
    normalized = {"mode": mode}
    for key, label in ((COST_MODE_ADD, "加粉现金成本"), (COST_MODE_COPY, "复制现金成本")):
        candidate = incoming.get(key) if isinstance(incoming.get(key), dict) else {}
        source = {**defaults[key], **candidate}
        normalized[key] = {
            "cold_start_spend_limit": str(
                _decimal_setting(source.get("cold_start_spend_limit"), f"{label}冷启动消耗线")
            ),
            "cost_limit": str(_decimal_setting(source.get("cost_limit"), f"{label}合格成本线")),
        }
    return normalized


def load_account_judgment_preference(db: Session, project_id: uuid.UUID) -> dict:
    row = db.scalar(select(ProjectPreference).where(
        ProjectPreference.project_id == project_id,
        ProjectPreference.key == ACCOUNT_JUDGMENT_PREFERENCE_KEY,
    ))
    return normalize_account_judgment_preference(row.value if row else None)


def classify_account_status(
    *,
    remote_status_code: int | None,
    plan_count: int,
    paused_plan_count: int,
    historical_impressions: int,
    confirmed_eliminated: bool,
    has_active_allocation: bool,
) -> str:
    """Apply the product rule in one testable place; eliminated is the final state."""
    if plan_count == 0 and (confirmed_eliminated or historical_impressions > 0):
        return ACCOUNT_STATUS_ELIMINATED
    if remote_status_code == 4:
        return ACCOUNT_STATUS_REJECTED
    if remote_status_code == 7:
        return ACCOUNT_STATUS_DISABLED
    if plan_count > 0:
        if paused_plan_count == plan_count:
            return ACCOUNT_STATUS_ALL_PAUSED
        if remote_status_code == 11:
            return ACCOUNT_STATUS_BUDGET_LOW
        return ACCOUNT_STATUS_ONLINE
    return ACCOUNT_STATUS_PENDING if has_active_allocation else ACCOUNT_STATUS_EMPTY


def classify_cost_status(
    *,
    cumulative_spend: Decimal,
    conversion_count: int,
    cash_cost: Decimal | None,
    recent_cash_cost: Decimal | None,
    recent_spend: Decimal,
    recent_conversion_count: int,
    cold_start_spend_limit: Decimal,
    cost_limit: Decimal,
) -> str:
    if conversion_count <= 0:
        return (
            COST_STATUS_COLD_START
            if cumulative_spend < cold_start_spend_limit
            else COST_STATUS_EMPTY_SPEND
        )
    if cash_cost is None:
        return COST_STATUS_PENDING
    if cash_cost > cost_limit:
        return COST_STATUS_HIGH
    recent_cost_is_high = recent_cash_cost is not None and recent_cash_cost > cost_limit
    recent_empty_spend_is_high = (
        recent_conversion_count <= 0 and recent_spend > cold_start_spend_limit
    )
    return COST_STATUS_RISING if recent_cost_is_high or recent_empty_spend_is_high else COST_STATUS_QUALIFIED


@dataclass(frozen=True)
class JudgmentFacts:
    lifetime_metrics: object
    recent_metrics: object
    campaign_facts: object
    active_allocation_account_ids: frozenset[int]


def judgment_facts(db: Session, project_id: uuid.UUID) -> JudgmentFacts:
    lifetime_metrics = (
        select(
            PerformanceDaily.account_id.label("account_id"),
            func.coalesce(func.sum(PerformanceDaily.impressions), 0).label("historical_impressions"),
            func.coalesce(func.sum(PerformanceDaily.spend), 0).label("cumulative_spend"),
            func.coalesce(func.sum(PerformanceDaily.adds), 0).label("cumulative_adds"),
            func.coalesce(func.sum(PerformanceDaily.copies), 0).label("cumulative_copies"),
        )
        .group_by(PerformanceDaily.account_id)
        .subquery()
    )
    recent_end = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    recent_start = recent_end - timedelta(days=6)
    recent_metrics = (
        select(
            PerformanceDaily.account_id.label("account_id"),
            func.coalesce(func.sum(PerformanceDaily.spend), 0).label("recent_spend"),
            func.coalesce(func.sum(PerformanceDaily.adds), 0).label("recent_adds"),
            func.coalesce(func.sum(PerformanceDaily.copies), 0).label("recent_copies"),
        )
        .where(
            PerformanceDaily.report_date >= recent_start,
            PerformanceDaily.report_date <= recent_end,
        )
        .group_by(PerformanceDaily.account_id)
        .subquery()
    )
    campaign_facts = (
        select(
            CampaignCache.account_id.label("account_id"),
            func.count(CampaignCache.id).label("plan_count"),
            func.sum(case((CampaignCache.pause.is_(True), 1), else_=0)).label("paused_plan_count"),
        )
        .where(CampaignCache.is_active.is_(True))
        .group_by(CampaignCache.account_id)
        .subquery()
    )
    batches = db.execute(
        select(AdBuildBatch.account_ids)
        .join(AdBuildJob, AdBuildJob.id == AdBuildBatch.job_id)
        .where(
            AdBuildJob.project_id == project_id,
            AdBuildJob.status.in_(ACTIVE_ALLOCATION_JOB_STATUSES),
            AdBuildBatch.status.in_(ACTIVE_ALLOCATION_BATCH_STATUSES),
        )
    ).scalars().all()
    allocated: set[int] = set()
    for values in batches:
        if not isinstance(values, list):
            continue
        for value in values:
            try:
                allocated.add(int(value))
            except (TypeError, ValueError):
                continue
    return JudgmentFacts(lifetime_metrics, recent_metrics, campaign_facts, frozenset(allocated))


def account_status_expression(facts: JudgmentFacts):
    plans = func.coalesce(facts.campaign_facts.c.plan_count, 0)
    paused = func.coalesce(facts.campaign_facts.c.paused_plan_count, 0)
    impressions = func.coalesce(facts.lifetime_metrics.c.historical_impressions, 0)
    no_plans = plans == 0
    eliminated_fact = or_(
        Account.eliminated_at.is_not(None),
        func.coalesce(Account.lifecycle_override, Account.lifecycle_stage, "") == ACCOUNT_STATUS_ELIMINATED,
    )
    has_allocation = (
        Account.baidu_account_id.in_(tuple(facts.active_allocation_account_ids))
        if facts.active_allocation_account_ids
        else literal(False)
    )
    return case(
        ((no_plans & (eliminated_fact | (impressions > 0))), ACCOUNT_STATUS_ELIMINATED),
        (Account.remote_status_code == 4, ACCOUNT_STATUS_REJECTED),
        (Account.remote_status_code == 7, ACCOUNT_STATUS_DISABLED),
        (((plans > 0) & (paused == plans)), ACCOUNT_STATUS_ALL_PAUSED),
        (((plans > 0) & (Account.remote_status_code == 11)), ACCOUNT_STATUS_BUDGET_LOW),
        ((plans > 0), ACCOUNT_STATUS_ONLINE),
        (has_allocation, ACCOUNT_STATUS_PENDING),
        else_=ACCOUNT_STATUS_EMPTY,
    )


def load_account_statuses(db: Session, project_id: uuid.UUID) -> dict[int, str]:
    """Return the canonical account status for every account in one project."""
    facts = judgment_facts(db, project_id)
    status = account_status_expression(facts)
    rows = db.execute(
        select(Account.baidu_account_id, status)
        .outerjoin(
            facts.lifetime_metrics,
            facts.lifetime_metrics.c.account_id == Account.id,
        )
        .outerjoin(
            facts.recent_metrics,
            facts.recent_metrics.c.account_id == Account.id,
        )
        .outerjoin(
            facts.campaign_facts,
            facts.campaign_facts.c.account_id == Account.id,
        )
        .where(Account.project_id == project_id)
    ).all()
    return {int(account_id): str(account_status) for account_id, account_status in rows}


def cost_judgment_expressions(facts: JudgmentFacts, preference: dict):
    mode = preference["mode"]
    rules = preference[mode]
    spend = func.coalesce(facts.lifetime_metrics.c.cumulative_spend, 0)
    conversions = func.coalesce(
        facts.lifetime_metrics.c.cumulative_adds
        if mode == COST_MODE_ADD
        else facts.lifetime_metrics.c.cumulative_copies,
        0,
    )
    cash_spend = spend / (
        literal(Decimal("1")) + Account.rebate_rate / literal(Decimal("100"))
    )
    cash_cost = cash_spend / func.nullif(conversions, 0)
    recent_spend = func.coalesce(facts.recent_metrics.c.recent_spend, 0)
    recent_conversions = func.coalesce(
        facts.recent_metrics.c.recent_adds
        if mode == COST_MODE_ADD
        else facts.recent_metrics.c.recent_copies,
        0,
    )
    recent_cash_spend = recent_spend / (
        literal(Decimal("1")) + Account.rebate_rate / literal(Decimal("100"))
    )
    recent_cash_cost = recent_cash_spend / func.nullif(recent_conversions, 0)
    cold_limit = Decimal(rules["cold_start_spend_limit"])
    cost_limit = Decimal(rules["cost_limit"])
    status = case(
        (((conversions <= 0) & (spend < cold_limit)), COST_STATUS_COLD_START),
        ((conversions <= 0), COST_STATUS_EMPTY_SPEND),
        ((cash_cost.is_(None)), COST_STATUS_PENDING),
        ((cash_cost > cost_limit), COST_STATUS_HIGH),
        (((recent_cash_cost > cost_limit) | ((recent_conversions <= 0) & (recent_spend > cold_limit))), COST_STATUS_RISING),
        else_=COST_STATUS_QUALIFIED,
    )
    return {
        "mode": mode,
        "spend": spend,
        "conversions": conversions,
        "cash_cost": cash_cost,
        "recent_cash_cost": recent_cash_cost,
        "recent_spend": recent_spend,
        "recent_conversions": recent_conversions,
        "status": status,
    }


def expand_account_status_filter(values: tuple[str, ...]) -> tuple[str, ...]:
    expanded: list[str] = []
    for value in values:
        expanded.extend(IN_USE_ACCOUNT_STATUSES if value == ACCOUNT_STATUS_IN_USE else (value,))
    return tuple(dict.fromkeys(item for item in expanded if item in ACCOUNT_STATUS_VALUES))
