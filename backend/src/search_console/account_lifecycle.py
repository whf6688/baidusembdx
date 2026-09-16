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
    must never reclassify an account.  This predicate is only called after the
    automatic elimination workflow has deleted and read back one account's
    campaigns.
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
) -> str | None:
    """Return the strict 23:20 elimination rule that an account matches."""
    if total_spend < 0 or total_adds < 0:
        raise ValueError("elimination metrics cannot be negative")
    def display(value: Decimal) -> str:
        text = format(value, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text

    spend_limit_text = display(spend_without_add_limit)
    cost_limit_text = display(add_cost_limit)
    if total_spend > spend_without_add_limit and total_adds == 0:
        return f"累计消费大于{spend_limit_text}元且无加粉"
    if total_adds > 0 and total_spend / Decimal(total_adds) > add_cost_limit:
        return f"累计加粉成本大于{cost_limit_text}元"
    return None
