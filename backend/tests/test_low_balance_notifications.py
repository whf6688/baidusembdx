import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from search_console.notifications import (
    calculate_balance_group_health,
    group_low_balance_accounts,
)


def test_low_balance_accounts_are_grouped_by_subject_and_cash_account():
    rows = [
        SimpleNamespace(account_subject="主体甲", recharge_account="钱柜A"),
        SimpleNamespace(account_subject="主体甲", recharge_account="钱柜A"),
        SimpleNamespace(account_subject="主体甲", recharge_account="钱柜B"),
        SimpleNamespace(account_subject="主体乙", recharge_account="钱柜A"),
    ]

    grouped = group_low_balance_accounts(rows)

    assert {key: len(value) for key, value in grouped.items()} == {
        ("主体甲", "钱柜A"): 2,
        ("主体甲", "钱柜B"): 1,
        ("主体乙", "钱柜A"): 1,
    }


def test_missing_cash_account_and_blank_subject_are_skipped():
    rows = [
        SimpleNamespace(account_subject="主体甲", recharge_account=None),
        SimpleNamespace(account_subject="主体甲", recharge_account="  "),
        SimpleNamespace(account_subject="  ", recharge_account="钱柜A"),
    ]

    grouped = group_low_balance_accounts(rows)

    assert grouped == {}


def _account(subject: str, cash: str, balance: str, snapshot_at: datetime):
    return SimpleNamespace(
        id=uuid.uuid4(),
        account_subject=subject,
        recharge_account=cash,
        balance=Decimal(balance),
        budget_snapshot_at=snapshot_at,
    )


def test_group_balance_below_seven_day_average_spend_needs_recharge():
    now = datetime.now(UTC)
    first = _account("主体甲", "钱柜A", "30", now)
    second = _account("主体甲", "钱柜A", "20", now)

    result = calculate_balance_group_health(
        [first, second],
        {first.id: Decimal("420"), second.id: Decimal("280")},
        metric_start=date(2026, 7, 11),
        metric_end=date(2026, 7, 17),
        fresh_since=now - timedelta(hours=1),
    )[("主体甲", "钱柜A")]

    assert result.total_balance == Decimal("50")
    assert result.average_daily_spend == Decimal("100")
    assert result.balance_days == Decimal("0.5")
    assert result.needs_recharge is True


def test_group_balance_at_two_days_or_stale_snapshot_does_not_alert():
    now = datetime.now(UTC)
    current = _account("主体甲", "钱柜A", "200", now)
    stale = _account("主体乙", "钱柜B", "10", now - timedelta(days=1))

    result = calculate_balance_group_health(
        [current, stale],
        {current.id: Decimal("700"), stale.id: Decimal("700")},
        metric_start=date(2026, 7, 11),
        metric_end=date(2026, 7, 17),
        fresh_since=now - timedelta(hours=1),
    )

    assert result[("主体甲", "钱柜A")].balance_days == Decimal("2")
    assert result[("主体甲", "钱柜A")].needs_recharge is False
    assert result[("主体乙", "钱柜B")].is_fresh is False
    assert result[("主体乙", "钱柜B")].needs_recharge is False
