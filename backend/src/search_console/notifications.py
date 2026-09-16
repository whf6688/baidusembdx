import hashlib
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .models import (
    Account,
    BackgroundTask,
    Notification,
    NotificationCursor,
    PerformanceDaily,
    Project,
    TaskStatus,
)

BALANCE_METRIC_DAYS = 7
BALANCE_ALERT_DAYS = Decimal("2")
BALANCE_LIFECYCLE_STAGES = ("空账户", "测试期")
REFUND_STAGE = "应退款"
SHANGHAI = ZoneInfo("Asia/Shanghai")
TERMINAL_TASK_STATUSES = (
    TaskStatus.SUCCEEDED,
    TaskStatus.FAILED,
    TaskStatus.BLOCKED,
)


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class BalanceGroupHealth:
    subject: str
    cash_account: str
    account_count: int
    account_ids: tuple[uuid.UUID, ...]
    total_balance: Decimal
    spend_7d: Decimal
    average_daily_spend: Decimal
    balance_days: Decimal | None
    is_fresh: bool
    needs_recharge: bool
    snapshot_at: datetime | None
    metric_start: date
    metric_end: date


def balance_group_key(account: Account) -> tuple[str, str] | None:
    subject = (account.account_subject or "").strip()
    cash_account = (account.recharge_account or "").strip()
    if not subject or not cash_account:
        return None
    return subject, cash_account


def group_low_balance_accounts(
    accounts: list[Account],
) -> dict[tuple[str, str], list[Account]]:
    """Group accounts by subject and configured cash account."""
    grouped: dict[tuple[str, str], list[Account]] = defaultdict(list)
    for account in accounts:
        key = balance_group_key(account)
        if key is None:
            continue
        grouped[key].append(account)
    return grouped


def calculate_balance_group_health(
    accounts: list[Account],
    spend_by_account: dict[uuid.UUID, Decimal],
    *,
    metric_start: date,
    metric_end: date,
    fresh_since: datetime | None = None,
) -> dict[tuple[str, str], BalanceGroupHealth]:
    grouped = group_low_balance_accounts(accounts)
    result: dict[tuple[str, str], BalanceGroupHealth] = {}
    for (subject, cash_account), group_accounts in grouped.items():
        total_balance = sum(
            (Decimal(account.balance or 0) for account in group_accounts),
            Decimal("0"),
        )
        spend_7d = sum(
            (Decimal(spend_by_account.get(account.id, 0)) for account in group_accounts),
            Decimal("0"),
        )
        average_daily_spend = spend_7d / Decimal(BALANCE_METRIC_DAYS)
        snapshots = [account.budget_snapshot_at for account in group_accounts]
        is_fresh = bool(snapshots) and all(
            snapshot is not None and (fresh_since is None or snapshot >= fresh_since)
            for snapshot in snapshots
        )
        snapshot_at = min(
            (snapshot for snapshot in snapshots if snapshot is not None),
            default=None,
        )
        balance_days = (
            total_balance / average_daily_spend
            if average_daily_spend > 0
            else None
        )
        result[(subject, cash_account)] = BalanceGroupHealth(
            subject=subject,
            cash_account=cash_account,
            account_count=len(group_accounts),
            account_ids=tuple(account.id for account in group_accounts),
            total_balance=total_balance,
            spend_7d=spend_7d,
            average_daily_spend=average_daily_spend,
            balance_days=balance_days,
            is_fresh=is_fresh,
            needs_recharge=bool(
                is_fresh
                and average_daily_spend > 0
                and balance_days is not None
                and balance_days < BALANCE_ALERT_DAYS
            ),
            snapshot_at=snapshot_at,
            metric_start=metric_start,
            metric_end=metric_end,
        )
    return result


def load_balance_group_health(
    db: Session,
    project_id: uuid.UUID,
    *,
    local_date: date | None = None,
    fresh_since: datetime | None = None,
) -> dict[tuple[str, str], BalanceGroupHealth]:
    as_of_date = local_date or datetime.now(SHANGHAI).date()
    metric_end = as_of_date - timedelta(days=1)
    metric_start = as_of_date - timedelta(days=BALANCE_METRIC_DAYS)
    accounts = db.scalars(
        select(Account).where(
            Account.project_id == project_id,
            Account.is_active.is_(True),
            Account.eliminated_at.is_(None),
            or_(
                Account.lifecycle_override.in_(BALANCE_LIFECYCLE_STAGES),
                and_(
                    Account.lifecycle_override.is_(None),
                    Account.lifecycle_stage.in_(BALANCE_LIFECYCLE_STAGES),
                ),
            ),
            Account.account_subject.is_not(None),
            Account.account_subject != "",
            Account.recharge_account.is_not(None),
            Account.recharge_account != "",
        )
    ).all()
    if not accounts:
        return {}
    account_ids = [account.id for account in accounts]
    spend_rows = db.execute(
        select(
            PerformanceDaily.account_id,
            func.coalesce(func.sum(PerformanceDaily.spend), 0),
        )
        .where(
            PerformanceDaily.account_id.in_(account_ids),
            PerformanceDaily.report_date.between(metric_start, metric_end),
        )
        .group_by(PerformanceDaily.account_id)
    ).all()
    spend_by_account = {
        account_id: Decimal(spend or 0)
        for account_id, spend in spend_rows
    }
    return calculate_balance_group_health(
        accounts,
        spend_by_account,
        metric_start=metric_start,
        metric_end=metric_end,
        fresh_since=fresh_since,
    )


def _add_notification(db: Session, **values) -> bool:
    statement = pg_insert(Notification).values(**values).on_conflict_do_nothing(
        index_elements=[Notification.dedupe_key]
    )
    return bool(db.execute(statement).rowcount)


def ensure_notification_cursor(db: Session, project_id: uuid.UUID) -> NotificationCursor:
    cursor = db.scalar(
        select(NotificationCursor).where(NotificationCursor.project_id == project_id)
    )
    if cursor is None:
        # A new cursor starts at the current time so existing task history is never
        # mistaken for a newly completed task.
        cursor = NotificationCursor(project_id=project_id, task_updated_at=datetime.now(UTC))
        db.add(cursor)
        db.flush()
    return cursor


def create_task_status_notifications(db: Session, project_id: uuid.UUID) -> int:
    cursor = ensure_notification_cursor(db, project_id)
    rows = db.scalars(
        select(BackgroundTask)
        .where(
            BackgroundTask.project_id == project_id,
            BackgroundTask.updated_at >= cursor.task_updated_at,
            BackgroundTask.status.in_(TERMINAL_TASK_STATUSES),
        )
        .order_by(BackgroundTask.updated_at, BackgroundTask.id)
    ).all()
    created = 0
    labels = {
        TaskStatus.SUCCEEDED: ("任务执行完成", "success"),
        TaskStatus.FAILED: ("任务执行失败", "error"),
        TaskStatus.BLOCKED: ("任务执行受阻", "warning"),
    }
    for task in rows:
        title, severity = labels[task.status]
        summary = f"{task.task_type} · {task.current_node} · 进度 {task.progress}%"
        body_lines = [
            f"任务类型：{task.task_type}",
            f"当前状态：{task.status.value}",
            f"当前节点：{task.current_node}",
            f"执行进度：{task.progress}%",
            f"重试次数：{task.retry_count}",
        ]
        if task.last_error:
            body_lines.append(f"异常信息：{task.last_error}")
        created += int(
            _add_notification(
                db,
                project_id=project_id,
                category="task_status",
                severity=severity,
                title=title,
                summary=summary,
                body="\n".join(body_lines),
                entity_type="background_task",
                entity_id=str(task.id),
                dedupe_key=f"task-status:{task.id}:{task.status.value}",
                payload={
                    "task_id": str(task.id),
                    "task_type": task.task_type,
                    "status": task.status.value,
                    "current_node": task.current_node,
                    "progress": task.progress,
                    "retry_count": task.retry_count,
                    "last_error": task.last_error,
                },
                occurred_at=task.updated_at,
            )
        )
    if rows:
        cursor.task_updated_at = max(row.updated_at for row in rows)
    return created


def create_refund_notifications(db: Session, project_id: uuid.UUID) -> int:
    # Leaving the refund stage clears the episode marker. A later re-entry is a
    # genuinely new reminder; rows already in this stage were baselined by the
    # migration and are intentionally not backfilled.
    db.query(Account).filter(
        Account.project_id == project_id,
        Account.refund_notification_sent_at.is_not(None),
        and_(
            or_(Account.lifecycle_stage.is_(None), Account.lifecycle_stage != REFUND_STAGE),
            or_(Account.lifecycle_override.is_(None), Account.lifecycle_override != REFUND_STAGE),
        ),
    ).update({Account.refund_notification_sent_at: None}, synchronize_session=False)

    accounts = db.scalars(
        select(Account).where(
            Account.project_id == project_id,
            Account.refund_notification_sent_at.is_(None),
            or_(
                Account.lifecycle_stage == REFUND_STAGE,
                Account.lifecycle_override == REFUND_STAGE,
            ),
        )
    ).all()
    created = 0
    now = datetime.now(UTC)
    for account in accounts:
        subject = account.account_subject or account.login_name
        cash_account = account.recharge_account or "未设置"
        created += int(
            _add_notification(
                db,
                project_id=project_id,
                category="refund_due",
                severity="warning",
                title=f"{subject} 应退款",
                summary=f"账户 {account.login_name} · 钱柜账户 {cash_account}",
                body=(
                    f"主体：{subject}\n"
                    f"百度账户：{account.login_name}（{account.baidu_account_id}）\n"
                    f"钱柜账户：{cash_account}\n"
                    "处理建议：核对账户余额和退款资料后办理退款"
                ),
                entity_type="account",
                entity_id=str(account.id),
                dedupe_key=f"refund-due:{account.id}:{now.isoformat()}",
                payload={
                    "subject": subject,
                    "account_id": account.baidu_account_id,
                    "account_name": account.login_name,
                    "cash_account": account.recharge_account,
                },
                occurred_at=now,
            )
        )
        account.refund_notification_sent_at = now
    return created


def create_low_balance_notifications(
    db: Session,
    project_id: uuid.UUID,
    *,
    snapshot_started_at: datetime,
    reminder_date: date | None = None,
) -> int:
    local_date = reminder_date or datetime.now(SHANGHAI).date()
    group_health = load_balance_group_health(
        db,
        project_id,
        local_date=local_date,
        fresh_since=snapshot_started_at,
    )

    created = 0
    now = datetime.now(UTC)
    for (subject, cash_account), health in group_health.items():
        if not health.needs_recharge:
            continue
        balance_days = health.balance_days or Decimal("0")
        group_fingerprint = hashlib.sha256(
            f"{subject}\0{cash_account}".encode("utf-8")
        ).hexdigest()[:20]
        created += int(
            _add_notification(
                db,
                project_id=project_id,
                category="low_balance",
                severity="warning",
                title=f"{subject} · 钱柜 {cash_account} 余额不足 2 天，请充值",
                summary=(
                    f"余额合计 ¥{_money(health.total_balance)} · "
                    f"近7日平均消耗 ¥{_money(health.average_daily_spend)}/天 · "
                    f"预计可用 {balance_days.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)} 天"
                ),
                body=(
                    f"主体：{subject}\n"
                    f"钱柜账户：{cash_account}\n"
                    f"关联账户：{health.account_count} 个\n"
                    f"账户余额合计：¥{_money(health.total_balance)}\n"
                    f"{health.metric_start.isoformat()} 至 {health.metric_end.isoformat()} 消耗：¥{_money(health.spend_7d)}\n"
                    f"近7个完整自然日平均消耗：¥{_money(health.average_daily_spend)}/天\n"
                    f"预计可用：{balance_days.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)} 天\n"
                    "处理建议：请为该钱柜账户充值"
                ),
                entity_type="subject_cash_account",
                entity_id=group_fingerprint,
                dedupe_key=(
                    f"low-balance-days-v2:{project_id}:{group_fingerprint}:{local_date.isoformat()}"
                ),
                payload={
                    "subject": subject,
                    "cash_account": cash_account,
                    "group_account_count": health.account_count,
                    "group_balance": _money(health.total_balance),
                    "spend_7d": _money(health.spend_7d),
                    "average_daily_spend_7d": _money(health.average_daily_spend),
                    "balance_days": str(
                        balance_days.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    ),
                    "rule": "cash_group_balance_below_2_days_7d_average_spend",
                    "alert_days": str(BALANCE_ALERT_DAYS),
                    "date_from": health.metric_start.isoformat(),
                    "date_to": health.metric_end.isoformat(),
                },
                occurred_at=now,
            )
        )
    return created


def reconcile_project_notifications(db: Session, project_id: uuid.UUID) -> dict:
    task_count = create_task_status_notifications(db, project_id)
    refund_count = create_refund_notifications(db, project_id)
    return {"task_status": task_count, "refund_due": refund_count}


def reconcile_all_projects(db: Session) -> dict:
    result = {}
    for project_id in db.scalars(select(Project.id).where(Project.enabled.is_(True))).all():
        result[str(project_id)] = reconcile_project_notifications(db, project_id)
    return result
