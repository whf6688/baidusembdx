from datetime import UTC, datetime, timedelta
from decimal import Decimal

from search_console.budgets import (
    budget_snapshot_coverage,
    is_budget_append_candidate,
    needs_budget_reset,
    snapshot_is_fresh,
)


def test_budget_snapshot_freshness_uses_sixty_minute_window():
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    assert snapshot_is_fresh(now - timedelta(minutes=59), now=now) is True
    assert snapshot_is_fresh(now - timedelta(minutes=61), now=now) is False
    assert snapshot_is_fresh(None, now=now) is False


def test_budget_snapshot_coverage_distinguishes_partial_and_stale_data():
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    partial = budget_snapshot_coverage(
        [now - timedelta(minutes=5), None],
        now=now,
    )
    assert partial == {
        "status": "partial",
        "available": False,
        "total_count": 2,
        "fresh_count": 1,
        "missing_count": 1,
    }

    stale = budget_snapshot_coverage(
        [now - timedelta(minutes=61)],
        now=now,
    )
    assert stale["status"] == "stale"
    assert stale["available"] is False


def test_budget_snapshot_coverage_is_ready_only_when_current_cohort_is_complete():
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    ready = budget_snapshot_coverage(
        [now - timedelta(minutes=5), now - timedelta(minutes=20)],
        now=now,
    )
    assert ready["status"] == "ready"
    assert ready["available"] is True
    assert ready["missing_count"] == 0


def test_budget_reset_only_targets_known_non_default_budget():
    assert needs_budget_reset(Decimal("80")) is True
    assert needs_budget_reset(Decimal("50")) is False
    assert needs_budget_reset(None) is False
    assert needs_budget_reset(
        Decimal("80"), target_budget=Decimal("80"),
    ) is False
    assert needs_budget_reset(
        Decimal("50"), target_budget=Decimal("80"),
    ) is True


def test_budget_append_requires_adds_low_cost_and_high_utilization():
    assert is_budget_append_candidate(
        spend=Decimal("90"),
        adds=1,
        current_budget=Decimal("100"),
    ) is True
    assert is_budget_append_candidate(
        spend=Decimal("80"),
        adds=1,
        current_budget=Decimal("100"),
    ) is False
    assert is_budget_append_candidate(
        spend=Decimal("101"),
        adds=1,
        current_budget=Decimal("110"),
    ) is False
    assert is_budget_append_candidate(
        spend=Decimal("90"),
        adds=0,
        current_budget=Decimal("100"),
    ) is False
