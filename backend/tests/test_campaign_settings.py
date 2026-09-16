from datetime import UTC, datetime, timedelta
import uuid

from search_console.models import AccountType
from search_console.schemas import CampaignBatchUpdateRequest, CampaignSettingsScopeRequest
from search_console.worker import (
    _campaign_account_matches_task_scope,
    _campaign_auto_retry_plan,
    _campaign_cache_is_fresh,
    _campaign_retry_not_before,
)


def test_campaign_scope_accepts_all_account_and_page_types():
    payload = CampaignSettingsScopeRequest(account_type=None, page_type=None)

    assert payload.account_type is None
    assert payload.page_type is None


def test_campaign_scope_accepts_only_account_type():
    payload = CampaignSettingsScopeRequest(account_type="二跳账户", page_type=None)

    assert payload.account_type == AccountType.SECOND_HOP
    assert payload.page_type is None


def test_campaign_scope_accepts_only_page_type():
    payload = CampaignSettingsScopeRequest(account_type=None, page_type="科普账户")

    assert payload.account_type is None
    assert payload.page_type == "科普账户"


def test_campaign_batch_request_accepts_all_scope():
    payload = CampaignBatchUpdateRequest(
        account_type=None,
        page_type=None,
        action="schedule",
        online_weekdays=[1, 2, 3, 4, 5],
        online_start_hour=8,
        online_end_hour=23,
    )

    assert payload.account_type is None
    assert payload.page_type is None


def test_campaign_batch_request_defaults_to_08_through_24():
    payload = CampaignBatchUpdateRequest(action="schedule")

    assert payload.online_start_hour == 8
    assert payload.online_end_hour == 24


def test_campaign_batch_request_accepts_independent_online_windows():
    payload = CampaignBatchUpdateRequest(
        action="schedule",
        online_schedule=[
            {"weekDay": 1, "startHour": 8, "endHour": 12},
            {"weekDay": 1, "startHour": 14, "endHour": 18},
        ],
    )

    assert payload.online_schedule is not None
    assert payload.online_schedule[1].startHour == 14


def test_campaign_batch_request_accepts_cross_midnight_window():
    payload = CampaignBatchUpdateRequest(
        action="schedule",
        online_weekdays=[1],
        online_start_hour=12,
        online_end_hour=2,
    )

    assert payload.online_start_hour == 12
    assert payload.online_end_hour == 2


def test_campaign_batch_request_keeps_explicit_account_selection():
    account_id = uuid.uuid4()
    payload = CampaignBatchUpdateRequest(
        action="pause",
        pause=True,
        account_ids=[account_id, account_id],
    )

    assert payload.account_ids == [account_id]


class _CampaignAccount:
    is_active = True
    eliminated_at = None
    lifecycle_override = "测试期"
    lifecycle_stage = "测试期"
    account_type = AccountType.SECOND_HOP
    page_type = "科普账户"


def test_campaign_worker_all_scope_matches_account():
    assert _campaign_account_matches_task_scope(_CampaignAccount(), {
        "account_type": None,
        "page_type": None,
    })


def test_campaign_worker_does_not_restrict_lifecycle():
    account = _CampaignAccount()
    account.lifecycle_override = "空账户"
    account.lifecycle_stage = "空账户"

    assert _campaign_account_matches_task_scope(account, {
        "account_type": None,
        "page_type": None,
    })


def test_campaign_worker_single_optional_filter_matches_account():
    assert _campaign_account_matches_task_scope(_CampaignAccount(), {
        "account_type": "二跳账户",
        "page_type": None,
    })
    assert _campaign_account_matches_task_scope(_CampaignAccount(), {
        "account_type": None,
        "page_type": "科普账户",
    })


def test_campaign_worker_rejects_nonmatching_optional_filter():
    assert not _campaign_account_matches_task_scope(_CampaignAccount(), {
        "account_type": "一跳空户",
        "page_type": None,
    })
    assert not _campaign_account_matches_task_scope(_CampaignAccount(), {
        "account_type": None,
        "page_type": "软文账户",
    })


def test_campaign_cache_remains_valid_until_rebuild_marks_it_stale():
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    account = _CampaignAccount()
    account.campaign_cache_status = "succeeded"
    account.campaign_cache_synced_at = now - timedelta(hours=2)

    assert _campaign_cache_is_fresh(account, now=now)

    account.campaign_cache_status = "stale"
    assert not _campaign_cache_is_fresh(account, now=now)

    account.campaign_cache_status = "succeeded"
    account.campaign_cache_synced_at = now - timedelta(hours=7)
    assert _campaign_cache_is_fresh(account, now=now)

    account.campaign_cache_synced_at = None
    assert not _campaign_cache_is_fresh(account, now=now)


def test_campaign_failed_accounts_receive_bounded_backoff_retries():
    first = _campaign_auto_retry_plan({}, [1001, 1002])
    second = _campaign_auto_retry_plan({"auto_retry_attempt": 1}, [1001])
    third = _campaign_auto_retry_plan({"auto_retry_attempt": 2}, [1001])

    assert first == {"attempt": 1, "delay_seconds": 60}
    assert second == {"attempt": 2, "delay_seconds": 300}
    assert third == {"attempt": 3, "delay_seconds": 900}
    assert _campaign_auto_retry_plan({"auto_retry_attempt": 3}, [1001]) is None
    assert _campaign_auto_retry_plan({}, []) is None


def test_campaign_retry_not_before_is_normalized_to_utc():
    value = _campaign_retry_not_before({
        "auto_retry_not_before": "2026-07-20T21:05:00+08:00",
    })

    assert value == datetime(2026, 7, 20, 13, 5, tzinfo=UTC)
    assert _campaign_retry_not_before({}) is None
