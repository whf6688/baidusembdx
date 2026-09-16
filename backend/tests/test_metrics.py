from decimal import Decimal

from search_console.metrics import (
    calculate_cash_spend,
    calculate_metrics,
    calculate_report_metrics,
    safe_divide,
)


def test_metric_formulas_use_fixed_decimal():
    metrics = calculate_metrics(Decimal("100.00"), clicks=20, uv=10, adds=2)
    assert metrics == {"cpc": Decimal("5.00"), "uv_cost": Decimal("10.00"), "add_cost": Decimal("50.00"), "add_rate": Decimal("20.00")}


def test_zero_denominator_is_none():
    assert safe_divide(100, 0) is None


def test_daily_report_metrics_include_copy_and_cash_costs():
    metrics = calculate_report_metrics(
        Decimal("120.00"),
        Decimal("90.00"),
        clicks=24,
        uv=12,
        copies=6,
        adds=3,
    )
    assert metrics == {
        "cpc": Decimal("5.00"),
        "uv_cost": Decimal("10.00"),
        "copy_cost": Decimal("20.00"),
        "add_cost": Decimal("40.00"),
        "cash_copy_cost": Decimal("15.00"),
        "cash_add_cost": Decimal("30.00"),
        "add_rate": Decimal("25.00"),
    }


def test_cash_add_cost_is_unavailable_without_verified_cash_spend():
    metrics = calculate_report_metrics(
        Decimal("120.00"), None, clicks=24, uv=12, copies=6, adds=3
    )
    assert metrics["cash_add_cost"] is None


def test_cash_spend_uses_account_rebate_percentage():
    assert calculate_cash_spend(Decimal("120.00"), Decimal("20")) == Decimal("100.00")
    assert calculate_cash_spend(Decimal("120.00"), None) is None
