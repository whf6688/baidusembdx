from decimal import Decimal

import pytest

from search_console.account_lifecycle import elimination_reason
from search_console.budgets import is_budget_append_candidate, needs_budget_reset
from search_console.strategies import (
    DEFAULT_STRATEGY_CONFIGS,
    StrategyConfigError,
    budget_append_amount,
    config_hash,
    normalize_budget_append_round_amounts,
    validate_strategy_config,
)


def test_default_strategy_configs_preserve_existing_budget_rules():
    reset = validate_strategy_config("budget_reset", DEFAULT_STRATEGY_CONFIGS["budget_reset"])
    append = validate_strategy_config("budget_append", DEFAULT_STRATEGY_CONFIGS["budget_append"])
    assert reset == {
        "target_budget": "50.00",
        "minimum_difference": "0.01",
        "failure_retry_count": 3,
        "failure_retry_interval_seconds": 60,
        "schedule_times": ["00:00"],
    }
    assert len(append["schedule_times"]) == 23
    assert append["schedule_times"][0] == "01:30"
    assert append["schedule_times"][-1] == "23:30"
    assert len(append["round_amounts"]) == 10
    assert append["round_amounts"][0] == {"round": 1, "amount": "50.00"}
    assert append["round_amounts"][-1] == {"round": 10, "amount": "50.00"}
    assert needs_budget_reset(Decimal("50"), target_budget=Decimal(reset["target_budget"])) is False
    assert is_budget_append_candidate(
        spend=Decimal("90"), adds=1, current_budget=Decimal("100"),
        add_cost_limit=Decimal(append["add_cost_limit"]),
        utilization_limit=Decimal(append["utilization_limit"]),
    ) is True


def test_budget_reset_accepts_a_custom_fixed_daily_budget():
    reset = validate_strategy_config(
        "budget_reset",
        {"target_budget": "87.6", "schedule_times": ["02:15"]},
    )

    assert reset == {
        "target_budget": "87.60",
        "minimum_difference": "0.01",
        "failure_retry_count": 3,
        "failure_retry_interval_seconds": 60,
        "schedule_times": ["02:15"],
    }
    assert needs_budget_reset(
        Decimal("87.60"), target_budget=Decimal(reset["target_budget"]),
    ) is False
    assert needs_budget_reset(
        Decimal("50.00"), target_budget=Decimal(reset["target_budget"]),
    ) is True


def test_default_elimination_config_preserves_strict_boundaries():
    config = validate_strategy_config("elimination", DEFAULT_STRATEGY_CONFIGS["elimination"])
    kwargs = {
        "spend_without_add_limit": Decimal(config["spend_without_add_limit"]),
        "add_cost_limit": Decimal(config["add_cost_limit"]),
    }
    assert elimination_reason(Decimal("100"), 0, **kwargs) is None
    assert elimination_reason(Decimal("100.01"), 0, **kwargs) == "累计现金消费大于100元且无加粉"
    assert elimination_reason(Decimal("120"), 1, **kwargs) is None
    assert elimination_reason(Decimal("120.01"), 1, **kwargs) == "累计加粉现金成本大于120元"


def test_strategy_validation_normalizes_times_and_rejects_unsafe_values():
    value = validate_strategy_config("budget_append", {
        "round_amounts": [
            {"round": round_number, "amount": round_number * 10}
            for round_number in range(1, 11)
        ],
        "add_cost_limit": 100, "utilization_limit": "0.8",
        "schedule_times": ["23:30", "01:30", "01:30"],
    })
    assert value["schedule_times"] == ["01:30", "23:30"]
    assert value["round_amounts"][0]["amount"] == "10.00"
    assert budget_append_amount(value, 3) == Decimal("30.00")
    assert budget_append_amount(value, 15) == Decimal("100.00")
    with pytest.raises(StrategyConfigError):
        validate_strategy_config("budget_append", {**value, "utilization_limit": "1.1"})
    with pytest.raises(StrategyConfigError):
        validate_strategy_config("elimination", {"spend_without_add_limit": 100, "add_cost_limit": 120, "schedule_times": ["10:00", "11:00"]})


def test_budget_append_legacy_increment_is_compatible_but_normalizes_to_rounds():
    amounts = normalize_budget_append_round_amounts({"increment": 35})
    assert len(amounts) == 10
    assert {item["amount"] for item in amounts} == {"35.00"}


def test_budget_append_requires_all_ten_unique_rounds():
    with pytest.raises(StrategyConfigError):
        validate_strategy_config("budget_append", {
            "round_amounts": [{"round": 1, "amount": 50}],
            "add_cost_limit": 100,
            "utilization_limit": "0.8",
            "schedule_times": ["01:30"],
        })


def test_strategy_hash_is_order_independent():
    assert config_hash({"a": 1, "b": 2}) == config_hash({"b": 2, "a": 1})


def test_global_strategy_configs_use_the_same_version_validation_pipeline():
    assert validate_strategy_config("account_status", {"rules_version": "anything"}) == {
        "rules_version": "account-status-v1"
    }
    cost = validate_strategy_config("cost_judgment", {
        "mode": "copy_cash",
        "add_cash": {"cold_start_spend_limit": "88", "cost_limit": "99"},
        "copy_cash": {"cold_start_spend_limit": "66", "cost_limit": "77"},
    })
    assert cost["mode"] == "copy_cash"
    assert cost["copy_cash"]["cost_limit"] == "77.00"
    realtime = validate_strategy_config("realtime_closure", {
        "report_refresh_minutes": 30,
        "timezone": "UTC",
        "automation_guard": False,
    })
    assert realtime == {
        "report_refresh_minutes": 30,
        "timezone": "UTC",
        "automation_guard": True,
    }
