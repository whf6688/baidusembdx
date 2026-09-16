import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import String, cast, func, literal, or_, select
from sqlalchemy.orm import Session

from .account_judgment import (
    ACCOUNT_STATUS_IN_USE,
    COST_MODE_ADD,
    account_status_expression,
    cost_judgment_expressions,
    expand_account_status_filter,
    judgment_facts,
    load_account_judgment_preference,
)
from .metrics import calculate_cash_spend, calculate_report_metrics, safe_divide
from .models import Account, AccountManager, AccountType, OcpcProjectCache, PerformanceDaily


SUMMARY_METRIC_KEYS = (
    "impressions", "clicks", "spend", "cash_spend", "uv", "copies", "adds",
    "cpc", "uv_cost", "copy_cost", "add_cost", "cash_add_cost", "cash_copy_cost",
)


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _multi_values(value: str | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in (value or "").split(",") if item.strip()))


def _active_account_filters(project_id: uuid.UUID) -> list:
    """Keep archived accounts available to history tables, but out of the live account list."""
    return [
        Account.project_id == project_id,
        Account.is_active.is_(True),
        or_(
            Account.manager_id.is_(None),
            Account.manager.has(AccountManager.is_active.is_(True)),
        ),
    ]


def _account_type_filter(value: str):
    """Accept the Chinese UI value and the legacy enum name during transition."""
    try:
        resolved = AccountType(value)
    except ValueError:
        try:
            resolved = AccountType[value]
        except KeyError:
            return None
    return Account.account_type == resolved


def _comparison_trends(current: dict, previous: dict) -> dict:
    """Return display-ready comparison data so the web client never derives core metrics."""
    trends = {}
    for key in SUMMARY_METRIC_KEYS:
        current_value = current.get(key)
        previous_value = previous.get(key)
        if current_value is None or previous_value is None:
            trends[key] = {"direction": "muted", "percent": None}
            continue
        current_decimal = Decimal(str(current_value))
        previous_decimal = Decimal(str(previous_value))
        if previous_decimal == 0:
            trends[key] = {"direction": "muted", "percent": None}
            continue
        delta = (current_decimal - previous_decimal) / abs(previous_decimal) * Decimal("100")
        direction = "up" if delta > 0 else "down" if delta < 0 else "flat"
        percent = format(abs(delta).quantize(Decimal("0.1")), "f").rstrip("0").rstrip(".")
        trends[key] = {"direction": direction, "percent": percent}
    return trends


def account_workspace_data(
    db: Session,
    project_id: uuid.UUID,
    *,
    account_uuid: uuid.UUID | None = None,
    date_from: date,
    date_to: date,
    lifecycle: str | None = None,
    lifecycles: str | None = None,
    account_status: str | None = None,
    account_statuses: str | None = None,
    cost_status: str | None = None,
    cost_statuses: str | None = None,
    manager_id: uuid.UUID | None = None,
    manager_ids: str | None = None,
    subject: str | None = None,
    operator_name: str | None = None,
    operator_names: str | None = None,
    account_type: str | None = None,
    account_types: str | None = None,
    page_type: str | None = None,
    page_types: str | None = None,
    remote_status: str | None = None,
    remote_statuses: str | None = None,
    account_names: str | None = None,
    search: str | None = None,
    sort_by: str = "spend",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 20,
    allowed_operator_names: tuple[str, ...] | None = None,
) -> dict:
    """Build the account workspace from local facts only; never calls Baidu."""
    metrics = (
        select(
            PerformanceDaily.account_id.label("account_id"),
            func.coalesce(func.sum(PerformanceDaily.impressions), 0).label("impressions"),
            func.coalesce(func.sum(PerformanceDaily.clicks), 0).label("clicks"),
            func.coalesce(func.sum(PerformanceDaily.spend), 0).label("spend"),
            func.coalesce(func.sum(PerformanceDaily.uv), 0).label("uv"),
            func.coalesce(func.sum(PerformanceDaily.copies), 0).label("copies"),
            func.coalesce(func.sum(PerformanceDaily.adds), 0).label("adds"),
            func.max(PerformanceDaily.source_watermark).label("watermark"),
        )
        .where(PerformanceDaily.report_date.between(date_from, date_to))
        .group_by(PerformanceDaily.account_id)
        .subquery()
    )
    previous_date_to = date_from - timedelta(days=1)
    previous_date_from = previous_date_to - timedelta(days=(date_to - date_from).days)
    previous_metrics = (
        select(
            PerformanceDaily.account_id.label("account_id"),
            func.coalesce(func.sum(PerformanceDaily.impressions), 0).label("impressions"),
            func.coalesce(func.sum(PerformanceDaily.clicks), 0).label("clicks"),
            func.coalesce(func.sum(PerformanceDaily.spend), 0).label("spend"),
            func.coalesce(func.sum(PerformanceDaily.uv), 0).label("uv"),
            func.coalesce(func.sum(PerformanceDaily.copies), 0).label("copies"),
            func.coalesce(func.sum(PerformanceDaily.adds), 0).label("adds"),
            func.max(PerformanceDaily.source_watermark).label("watermark"),
        )
        .where(PerformanceDaily.report_date.between(previous_date_from, previous_date_to))
        .group_by(PerformanceDaily.account_id)
        .subquery()
    )
    facts = judgment_facts(db, project_id)
    judgment_preference = load_account_judgment_preference(db, project_id)
    resolved_account_status = account_status_expression(facts)
    cost_expressions = cost_judgment_expressions(facts, judgment_preference)
    resolved_cost_status = cost_expressions["status"]

    def with_judgment_joins(statement):
        return (
            statement
            .outerjoin(facts.lifetime_metrics, facts.lifetime_metrics.c.account_id == Account.id)
            .outerjoin(facts.recent_metrics, facts.recent_metrics.c.account_id == Account.id)
            .outerjoin(facts.campaign_facts, facts.campaign_facts.c.account_id == Account.id)
        )

    filters = _active_account_filters(project_id)
    if allowed_operator_names is not None:
        filters.append(Account.operator_name.in_(allowed_operator_names))
    if account_uuid:
        filters.append(Account.id == account_uuid)
    facet_filters = list(filters)
    selected_manager_ids = _multi_values(manager_ids)
    if selected_manager_ids:
        try:
            manager_uuid_values = tuple(uuid.UUID(value) for value in selected_manager_ids)
        except ValueError:
            manager_uuid_values = ()
        filters.append(Account.manager_id.in_(manager_uuid_values) if manager_uuid_values else False)
        facet_filters.append(Account.manager_id.in_(manager_uuid_values) if manager_uuid_values else False)
    elif manager_id:
        filters.append(Account.manager_id == manager_id)
        facet_filters.append(Account.manager_id == manager_id)
    if subject:
        filters.append(Account.account_subject == subject)
        facet_filters.append(Account.account_subject == subject)
    selected_operators = _multi_values(operator_names)
    if selected_operators:
        assigned = tuple(value for value in selected_operators if value != "__unassigned__")
        conditions = [Account.operator_name.in_(assigned)] if assigned else []
        if "__unassigned__" in selected_operators:
            conditions.append(or_(Account.operator_name.is_(None), Account.operator_name == ""))
        condition = or_(*conditions)
        filters.append(condition)
        facet_filters.append(condition)
    elif operator_name == "__unassigned__":
        condition = or_(Account.operator_name.is_(None), Account.operator_name == "")
        filters.append(condition)
        facet_filters.append(condition)
    elif operator_name:
        filters.append(Account.operator_name == operator_name)
        facet_filters.append(Account.operator_name == operator_name)
    selected_account_types = _multi_values(account_types)
    if selected_account_types:
        account_type_conditions = [resolved for value in selected_account_types if (resolved := _account_type_filter(value)) is not None]
        condition = or_(*account_type_conditions) if account_type_conditions else False
        filters.append(condition)
        facet_filters.append(condition)
    elif account_type:
        condition = _account_type_filter(account_type)
        if condition is None:
            filters.append(False)
            facet_filters.append(False)
        else:
            filters.append(condition)
            facet_filters.append(condition)
    selected_page_types = _multi_values(page_types)
    if selected_page_types:
        filters.append(Account.page_type.in_(selected_page_types))
        facet_filters.append(Account.page_type.in_(selected_page_types))
    elif page_type:
        filters.append(Account.page_type == page_type)
        facet_filters.append(Account.page_type == page_type)
    selected_statuses = _multi_values(account_statuses or account_status)
    if not selected_statuses and (remote_statuses or remote_status):
        # Compatibility for bookmarked URLs; the account-list UI no longer sends online userStat filters.
        selected_statuses = _multi_values(remote_statuses or remote_status)
    if selected_statuses:
        expanded_statuses = expand_account_status_filter(selected_statuses)
        filters.append(resolved_account_status.in_(expanded_statuses) if expanded_statuses else False)
    selected_cost_statuses = _multi_values(cost_statuses or cost_status)
    if selected_cost_statuses:
        filters.append(resolved_cost_status.in_(selected_cost_statuses))
    if search and search.strip():
        pattern = _like(search.strip())
        condition = or_(
            Account.login_name.ilike(pattern, escape="\\"),
            cast(Account.baidu_account_id, String).ilike(pattern, escape="\\"),
            Account.account_subject.ilike(pattern, escape="\\"),
            Account.recharge_account.ilike(pattern, escape="\\"),
        )
        filters.append(condition)
        facet_filters.append(condition)
    # Legacy lifecycle query parameters are intentionally ignored. They remain in
    # the signature for one release so old links do not fail validation.
    selected_account_names = _multi_values(account_names)
    if selected_account_names:
        filters.append(Account.login_name.in_(selected_account_names))

    spend = func.coalesce(metrics.c.spend, 0)
    adds = func.coalesce(metrics.c.adds, 0)
    impressions = func.coalesce(metrics.c.impressions, 0)
    clicks = func.coalesce(metrics.c.clicks, 0)
    cash_spend = spend / (
        literal(Decimal("1")) + Account.rebate_rate / literal(Decimal("100"))
    )
    sort_fields = {
        "status": resolved_account_status,
        "account_status": resolved_account_status,
        "account_id": Account.baidu_account_id,
        "account_name": Account.login_name,
        "subject": Account.account_subject,
        "lifecycle": resolved_cost_status,
        "cost_status": resolved_cost_status,
        "operator": Account.operator_name,
        "manager": Account.manager_login_name,
        "account_type": cast(Account.account_type, String),
        "page_type": Account.page_type,
        "impressions": impressions,
        "clicks": clicks,
        "spend": spend,
        "adds": adds,
        "copies": func.coalesce(metrics.c.copies, 0),
        "cpm": spend * 1000 / func.nullif(impressions, 0),
        "ctr": clicks * 100 / func.nullif(impressions, 0),
        "add_cost": spend / func.nullif(adds, 0),
        "copy_cost": spend / func.nullif(func.coalesce(metrics.c.copies, 0), 0),
        "cash_add_cost": cash_spend / func.nullif(adds, 0),
        "cash_copy_cost": cash_spend / func.nullif(func.coalesce(metrics.c.copies, 0), 0),
        "budget": Account.current_budget,
        "balance": Account.balance,
        "updated_at": Account.last_synced_at,
    }
    sort_expression = sort_fields.get(sort_by, Account.baidu_account_id)
    order = sort_expression.desc().nulls_last() if sort_order == "desc" else sort_expression.asc().nulls_last()
    total = int(db.scalar(with_judgment_joins(select(func.count(Account.id)).select_from(Account)).where(*filters)) or 0)
    rows = db.execute(
        with_judgment_joins(select(Account, metrics, resolved_account_status.label("account_status"), resolved_cost_status.label("cost_status")))
        .outerjoin(metrics, metrics.c.account_id == Account.id)
        .where(*filters)
        .order_by(order, Account.baidu_account_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    def aggregate_summary(metric_source):
        aggregate = db.execute(
            with_judgment_joins(select(
                func.coalesce(func.sum(metric_source.c.spend), 0),
                func.coalesce(func.sum(metric_source.c.impressions), 0),
                func.coalesce(func.sum(metric_source.c.clicks), 0),
                func.coalesce(func.sum(metric_source.c.uv), 0),
                func.coalesce(func.sum(metric_source.c.copies), 0),
                func.coalesce(func.sum(metric_source.c.adds), 0),
                func.max(metric_source.c.watermark),
            ).select_from(Account))
            .outerjoin(metric_source, metric_source.c.account_id == Account.id)
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
        cash_groups = db.execute(
            with_judgment_joins(select(metric_source.c.spend, Account.rebate_rate).select_from(Account))
            .join(metric_source, metric_source.c.account_id == Account.id)
            .where(*filters)
        ).all()
        cash_values = [
            calculate_cash_spend(Decimal(group_spend or 0), Decimal(rate) if rate is not None else None)
            for group_spend, rate in cash_groups
        ]
        cash_spend = (
            sum((value for value in cash_values if value is not None), Decimal("0"))
            if cash_groups and all(value is not None for value in cash_values)
            else None
        )
        derived = calculate_report_metrics(
            total_spend, cash_spend, totals["clicks"], totals["uv"], totals["copies"], totals["adds"],
        )
        return {
            "spend": str(total_spend),
            "cash_spend": str(cash_spend) if cash_spend is not None else None,
            **totals,
            **{key: str(value) if value is not None else None for key, value in derived.items()},
        }, aggregate[6]

    summary_payload, summary_watermark = aggregate_summary(metrics)
    previous_summary_payload, _ = aggregate_summary(previous_metrics)
    status_counts = {
        str(stage): int(count)
        for stage, count in db.execute(
            with_judgment_joins(select(resolved_account_status, func.count(Account.id)).select_from(Account))
            .where(*facet_filters)
            .group_by(resolved_account_status)
        ).all()
    }
    cost_status_counts = {
        str(stage): int(count)
        for stage, count in db.execute(
            with_judgment_joins(select(resolved_cost_status, func.count(Account.id)).select_from(Account))
            .where(*facet_filters)
            .group_by(resolved_cost_status)
        ).all()
    }
    result_rows = []
    for row in rows:
        account = row[0]
        values = row._mapping
        row_spend = Decimal(values.get("spend") or 0)
        row_adds = int(values.get("adds") or 0)
        row_copies = int(values.get("copies") or 0)
        row_impressions = int(values.get("impressions") or 0)
        row_clicks = int(values.get("clicks") or 0)
        row_cash_spend = calculate_cash_spend(
            row_spend,
            Decimal(account.rebate_rate) if account.rebate_rate is not None else None,
        )
        row_cash_add_cost = None if row_cash_spend is None else safe_divide(row_cash_spend, row_adds)
        row_cash_copy_cost = None if row_cash_spend is None else safe_divide(row_cash_spend, row_copies)
        cpm = safe_divide(row_spend * 1000, row_impressions)
        ctr = safe_divide(row_clicks * 100, row_impressions)
        result_rows.append({
            "id": str(account.id), "account_id": account.baidu_account_id,
            "account_name": account.login_name, "subject": account.account_subject,
            "remote_status_code": account.remote_status_code,
            "account_status": str(values.get("account_status")),
            "cost_status": str(values.get("cost_status")),
            "manager_id": str(account.manager_id) if account.manager_id else None,
            "manager_name": account.manager.login_name if account.manager else account.manager_login_name,
            "operator_name": account.operator_name, "account_type": account.account_type.value,
            "page_type": account.page_type, "promotion_page": account.promotion_page,
            "promotion_link": account.landing_url_template,
            "rebate_rate": str(account.rebate_rate) if account.rebate_rate is not None else None,
            "cash_account": account.recharge_account,
            "spend": str(row_spend), "adds": row_adds,
            "add_cost": str(row_spend / row_adds) if row_adds else None,
            "copy_cost": str(row_spend / row_copies) if row_copies else None,
            "cash_add_cost": str(row_cash_add_cost) if row_cash_add_cost is not None else None,
            "cash_copy_cost": str(row_cash_copy_cost) if row_cash_copy_cost is not None else None,
            "impressions": row_impressions, "clicks": row_clicks,
            "cpm": str(cpm) if cpm is not None else None,
            "ctr": str(ctr) if ctr is not None else None,
            "uv": int(values.get("uv") or 0),
            "copies": row_copies,
            "budget": str(account.current_budget) if account.current_budget is not None else None,
            "balance": str(account.balance), "balance_snapshot_at": account.budget_snapshot_at,
            "permission_status": account.permission_status, "is_active": account.is_active,
            "campaign_cache_status": account.campaign_cache_status,
            "campaign_cache_synced_at": account.campaign_cache_synced_at,
            "last_synced_at": account.last_synced_at,
            "data_watermark": values.get("watermark"),
        })
    return {
        "date_from": date_from, "date_to": date_to,
        "rows": result_rows, "total": total, "page": page, "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
        "summary": {
            "account_count": total,
            **summary_payload,
        },
        "comparison": {
            "date_from": previous_date_from,
            "date_to": previous_date_to,
            "summary": previous_summary_payload,
            "trends": _comparison_trends(summary_payload, previous_summary_payload),
        },
        "account_status_counts": status_counts,
        "cost_status_counts": cost_status_counts,
        "cost_judgment": judgment_preference,
        "watermark": summary_watermark,
    }


def account_ocpc_project_cache_data(
    db: Session,
    project_id: uuid.UUID,
    account_id: uuid.UUID,
) -> dict | None:
    """Return one account's locally cached oCPC projects without a Baidu request."""
    account = db.scalar(select(Account).where(
        Account.id == account_id,
        Account.project_id == project_id,
        Account.is_active.is_(True),
    ))
    if account is None:
        return None
    projects = db.scalars(
        select(OcpcProjectCache)
        .where(
            OcpcProjectCache.project_id == project_id,
            OcpcProjectCache.account_id == account_id,
            OcpcProjectCache.is_active.is_(True),
        )
        .order_by(OcpcProjectCache.project_name.asc().nulls_last(), OcpcProjectCache.baidu_ocpc_project_id)
    ).all()
    return {
        "account_id": str(account.id),
        "account_name": account.login_name,
        "cache_status": account.ocpc_cache_status,
        "cache_synced_at": account.ocpc_cache_synced_at,
        "rows": [
            {
                "id": str(project.id),
                "ocpc_project_id": project.baidu_ocpc_project_id,
                "ocpc_project_name": project.project_name,
                "ocpc_bid": str(project.ocpc_bid) if project.ocpc_bid is not None else None,
                "bid_type": project.bid_type,
                "remote_status": project.remote_status,
                "scope": project.scope or [],
                "last_seen_at": project.last_seen_at,
            }
            for project in projects
        ],
    }


def account_workspace_facets(
    db: Session,
    project_id: uuid.UUID,
    *,
    allowed_operator_names: tuple[str, ...] | None = None,
) -> dict:
    scope_filters = (
        [Account.operator_name.in_(allowed_operator_names)]
        if allowed_operator_names is not None
        else []
    )
    def values(column):
        return [
            value for value in db.scalars(
                select(column).where(
                    *_active_account_filters(project_id),
                    *scope_filters,
                    column.is_not(None),
                    column != "",
                )
                .distinct().order_by(column)
            ).all()
        ]
    managers = db.execute(
        select(AccountManager.id, AccountManager.login_name)
        .where(
            AccountManager.project_id == project_id,
            AccountManager.is_active.is_(True),
            *(
                [AccountManager.id.in_(select(Account.manager_id).where(
                    Account.project_id == project_id,
                    Account.operator_name.in_(allowed_operator_names),
                ))]
                if allowed_operator_names is not None
                else []
            ),
        )
        .order_by(AccountManager.login_name)
    ).all()
    account_types = [
        value.value if isinstance(value, AccountType) else str(value)
        for value in db.scalars(
            select(Account.account_type)
            .where(*_active_account_filters(project_id), *scope_filters)
            .distinct().order_by(Account.account_type)
        ).all()
    ]
    return {
        "subjects": values(Account.account_subject), "operators": values(Account.operator_name),
        "account_types": account_types, "page_types": values(Account.page_type),
        "account_names": values(Account.login_name),
        "managers": [{"id": str(item.id), "name": item.login_name} for item in managers],
    }
