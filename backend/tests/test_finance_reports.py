from datetime import UTC, datetime

import pytest

from search_console.finance_reports import operator_scope_key
from search_console.worker import FINANCE_FUND_TYPES, _finance_datetime, _payment_result_rows


def test_finance_sync_queries_all_documented_fund_types():
    assert FINANCE_FUND_TYPES == (1, 2, 21, 22, 23)


def test_payment_rows_support_baidu_body_list_envelope():
    expected = [{"id": "1"}]
    assert _payment_result_rows({"body": {"list": expected}}) == expected
    assert _payment_result_rows({"body": {"data": [{"list": expected, "total": "1"}]}}) == expected


def test_baidu_payment_time_is_stored_as_utc_from_beijing_time():
    assert _finance_datetime("2026-09-16 08:30:00") == datetime(2026, 9, 16, 0, 30, tzinfo=UTC)


def test_profit_scope_respects_member_operator_range():
    assert operator_scope_key(None, None) == "__all__"
    assert operator_scope_key("王康", ("王康", "王聪")) == "operator:王康"
    assert operator_scope_key(None, ("王聪", "王康")) == "scope:王康|王聪"
    with pytest.raises(ValueError):
        operator_scope_key("其他运营", ("王康", "王聪"))
