from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from .account_judgment import (
    account_status_expression,
    cost_judgment_expressions,
    expand_account_status_filter,
    judgment_facts,
    load_account_judgment_preference,
)
from .manager_balance import resolve_manager_recharge_account
from .models import Account, AccountManager, AccountType


REMOTE_STATUS_LABELS = {
    1: "开户金未到",
    2: "正常生效",
    3: "余额为零",
    4: "未通过审核",
    6: "审核中",
    7: "被禁用",
    11: "预算不足",
}


def _search_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _multi_values(value: str | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in (value or "").split(",") if item.strip()))


def _account_type_filter(value: str):
    try:
        return Account.account_type == AccountType(value)
    except ValueError:
        try:
            return Account.account_type == AccountType[value]
        except KeyError:
            return False


def account_management_data(
    db: Session,
    project_id: uuid.UUID,
    *,
    manager_id: uuid.UUID | None = None,
    operator_name: str | None = None,
    account_type: str | None = None,
    page_type: str | None = None,
    remote_status: str | None = None,
    authorization_status: str | None = None,
    search: str | None = None,
    sort_by: str = "account_id",
    sort_order: str = "asc",
    page: int = 1,
    page_size: int = 50,
    allowed_operator_names: tuple[str, ...] | None = None,
) -> dict:
    filters = [Account.project_id == project_id, Account.is_active.is_(True)]
    if allowed_operator_names is not None:
        filters.append(Account.operator_name.in_(allowed_operator_names))
    if manager_id:
        filters.append(Account.manager_id == manager_id)
    if operator_name == "__unassigned__":
        filters.append(or_(Account.operator_name.is_(None), Account.operator_name == ""))
    elif operator_name:
        filters.append(Account.operator_name == operator_name)
    if account_type:
        filters.append(_account_type_filter(account_type))
    if page_type:
        filters.append(Account.page_type == page_type)
    if remote_status == "missing":
        filters.append(Account.remote_status_code.is_(None))
    elif remote_status:
        filters.append(Account.remote_status_code == int(remote_status))
    if authorization_status:
        filters.append(Account.permission_status == authorization_status)
    if search and search.strip():
        pattern = _search_pattern(search.strip())
        filters.append(or_(
            Account.login_name.ilike(pattern, escape="\\"),
            cast(Account.baidu_account_id, String).ilike(pattern, escape="\\"),
        ))

    sort_fields = {
        "account_id": Account.baidu_account_id,
        "account_name": Account.login_name,
        "operator_name": Account.operator_name,
        "account_type": cast(Account.account_type, String),
        "page_type": Account.page_type,
        "remote_status": Account.remote_status_code,
        "authorization": Account.permission_status,
    }
    sort_expression = sort_fields.get(sort_by, Account.baidu_account_id)
    order = sort_expression.desc().nulls_last() if sort_order == "desc" else sort_expression.asc().nulls_last()
    total = int(db.scalar(select(func.count(Account.id)).where(*filters)) or 0)
    rows = db.scalars(
        select(Account).where(*filters).order_by(order, Account.baidu_account_id)
        .offset((page - 1) * page_size).limit(page_size)
    ).all()

    managers = {
        manager.id: manager
        for manager in db.scalars(select(AccountManager).where(AccountManager.project_id == project_id)).all()
    }
    shared_balance: dict[uuid.UUID, tuple[Decimal | None, str | None, object | None]] = {}
    for manager_id_value, manager in managers.items():
        recharge = resolve_manager_recharge_account(db, manager)
        shared_balance[manager_id_value] = (
            recharge.balance if recharge is not None and recharge.budget_snapshot_at is not None else None,
            recharge.login_name if recharge is not None else None,
            recharge.budget_snapshot_at if recharge is not None else None,
        )

    result_rows = []
    for account in rows:
        balance, balance_name, balance_at = shared_balance.get(account.manager_id, (None, None, None))
        status_label = (
            REMOTE_STATUS_LABELS.get(account.remote_status_code, f"未知状态（{account.remote_status_code}）")
            if account.remote_status_code is not None else "未同步"
        )
        result_rows.append({
            "id": str(account.id), "account_id": account.baidu_account_id,
            "account_name": account.login_name,
            "manager_id": str(account.manager_id) if account.manager_id else None,
            "manager_name": managers.get(account.manager_id).login_name if account.manager_id in managers else account.manager_login_name,
            "operator_name": account.operator_name,
            "account_type": account.account_type.value,
            "page_type": account.page_type,
            "promotion_page": account.promotion_page,
            "promotion_link": account.landing_url_template,
            "balance": str(balance) if balance is not None else None,
            "balance_source_account_name": balance_name,
            "balance_snapshot_at": balance_at,
            "rebate_rate": str(account.rebate_rate) if account.rebate_rate is not None else None,
            "remote_status_code": account.remote_status_code,
            "remote_status_text": status_label,
            "remote_status_at": account.remote_status_at,
            "authorization_status": account.permission_status,
            "is_active": account.is_active,
        })
    return {
        "rows": result_rows, "total": total, "page": page, "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }


def account_selection_ids(
    db: Session,
    project_id: uuid.UUID,
    *,
    manager_id: uuid.UUID | None = None,
    manager_ids: str | None = None,
    lifecycle: str | None = None,
    lifecycles: str | None = None,
    account_status: str | None = None,
    account_statuses: str | None = None,
    cost_status: str | None = None,
    cost_statuses: str | None = None,
    operator_name: str | None = None,
    operator_names: str | None = None,
    account_type: str | None = None,
    account_types: str | None = None,
    page_type: str | None = None,
    page_types: str | None = None,
    remote_status: str | None = None,
    remote_statuses: str | None = None,
    account_names: str | None = None,
    authorization_status: str | None = None,
    search: str | None = None,
    allowed_operator_names: tuple[str, ...] | None = None,
) -> list[str]:
    filters = [
        Account.project_id == project_id,
        Account.is_active.is_(True),
        or_(Account.manager_id.is_(None), Account.manager.has(AccountManager.is_active.is_(True))),
    ]
    if allowed_operator_names is not None:
        filters.append(Account.operator_name.in_(allowed_operator_names))
    selected_manager_ids = _multi_values(manager_ids)
    if selected_manager_ids:
        try:
            manager_uuid_values = tuple(uuid.UUID(value) for value in selected_manager_ids)
        except ValueError:
            manager_uuid_values = ()
        filters.append(Account.manager_id.in_(manager_uuid_values) if manager_uuid_values else False)
    elif manager_id:
        filters.append(Account.manager_id == manager_id)
    facts = judgment_facts(db, project_id)
    preference = load_account_judgment_preference(db, project_id)
    resolved_account_status = account_status_expression(facts)
    resolved_cost_status = cost_judgment_expressions(facts, preference)["status"]
    selected_account_statuses = _multi_values(account_statuses or account_status)
    if selected_account_statuses:
        expanded = expand_account_status_filter(selected_account_statuses)
        filters.append(resolved_account_status.in_(expanded) if expanded else False)
    selected_cost_statuses = _multi_values(cost_statuses or cost_status)
    if selected_cost_statuses:
        filters.append(resolved_cost_status.in_(selected_cost_statuses))
    selected_operators = _multi_values(operator_names)
    if selected_operators:
        assigned = tuple(value for value in selected_operators if value != "__unassigned__")
        conditions = [Account.operator_name.in_(assigned)] if assigned else []
        if "__unassigned__" in selected_operators:
            conditions.append(or_(Account.operator_name.is_(None), Account.operator_name == ""))
        filters.append(or_(*conditions))
    elif operator_name == "__unassigned__":
        filters.append(or_(Account.operator_name.is_(None), Account.operator_name == ""))
    elif operator_name:
        filters.append(Account.operator_name == operator_name)
    selected_account_types = _multi_values(account_types)
    if selected_account_types:
        filters.append(or_(*[_account_type_filter(value) for value in selected_account_types]))
    elif account_type:
        filters.append(_account_type_filter(account_type))
    selected_page_types = _multi_values(page_types)
    if selected_page_types:
        filters.append(Account.page_type.in_(selected_page_types))
    elif page_type:
        filters.append(Account.page_type == page_type)
    selected_statuses = _multi_values(remote_statuses)
    if selected_statuses and not selected_account_statuses:
        status_conditions = []
        if "missing" in selected_statuses:
            status_conditions.append(Account.remote_status_code.is_(None))
        status_codes = tuple(int(value) for value in selected_statuses if value != "missing" and value.isdigit())
        if status_codes:
            status_conditions.append(Account.remote_status_code.in_(status_codes))
        filters.append(or_(*status_conditions) if status_conditions else False)
    elif remote_status == "missing" and not selected_account_statuses:
        filters.append(Account.remote_status_code.is_(None))
    elif remote_status and not selected_account_statuses:
        filters.append(Account.remote_status_code == int(remote_status))
    if authorization_status:
        filters.append(Account.permission_status == authorization_status)
    selected_account_names = _multi_values(account_names)
    if selected_account_names:
        filters.append(Account.login_name.in_(selected_account_names))
    if search and search.strip():
        pattern = _search_pattern(search.strip())
        filters.append(or_(
            Account.login_name.ilike(pattern, escape="\\"),
            cast(Account.baidu_account_id, String).ilike(pattern, escape="\\"),
            Account.account_subject.ilike(pattern, escape="\\"),
            Account.recharge_account.ilike(pattern, escape="\\"),
        ))
    query = (
        select(Account.id)
        .outerjoin(facts.lifetime_metrics, facts.lifetime_metrics.c.account_id == Account.id)
        .outerjoin(facts.recent_metrics, facts.recent_metrics.c.account_id == Account.id)
        .outerjoin(facts.campaign_facts, facts.campaign_facts.c.account_id == Account.id)
        .where(*filters)
        .order_by(Account.baidu_account_id)
    )
    return [str(value) for value in db.scalars(query).all()]
