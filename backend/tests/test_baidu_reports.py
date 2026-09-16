from datetime import date
from decimal import Decimal

import pytest

from search_console.baidu_reports import (
    SEARCH_ACCOUNT_REPORT_TYPE,
    SEARCH_KEYWORD_REPORT_TYPE,
    build_account_report_payload,
    build_keyword_report_payload,
    extract_report_rows,
    extract_report_total_row_count,
    normalize_account_report_rows,
    normalize_keyword_report_rows,
    normalize_report_keyword,
)


def test_account_report_payload_is_account_only_daily_scope():
    payload = build_account_report_payload(date(2026, 2, 14), date(2026, 7, 14))

    assert payload["reportType"] == SEARCH_ACCOUNT_REPORT_TYPE
    assert payload["timeUnit"] == "DAY"
    assert payload["columns"] == ["date", "userId", "userName", "cost", "impression", "click"]
    assert not any(name in payload["columns"] for name in ["campaignId", "adgroupId", "keywordId"])


def test_extract_and_normalize_documented_report_response():
    result = {
        "success": True,
        "status": 200,
        "data": {
            "rowCount": 1,
            "totalRowCount": 1,
            "rows": [{
                "date": "2026-02-14",
                "userId": 123,
                "userName": "account-a",
                "cost": 10.125,
                "impression": 20,
                "click": 3,
            }],
        },
    }

    facts = normalize_account_report_rows(
        extract_report_rows(result),
        target_account_id=123,
        target_login_name="account-a",
        start_date=date(2026, 2, 14),
        end_date=date(2026, 7, 14),
    )

    assert len(facts) == 1
    assert facts[0].spend == Decimal("10.13")
    assert facts[0].impressions == 20


def test_extracts_baidu_sms_body_list_envelope():
    result = {
        "header": {"status": 0},
        "body": {"data": [{"rowCount": 1, "totalRowCount": 1, "rows": [{"date": "2026-02-14"}]}]},
    }

    assert extract_report_rows(result) == [{"date": "2026-02-14"}]


def test_rejects_cross_account_report_rows():
    with pytest.raises(ValueError, match="非目标账户"):
        normalize_account_report_rows(
            [{"date": "2026-02-14", "userId": 999, "userName": "other"}],
            target_account_id=123,
            target_login_name="account-a",
            start_date=date(2026, 2, 14),
            end_date=date(2026, 2, 14),
        )


def test_rejects_duplicate_daily_rows():
    rows = [
        {"date": "2026-02-14", "userId": 123, "userName": "account-a"},
        {"date": "2026-02-14", "userId": 123, "userName": "account-a"},
    ]
    with pytest.raises(ValueError, match="重复行"):
        normalize_account_report_rows(
            rows,
            target_account_id=123,
            target_login_name="account-a",
            start_date=date(2026, 2, 14),
            end_date=date(2026, 2, 14),
        )


def test_keyword_report_payload_is_daily_and_paginated():
    payload = build_keyword_report_payload(
        date(2026, 2, 14),
        date(2026, 7, 14),
        start_row=100_000,
    )

    assert payload["reportType"] == SEARCH_KEYWORD_REPORT_TYPE
    assert payload["timeUnit"] == "DAY"
    assert payload["startRow"] == 100_000
    assert payload["rowCount"] == 100_000
    assert "wInfoNameStatus" in payload["columns"]
    assert "winfoIdTypeEnum" in payload["columns"]


def test_extracts_keyword_report_total_row_count():
    result = {
        "body": {
            "data": [{
                "rowCount": 2,
                "totalRowCount": 123,
                "rows": [{"date": "2026-02-14"}, {"date": "2026-02-15"}],
            }]
        }
    }

    assert extract_report_total_row_count(result) == 123


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("减肥", "减肥"),
        ("减肥[已删除]", "减肥"),
        (" [已删除]减肥[已删除] ", "减肥"),
    ],
)
def test_deleted_marker_is_removed_before_exact_match(raw, expected):
    assert normalize_report_keyword(raw) == expected


def test_keyword_rows_are_target_safe_and_duplicate_keys_are_aggregated():
    rows = [
        {
            "date": "2026-02-14",
            "userId": 123,
            "userName": "account-a",
            "campaignNameStatus": "计划A",
            "winfoIdTypeEnum": 0,
            "wInfoNameStatus": "减肥[已删除]",
            "impression": 20,
            "click": 3,
            "cost": "10.12",
        },
        {
            "date": "2026-02-14",
            "userId": 123,
            "userName": "account-a",
            "campaignNameStatus": "计划A",
            "winfoIdTypeEnum": "关键词",
            "wInfoNameStatus": "减肥",
            "impression": 5,
            "click": 1,
            "cost": "2.01",
        },
        {
            "date": "2026-02-14",
            "userId": 123,
            "userName": "account-a",
            "campaignNameStatus": "计划A",
            "winfoIdTypeEnum": 1,
            "wInfoNameStatus": "词包A",
            "impression": 100,
            "click": 10,
            "cost": "30",
        },
    ]

    facts, non_keyword_rows, deleted_marker_rows = normalize_keyword_report_rows(
        rows,
        target_account_id=123,
        target_login_name="account-a",
        start_date=date(2026, 2, 14),
        end_date=date(2026, 7, 14),
    )

    assert non_keyword_rows == 1
    assert deleted_marker_rows == 1
    assert len(facts) == 1
    assert facts[0].keyword_text == "减肥"
    assert facts[0].impressions == 25
    assert facts[0].clicks == 4
    assert facts[0].spend == Decimal("12.13")


def test_keyword_report_rejects_cross_account_rows():
    with pytest.raises(ValueError, match="非目标账户"):
        normalize_keyword_report_rows(
            [{
                "date": "2026-02-14",
                "userId": 999,
                "userName": "other",
                "wInfoNameStatus": "减肥",
            }],
            target_account_id=123,
            target_login_name="account-a",
            start_date=date(2026, 2, 14),
            end_date=date(2026, 2, 14),
        )
