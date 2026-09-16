from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterable


TARGET_DAILY_BUDGET = Decimal("50.00")
BUDGET_INCREMENT = Decimal("50.00")
ADD_COST_LIMIT = Decimal("100.00")
BUDGET_UTILIZATION_LIMIT = Decimal("0.80")


def snapshot_is_fresh(
    captured_at: datetime | None,
    *,
    now: datetime,
    max_age: timedelta = timedelta(minutes=60),
) -> bool:
    return captured_at is not None and captured_at >= now - max_age


def budget_snapshot_coverage(
    captured_at_values: Iterable[datetime | None],
    *,
    now: datetime,
) -> dict[str, int | str | bool]:
    values = list(captured_at_values)
    total = len(values)
    known = sum(value is not None for value in values)
    fresh = sum(snapshot_is_fresh(value, now=now) for value in values)
    available = fresh == total
    if available:
        status = "ready"
    elif fresh:
        status = "partial"
    elif known:
        status = "stale"
    else:
        status = "missing"
    return {
        "status": status,
        "available": available,
        "total_count": total,
        "fresh_count": fresh,
        "missing_count": total - fresh,
    }


def budget_snapshot_skip_reason(
    captured_at: datetime | None,
    *,
    now: datetime,
) -> tuple[str, str] | None:
    """Return the account-level reason that prevents safe budget execution."""
    if captured_at is None:
        return "budget_snapshot_missing", "预算快照缺失"
    if not snapshot_is_fresh(captured_at, now=now):
        return "budget_snapshot_stale", "预算快照已过期"
    return None


def budget_snapshot_scope_is_available(
    captured_at_values: Iterable[datetime | None],
    *,
    now: datetime,
) -> bool:
    """A partial cohort can run; only a non-empty cohort with no fresh data is blocked."""
    values = list(captured_at_values)
    return not values or any(snapshot_is_fresh(value, now=now) for value in values)


def needs_budget_reset(
    current_budget: Decimal | None,
    *,
    target_budget: Decimal = TARGET_DAILY_BUDGET,
    minimum_difference: Decimal = Decimal("0.01"),
) -> bool:
    return (
        current_budget is not None
        and abs(current_budget - target_budget) >= minimum_difference
    )


def is_budget_append_candidate(
    *,
    spend: Decimal,
    adds: int | None = None,
    conversions: int | None = None,
    cash_spend: Decimal | None = None,
    require_cash_spend: bool = False,
    current_budget: Decimal | None,
    add_cost_limit: Decimal | None = None,
    cost_limit: Decimal | None = None,
    utilization_limit: Decimal = BUDGET_UTILIZATION_LIMIT,
) -> bool:
    conversion_count = conversions if conversions is not None else int(adds or 0)
    resolved_cost_limit = cost_limit if cost_limit is not None else (add_cost_limit or ADD_COST_LIMIT)
    if conversion_count <= 0 or current_budget is None or current_budget <= 0:
        return False
    if require_cash_spend and cash_spend is None:
        return False
    cost_spend = cash_spend if cash_spend is not None else spend
    conversion_cost = cost_spend / Decimal(conversion_count)
    utilization = spend / current_budget
    return conversion_cost < resolved_cost_limit and utilization > utilization_limit
