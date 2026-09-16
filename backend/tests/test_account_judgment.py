from decimal import Decimal

import pytest

from search_console.account_judgment import (
    ACCOUNT_STATUS_ALL_PAUSED,
    ACCOUNT_STATUS_BUDGET_LOW,
    ACCOUNT_STATUS_DISABLED,
    ACCOUNT_STATUS_ELIMINATED,
    ACCOUNT_STATUS_EMPTY,
    ACCOUNT_STATUS_ONLINE,
    ACCOUNT_STATUS_PENDING,
    ACCOUNT_STATUS_REJECTED,
    COST_STATUS_COLD_START,
    COST_STATUS_EMPTY_SPEND,
    COST_STATUS_HIGH,
    COST_STATUS_PENDING,
    COST_STATUS_QUALIFIED,
    COST_STATUS_RISING,
    classify_account_status,
    classify_cost_status,
    normalize_account_judgment_preference,
)


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        ({"remote_status_code": 4, "plan_count": 2, "paused_plan_count": 0, "historical_impressions": 0, "confirmed_eliminated": False, "has_active_allocation": False}, ACCOUNT_STATUS_REJECTED),
        ({"remote_status_code": 7, "plan_count": 0, "paused_plan_count": 0, "historical_impressions": 0, "confirmed_eliminated": False, "has_active_allocation": True}, ACCOUNT_STATUS_DISABLED),
        ({"remote_status_code": 11, "plan_count": 2, "paused_plan_count": 2, "historical_impressions": 0, "confirmed_eliminated": False, "has_active_allocation": False}, ACCOUNT_STATUS_ALL_PAUSED),
        ({"remote_status_code": 11, "plan_count": 2, "paused_plan_count": 1, "historical_impressions": 0, "confirmed_eliminated": False, "has_active_allocation": False}, ACCOUNT_STATUS_BUDGET_LOW),
        ({"remote_status_code": 1, "plan_count": 1, "paused_plan_count": 0, "historical_impressions": 0, "confirmed_eliminated": False, "has_active_allocation": False}, ACCOUNT_STATUS_ONLINE),
        ({"remote_status_code": 4, "plan_count": 0, "paused_plan_count": 0, "historical_impressions": 1, "confirmed_eliminated": False, "has_active_allocation": True}, ACCOUNT_STATUS_ELIMINATED),
        ({"remote_status_code": 1, "plan_count": 0, "paused_plan_count": 0, "historical_impressions": 0, "confirmed_eliminated": False, "has_active_allocation": True}, ACCOUNT_STATUS_PENDING),
        ({"remote_status_code": 1, "plan_count": 0, "paused_plan_count": 0, "historical_impressions": 0, "confirmed_eliminated": False, "has_active_allocation": False}, ACCOUNT_STATUS_EMPTY),
    ],
)
def test_account_status_priority(facts, expected):
    assert classify_account_status(**facts) == expected


@pytest.mark.parametrize(
    ("spend", "count", "cost", "recent_cost", "recent_spend", "recent_count", "expected"),
    [
        ("99.99", 0, None, None, "0", 0, COST_STATUS_COLD_START),
        ("100", 0, None, None, "0", 0, COST_STATUS_EMPTY_SPEND),
        ("300", 2, "120", "120", "20", 1, COST_STATUS_QUALIFIED),
        ("300", 2, "120", "120.01", "120.01", 1, COST_STATUS_RISING),
        ("300", 2, "120", None, "100.01", 0, COST_STATUS_RISING),
        ("300", 2, "120", None, "100", 0, COST_STATUS_QUALIFIED),
        ("300", 2, "120.01", "80", "80", 1, COST_STATUS_HIGH),
        ("300", 2, None, "80", "80", 1, COST_STATUS_PENDING),
    ],
)
def test_cost_status_boundaries(spend, count, cost, recent_cost, recent_spend, recent_count, expected):
    assert classify_cost_status(
        cumulative_spend=Decimal(spend),
        conversion_count=count,
        cash_cost=Decimal(cost) if cost is not None else None,
        recent_cash_cost=Decimal(recent_cost) if recent_cost is not None else None,
        recent_spend=Decimal(recent_spend),
        recent_conversion_count=recent_count,
        cold_start_spend_limit=Decimal("100"),
        cost_limit=Decimal("120"),
    ) == expected


def test_cost_modes_keep_independent_thresholds():
    value = normalize_account_judgment_preference({
        "mode": "copy_cash",
        "add_cash": {"cold_start_spend_limit": "88", "cost_limit": "99"},
        "copy_cash": {"cold_start_spend_limit": "66", "cost_limit": "77"},
    })
    assert value["mode"] == "copy_cash"
    assert value["add_cash"]["cost_limit"] == "99.00"
    assert value["copy_cash"]["cost_limit"] == "77.00"
