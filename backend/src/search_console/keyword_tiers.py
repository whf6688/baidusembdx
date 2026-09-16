from decimal import Decimal, ROUND_HALF_UP

from .schemas import KeywordTierRuleConfig


TIER_RANK = {
    "F拓展": 0,
    "E消耗很小-无复制": 1,
    "E消耗很小-有复制": 1,
    "E消耗很小": 1,
    "D消耗不足-无复制": 2,
    "D消耗不足-有复制": 2,
    "D消耗不足": 2,
    "C成本较高": 3,
    "B机会": 4,
    "A成本": 5,
}

LEGACY_TIER_ALIASES = {
    "D消耗不足-有复制": "D消耗不足",
    "D消耗不足-无复制": "D消耗不足",
    "E消耗很小-有复制": "E消耗很小",
    "E消耗很小-无复制": "E消耗很小",
}


def normalize_tier_name(value: str) -> str:
    """Collapse legacy copy-based D/E labels into the current tier names."""
    return LEGACY_TIER_ALIASES.get(value, value)


def money(value: Decimal | int | float | None) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def classify_keyword(
    *,
    has_performance: bool,
    spend: Decimal | int | float | None,
    copies: int | None,
    adds: int | None,
    rules: KeywordTierRuleConfig,
) -> str:
    """Classify from cumulative performance; zero-spend keywords stay in F."""
    if not has_performance:
        return "F拓展"

    normalized_spend = money(spend)
    normalized_adds = int(adds or 0)
    if normalized_adds > 0:
        if normalized_spend / normalized_adds <= rules.a_add_cost_max:
            return "A成本"
        if normalized_spend / (normalized_adds + 1) < rules.b_next_add_cost_max:
            return "B机会"
        if (
            normalized_spend / (Decimal(normalized_adds) * rules.c_add_growth_factor)
            < rules.c_projected_cost_max
        ):
            return "C成本较高"
        return "成本高"

    if normalized_spend >= rules.empty_spend_min:
        return "空耗"
    if normalized_spend >= rules.d_spend_min:
        return "D消耗不足"
    if normalized_spend == 0:
        return "F拓展"
    return "E消耗很小"
