from decimal import Decimal


def safe_divide(numerator: Decimal | int, denominator: Decimal | int) -> Decimal | None:
    if not denominator:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.01"))


def calculate_metrics(spend: Decimal, clicks: int, uv: int, adds: int) -> dict[str, Decimal | None]:
    return {
        "cpc": safe_divide(spend, clicks),
        "uv_cost": safe_divide(spend, uv),
        "add_cost": safe_divide(spend, adds),
        "add_rate": safe_divide(adds * 100, uv),
    }


def calculate_report_metrics(
    spend: Decimal,
    cash_spend: Decimal | None,
    clicks: int,
    uv: int,
    copies: int,
    adds: int,
) -> dict[str, Decimal | None]:
    """Calculate persisted-report metrics with explicit unavailable cash data."""
    return {
        "cpc": safe_divide(spend, clicks),
        "uv_cost": safe_divide(spend, uv),
        "copy_cost": safe_divide(spend, copies),
        "add_cost": safe_divide(spend, adds),
        "cash_copy_cost": None if cash_spend is None else safe_divide(cash_spend, copies),
        "cash_add_cost": None if cash_spend is None else safe_divide(cash_spend, adds),
        "add_rate": safe_divide(adds * 100, uv),
    }


def calculate_cash_spend(spend: Decimal, rebate_rate: Decimal | None) -> Decimal | None:
    """Convert gross media spend to cash spend using an account rebate percentage."""
    if rebate_rate is None:
        return None
    multiplier = Decimal("1") + (Decimal(rebate_rate) / Decimal("100"))
    return (Decimal(spend) / multiplier).quantize(Decimal("0.01"))
