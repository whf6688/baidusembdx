from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Account, AccountManager


def resolve_manager_recharge_account(
    db: Session,
    manager: AccountManager,
    *,
    update_binding: bool = False,
) -> Account | None:
    """Resolve the manager's configured recharge account without guessing."""

    if manager.financial_settings_mode == "legacy_per_account":
        account = db.get(Account, manager.balance_account_id) if manager.balance_account_id else None
        return account if account is not None and account.manager_id == manager.id else None

    selector = str(manager.recharge_account or "").strip().casefold()
    if not selector:
        if update_binding:
            manager.balance_account_id = None
        return None

    accounts = db.scalars(
        select(Account).where(
            Account.manager_id == manager.id,
            Account.is_active.is_(True),
        )
    ).all()
    matches = [
        account
        for account in accounts
        if account.login_name.strip().casefold() == selector
        or str(account.baidu_account_id) == selector
    ]
    account = matches[0] if len(matches) == 1 else None
    if update_binding:
        manager.balance_account_id = account.id if account is not None else None
    return account


def refresh_manager_recharge_balance(
    db: Session,
    manager: AccountManager,
    *,
    request_batch: str,
) -> dict:
    """Read the configured recharge account balance through the shared safe client."""

    account = resolve_manager_recharge_account(db, manager, update_binding=True)
    if account is None:
        raise ValueError("充值账户未配置，或未在该管家的下辖账户中精确匹配")

    # Imported lazily so the OAuth module can be loaded without initializing a
    # Celery worker. The shared client still applies token selection, rate
    # limiting and API auditing for this read-only request.
    from .worker import call_context, extract_account_info, platform_client

    result = platform_client().execute_read(
        context=call_context(
            account,
            batch=request_batch,
            idempotency_key=uuid.uuid4().hex,
        ),
        service="account.get",
        payload={"accountFields": ["userId", "balance", "budget", "budgetType"]},
    )
    info = extract_account_info(result)
    if info is None or info.get("balance") is None:
        raise ValueError("百度充值账户信息未返回余额")

    captured_at = datetime.now(UTC)
    account.balance = Decimal(str(info["balance"]))
    if info.get("budget") is not None:
        account.current_budget = Decimal(str(info["budget"]))
    if info.get("budgetType") is not None:
        account.budget_type = int(info["budgetType"])
    account.budget_snapshot_at = captured_at
    account.last_synced_at = captured_at
    manager.last_synced_at = captured_at
    return {
        "account_id": account.baidu_account_id,
        "account_name": account.login_name,
        "balance": str(account.balance),
        "snapshot_at": captured_at.isoformat(),
    }
