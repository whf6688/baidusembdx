from decimal import Decimal
from typing import Iterable


EMPTY = "空账户"
TESTING = "测试期"
ELIMINATED = "已淘汰"
REFUND_DUE = "应退款"
RETURNED = "退户"
MANUAL_LIFECYCLE_STAGES = frozenset({EMPTY, TESTING, ELIMINATED, REFUND_DUE, RETURNED})


def subject_accounts_are_all_eliminated(stages: Iterable[str | None]) -> bool:
    """Return whether an elimination event may promote one subject to refund due.

    Lifecycle is event driven.  Merely observing keywords, campaigns or spend
    must never reclassify an account. This predicate is only called after a
    manually confirmed retirement has deleted and read back an account's
    projects and campaigns.
    """
    values = list(stages)
    return bool(values) and all(stage == ELIMINATED for stage in values)


def resolve_lifecycle(automatic_stage: str, manual_override: str | None) -> str:
    """Return the persisted lifecycle while preserving automatic classification by default."""
    if manual_override is None:
        return automatic_stage
    if manual_override not in MANUAL_LIFECYCLE_STAGES:
        raise ValueError("unsupported manual lifecycle override")
    return manual_override


def elimination_reason(
    total_spend: Decimal,
    total_adds: int,
    *,
    spend_without_add_limit: Decimal = Decimal("100"),
    add_cost_limit: Decimal = Decimal("120"),
    cash_spend: Decimal | None = None,
    require_cash_spend: bool = False,
    conversion_label: str = "加粉",
) -> str | None:
    """Return the strict rule that requires an account's campaigns to be paused."""
    if total_spend < 0 or total_adds < 0:
        raise ValueError("elimination metrics cannot be negative")
    def display(value: Decimal) -> str:
        text = format(value, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text

    spend_limit_text = display(spend_without_add_limit)
    cost_limit_text = display(add_cost_limit)
    if require_cash_spend and cash_spend is None:
        return None
    cost_spend = cash_spend if cash_spend is not None else total_spend
    if cost_spend > spend_without_add_limit and total_adds == 0:
        return f"累计现金消费大于{spend_limit_text}元且无{conversion_label}"
    if total_adds > 0 and cost_spend / Decimal(total_adds) > add_cost_limit:
        return f"累计{conversion_label}现金成本大于{cost_limit_text}元"
    return None
