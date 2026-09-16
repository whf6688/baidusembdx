import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .account_judgment import COST_MODE_COPY, load_account_judgment_preference
from .metrics import calculate_cash_spend, safe_divide
from .models import (
    Account,
    AccountManager,
    FinancePaymentRecord,
    FinanceProfitInput,
    PerformanceDaily,
    Project,
)


def money(value: Decimal | int | None) -> str:
    return str(Decimal(value or 0).quantize(Decimal("0.01")))


def operator_scope_key(operator_name: str | None, allowed_operator_names: tuple[str, ...] | None) -> str:
    if operator_name:
        if allowed_operator_names is not None and operator_name not in allowed_operator_names:
            raise ValueError("所选运营不在当前成员的数据范围内")
        return f"operator:{operator_name}"
    if allowed_operator_names is None:
        return "__all__"
    return "scope:" + "|".join(sorted(allowed_operator_names))


def recharge_reconciliation_report(
    db: Session,
    project_id: uuid.UUID,
    *,
    date_from: date,
    date_to: date,
    movement_type: str | None,
    reconciliation_status: str | None,
    search: str | None,
    page: int,
    page_size: int,
) -> dict:
    query = (
        select(
            FinancePaymentRecord.pay_date,
            Account.login_name,
            Account.baidu_account_id,
            AccountManager.login_name,
            AccountManager.display_name,
            AccountManager.rebate_rate,
            FinancePaymentRecord.movement_type,
            func.sum(FinancePaymentRecord.account_currency),
            func.sum(FinancePaymentRecord.cash_amount),
            func.max(FinancePaymentRecord.source_watermark),
            func.count(FinancePaymentRecord.id),
            func.count(FinancePaymentRecord.reconciled_at),
        )
        .join(Account, Account.id == FinancePaymentRecord.account_id)
        .join(AccountManager, AccountManager.id == FinancePaymentRecord.manager_id)
        .where(
            FinancePaymentRecord.project_id == project_id,
            FinancePaymentRecord.pay_date.between(date_from, date_to),
        )
        .group_by(
            FinancePaymentRecord.pay_date,
            Account.login_name,
            Account.baidu_account_id,
            AccountManager.login_name,
            AccountManager.display_name,
            AccountManager.rebate_rate,
            FinancePaymentRecord.movement_type,
        )
        .order_by(FinancePaymentRecord.pay_date.desc(), Account.login_name, FinancePaymentRecord.movement_type)
    )
    if movement_type:
        query = query.where(FinancePaymentRecord.movement_type == movement_type)
    values = db.execute(query).all()
    needle = (search or "").strip().casefold()
    rows = []
    for row in values:
        (
            pay_date,
            account_name,
            account_id,
            manager_login,
            manager_name,
            rebate,
            movement,
            account_currency,
            cash_amount,
            watermark,
            record_count,
            reconciled_count,
        ) = row
        reconciled = int(record_count or 0) > 0 and int(record_count or 0) == int(reconciled_count or 0)
        if reconciliation_status == "reconciled" and not reconciled:
            continue
        if reconciliation_status == "unreconciled" and reconciled:
            continue
        haystack = " ".join((str(pay_date), account_name or "", str(account_id), manager_login or "", manager_name or "")).casefold()
        if needle and needle not in haystack:
            continue
        rows.append({
            "date": pay_date.isoformat(),
            "account_name": account_name,
            "account_id": account_id,
            "manager_name": manager_name or manager_login,
            "type": "充值" if movement == "recharge" else "退款",
            "movement_type": movement,
            "account_currency": money(account_currency),
            "rebate_rate": money(rebate) if rebate is not None else None,
            "cash_amount": money(cash_amount),
            "reconciled": reconciled,
            "reconciliation_status": "已对账" if reconciled else "未对账",
            "watermark": watermark.isoformat() if watermark else None,
        })
    total = len(rows)
    summary_account_currency = sum((Decimal(row["account_currency"]) for row in rows), Decimal("0"))
    summary_cash = sum((Decimal(row["cash_amount"]) for row in rows), Decimal("0"))
    watermarks = [row["watermark"] for row in rows if row["watermark"]]
    offset = (page - 1) * page_size
    return {
        "rows": rows[offset:offset + page_size],
        "summary": {
            "account_currency": money(summary_account_currency),
            "cash_amount": money(summary_cash),
        },
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
        "watermark": max(watermarks) if watermarks else None,
    }


def set_reconciliation_status(
    db: Session,
    project_id: uuid.UUID,
    *,
    rows: list,
    reconciled: bool,
    actor: str,
) -> dict:
    requested = {(row.report_date, row.account_id, row.movement_type) for row in rows}
    account_ids = {account_id for _, account_id, _ in requested}
    accounts = {
        int(account.baidu_account_id): account.id
        for account in db.scalars(select(Account).where(
            Account.project_id == project_id,
            Account.baidu_account_id.in_(account_ids),
        )).all()
    }
    updated_records = 0
    updated_groups = 0
    for report_date, baidu_account_id, movement_type in requested:
        account_pk = accounts.get(baidu_account_id)
        if account_pk is None:
            continue
        result = db.execute(
            update(FinancePaymentRecord)
            .where(
                FinancePaymentRecord.project_id == project_id,
                FinancePaymentRecord.account_id == account_pk,
                FinancePaymentRecord.pay_date == report_date,
                FinancePaymentRecord.movement_type == movement_type,
            )
            .values(
                reconciled_at=func.now() if reconciled else None,
                reconciled_by=actor if reconciled else None,
            )
        )
        affected = int(result.rowcount or 0)
        if affected:
            updated_groups += 1
            updated_records += affected
    return {"updated": updated_groups, "updated_records": updated_records, "reconciled": reconciled}


def profit_report(
    db: Session,
    project_id: uuid.UUID,
    *,
    date_from: date,
    date_to: date,
    operator_name: str | None,
    allowed_operator_names: tuple[str, ...] | None,
    search: str | None,
    page: int,
    page_size: int,
) -> dict:
    project = db.get(Project, project_id)
    scope_key = operator_scope_key(operator_name, allowed_operator_names)
    filters = [Account.project_id == project_id, PerformanceDaily.report_date.between(date_from, date_to)]
    if operator_name:
        filters.append(Account.operator_name == operator_name)
    elif allowed_operator_names is not None:
        filters.append(Account.operator_name.in_(allowed_operator_names))
    facts = db.execute(
        select(
            PerformanceDaily.report_date,
            Account.rebate_rate,
            func.sum(PerformanceDaily.spend),
            func.sum(PerformanceDaily.copies),
            func.sum(PerformanceDaily.adds),
        )
        .join(Account, Account.id == PerformanceDaily.account_id)
        .where(*filters)
        .group_by(PerformanceDaily.report_date, Account.rebate_rate)
        .order_by(PerformanceDaily.report_date.desc())
    ).all()
    daily: dict[date, dict] = {}
    for report_date, rebate_rate, spend, copies, adds in facts:
        gross = Decimal(spend or 0)
        if gross <= 0:
            continue
        item = daily.setdefault(report_date, {"account_spend": Decimal("0"), "cash_spend": Decimal("0"), "cash_complete": True, "copies": 0, "adds": 0})
        item["account_spend"] += gross
        cash = calculate_cash_spend(gross, Decimal(rebate_rate) if rebate_rate is not None else None)
        if cash is not None:
            item["cash_spend"] += cash
        else:
            item["cash_complete"] = False
        item["copies"] += int(copies or 0)
        item["adds"] += int(adds or 0)
    input_rows = db.scalars(select(FinanceProfitInput).where(
        FinanceProfitInput.project_id == project_id,
        FinanceProfitInput.report_date.between(date_from, date_to),
        FinanceProfitInput.operator_scope == scope_key,
    )).all()
    inputs = {row.report_date: Decimal(row.reported_spend) for row in input_rows}
    cost_mode = load_account_judgment_preference(db, project_id)["mode"]
    conversion_key = "copies" if cost_mode == COST_MODE_COPY else "adds"
    needle = (search or "").strip().casefold()
    rows = []
    for report_date in sorted(daily, reverse=True):
        values = daily[report_date]
        if needle and needle not in f"{report_date.isoformat()} {project.name}".casefold():
            continue
        reported_spend = inputs.get(report_date)
        conversions = int(values[conversion_key])
        cash_spend = Decimal(values["cash_spend"]) if values["cash_complete"] else None
        rows.append({
            "date": report_date.isoformat(),
            "project_name": project.name,
            "operator_name": operator_name,
            "reported_spend": money(reported_spend) if reported_spend is not None else None,
            "conversions": conversions,
            "reported_conversion_cost": money(safe_divide(reported_spend, conversions)) if reported_spend is not None and conversions else None,
            "account_spend": money(values["account_spend"]),
            "cash_spend": money(cash_spend) if cash_spend is not None else None,
            "cash_conversion_cost": money(safe_divide(cash_spend, conversions)) if cash_spend is not None and conversions else None,
            "profit": money(reported_spend - cash_spend) if reported_spend is not None and cash_spend is not None else None,
        })
    total = len(rows)
    summary_reported_values = [Decimal(row["reported_spend"]) for row in rows if row["reported_spend"] is not None]
    summary_reported = sum(summary_reported_values, Decimal("0")) if summary_reported_values else None
    summary_conversions = sum(int(row["conversions"]) for row in rows)
    summary_account_spend = sum((Decimal(row["account_spend"]) for row in rows), Decimal("0"))
    cash_values = [Decimal(row["cash_spend"]) for row in rows if row["cash_spend"] is not None]
    summary_cash_spend = sum(cash_values, Decimal("0")) if len(cash_values) == len(rows) else None
    offset = (page - 1) * page_size
    operator_query = select(Account.operator_name).where(
        Account.project_id == project_id,
        Account.operator_name.is_not(None),
    ).distinct().order_by(Account.operator_name)
    if allowed_operator_names is not None:
        operator_query = operator_query.where(Account.operator_name.in_(allowed_operator_names))
    operators = [name for name in db.scalars(operator_query).all() if name]
    return {
        "rows": rows[offset:offset + page_size],
        "summary": {
            "reported_spend": money(summary_reported) if summary_reported is not None else None,
            "conversions": summary_conversions,
            "reported_conversion_cost": money(safe_divide(summary_reported, summary_conversions)) if summary_reported is not None and summary_conversions else None,
            "account_spend": money(summary_account_spend),
            "cash_spend": money(summary_cash_spend) if summary_cash_spend is not None else None,
            "cash_conversion_cost": money(safe_divide(summary_cash_spend, summary_conversions)) if summary_cash_spend is not None and summary_conversions else None,
            "profit": money(summary_reported - summary_cash_spend) if summary_reported is not None and summary_cash_spend is not None else None,
        },
        "metric_mode": "copy" if cost_mode == COST_MODE_COPY else "add",
        "operator_name": operator_name,
        "operator_names": operators,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }


def save_profit_inputs(
    db: Session,
    project_id: uuid.UUID,
    *,
    operator_name: str | None,
    allowed_operator_names: tuple[str, ...] | None,
    rows: list,
    actor: str,
) -> int:
    scope_key = operator_scope_key(operator_name, allowed_operator_names)
    count = 0
    for row in rows:
        statement = pg_insert(FinanceProfitInput).values(
            id=uuid.uuid4(),
            project_id=project_id,
            report_date=row.report_date,
            operator_scope=scope_key,
            reported_spend=row.reported_spend,
            updated_by=actor,
            created_at=func.now(),
            updated_at=func.now(),
        ).on_conflict_do_update(
            index_elements=["project_id", "report_date", "operator_scope"],
            set_={"reported_spend": row.reported_spend, "updated_by": actor, "updated_at": func.now()},
        )
        db.execute(statement)
        count += 1
    return count
