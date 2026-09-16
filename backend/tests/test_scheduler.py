from search_console.worker import (
    FINAL_ARCHIVE_ACCOUNT_SELECTION,
    HOURLY_ACCOUNT_SELECTION,
    KEYWORD_REPORT_SCOPE,
    account_report_conditions,
    celery_app,
    keyword_report_conditions,
    strategy_schedule_slots,
    _task_heartbeat_expired,
)
from search_console.models import Account, TaskStatus
from sqlalchemy import select
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace


def test_data_cycle_uses_configurable_minute_dispatch_and_fixed_final_archive():
    dispatcher = celery_app.conf.beat_schedule["minute-configurable-data-cycle-dispatch"]["schedule"]
    final = celery_app.conf.beat_schedule["final-previous-day-archive-0030"]["schedule"]

    assert dispatcher._orig_minute == "*"
    assert final._orig_minute == 30
    assert final._orig_hour == 0
    assert celery_app.conf.timezone == "Asia/Shanghai"
    assert "midnight-budget-snapshot" not in celery_app.conf.beat_schedule
    assert "hourly-budget-append-0130-to-2330" not in celery_app.conf.beat_schedule
    assert "account-elimination-2320" not in celery_app.conf.beat_schedule
    assert "minute-strategy-schedule-dispatch" in celery_app.conf.beat_schedule
    assert "fifteen-minute-creative-review-sync" not in celery_app.conf.beat_schedule
    assert "minute-background-task-heartbeat-watchdog" in celery_app.conf.beat_schedule


def test_default_strategy_times_reproduce_the_previous_schedule():
    from search_console.strategies import DEFAULT_STRATEGY_CONFIGS

    day = datetime(2026, 8, 7, tzinfo=UTC)
    assert strategy_schedule_slots(day.replace(hour=0, minute=0), DEFAULT_STRATEGY_CONFIGS["budget_reset"])
    assert strategy_schedule_slots(day.replace(hour=23, minute=20), DEFAULT_STRATEGY_CONFIGS["elimination"])
    assert all(
        strategy_schedule_slots(day.replace(hour=hour, minute=30), DEFAULT_STRATEGY_CONFIGS["budget_append"])
        for hour in range(1, 24)
    )
    assert not strategy_schedule_slots(day.replace(hour=0, minute=30), DEFAULT_STRATEGY_CONFIGS["budget_append"])


def test_stale_active_task_is_closed_but_intentional_wait_is_not():
    now = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    stale = SimpleNamespace(
        status=TaskStatus.RUNNING,
        current_node="queued_for_resume",
        heartbeat_at=now - timedelta(minutes=16),
        updated_at=now - timedelta(minutes=16),
        created_at=now - timedelta(hours=1),
    )
    intentional_wait = SimpleNamespace(
        status=TaskStatus.PENDING,
        current_node="campaign_batch_auto_retry_wait",
        heartbeat_at=now - timedelta(hours=1),
        updated_at=now - timedelta(hours=1),
        created_at=now - timedelta(hours=1),
    )

    assert _task_heartbeat_expired(stale, now) is True
    assert _task_heartbeat_expired(intentional_wait, now) is False


def test_baidu_refresh_account_scope_names_are_explicit():
    assert HOURLY_ACCOUNT_SELECTION == "testing_only"
    assert FINAL_ARCHIVE_ACCOUNT_SELECTION == "testing_as_of_previous_day"
    assert KEYWORD_REPORT_SCOPE == "keyword_daily_second_hop_material_exact"


def test_regular_account_report_scope_excludes_eliminated_blacklist():
    conditions = account_report_conditions(uuid.uuid4(), {
        "account_selection": HOURLY_ACCOUNT_SELECTION,
        "trigger": "hourly_refresh",
    })
    sql = str(select(Account.id).where(*conditions))

    assert "eliminated_at IS NULL" in sql


def test_final_archive_only_allows_accounts_eliminated_on_target_day():
    conditions = account_report_conditions(uuid.uuid4(), {
        "account_selection": FINAL_ARCHIVE_ACCOUNT_SELECTION,
        "trigger": "final_archive",
        "date_to": "2026-07-14",
        "eliminated_on": "2026-07-14",
    })
    sql = str(select(Account.id).where(*conditions))

    assert "eliminated_at IS NULL" in sql
    assert "eliminated_at >=" in sql
    assert "eliminated_at <" in sql


def test_keyword_archive_uses_same_final_scope_and_second_hop_only():
    conditions = keyword_report_conditions(uuid.uuid4(), {
        "account_selection": FINAL_ARCHIVE_ACCOUNT_SELECTION,
        "trigger": "final_archive",
        "date_to": "2026-07-14",
        "eliminated_on": "2026-07-14",
    })
    sql = str(select(Account.id).where(*conditions))

    assert "eliminated_at >=" in sql
    assert "account_type" in sql
