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


def needs_budget_reset(
    current_budget: Decimal | None,
    *,
    target_budget: Decimal = TARGET_DAILY_BUDGET,
) -> bool:
    return current_budget is not None and current_budget != target_budget


def is_budget_append_candidate(
    *,
    spend: Decimal,
    adds: int,
    current_budget: Decimal | None,
    add_cost_limit: Decimal = ADD_COST_LIMIT,
    utilization_limit: Decimal = BUDGET_UTILIZATION_LIMIT,
) -> bool:
    if adds <= 0 or current_budget is None or current_budget <= 0:
        return False
    add_cost = spend / Decimal(adds)
    utilization = spend / current_budget
    return add_cost < add_cost_limit and utilization > utilization_limit
