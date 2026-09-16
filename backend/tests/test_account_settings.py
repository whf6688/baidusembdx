from decimal import Decimal
import uuid

import pytest
from pydantic import ValidationError

from search_console.schemas import AccountBatchSettings, ManagerCreate, ManagerSettingsUpdate


def test_batch_settings_deduplicates_and_trims_selectors():
    payload = AccountBatchSettings(
        selectors=[" 账户甲 ", "账户甲", "", "主体乙"],
        operator_name="王康",
    )

    assert payload.selectors == ["账户甲", "主体乙"]


def test_batch_settings_rejects_unknown_operator():
    with pytest.raises(ValidationError, match="运营只能选择王康或王聪"):
        AccountBatchSettings(selectors=["账户甲"], operator_name="其他人")


def test_batch_settings_rejects_unknown_account_type():
    with pytest.raises(ValidationError):
        AccountBatchSettings(selectors=["账户甲"], account_type="未知类型")


def test_batch_settings_accepts_separate_page_type_and_promotion_page():
    payload = AccountBatchSettings(
        selectors=["账户甲"],
        page_type="科普账户",
        promotion_page="科普基木鱼",
    )

    assert payload.page_type == "科普账户"
    assert payload.promotion_page == "科普基木鱼"


@pytest.mark.parametrize(
    ("field", "value"),
    [("page_type", "其他账户"), ("promotion_page", "其他页面")],
)
def test_batch_settings_rejects_unknown_page_options(field, value):
    with pytest.raises(ValidationError):
        AccountBatchSettings(selectors=["账户甲"], **{field: value})


def test_batch_settings_rejects_invalid_link():
    with pytest.raises(ValidationError, match="推广链接必须以"):
        AccountBatchSettings(selectors=["账户甲"], promotion_link="example.com/page")


def test_batch_settings_rejects_out_of_range_rebate():
    with pytest.raises(ValidationError):
        AccountBatchSettings(selectors=["账户甲"], rebate_rate=101)


def test_manager_accepts_one_shared_rebate_and_recharge_account():
    payload = ManagerCreate(
        login_name=" 管家甲 ",
        rebate_rate="52.5",
        recharge_account=" 钱柜甲 ",
    )

    assert payload.login_name == "管家甲"
    assert payload.rebate_rate == Decimal("52.5")
    assert payload.recharge_account == "钱柜甲"


def test_manager_settings_accept_balance_warning_and_rebate():
    payload = ManagerSettingsUpdate(
        balance_warning_threshold="1000.50",
        rebate_rate="52.5",
    )

    assert payload.balance_warning_threshold == Decimal("1000.50")
    assert payload.rebate_rate == Decimal("52.5")


def test_manager_settings_reject_empty_and_invalid_values():
    with pytest.raises(ValidationError, match="至少提交一项"):
        ManagerSettingsUpdate()
    with pytest.raises(ValidationError):
        ManagerSettingsUpdate(balance_warning_threshold=-1)
    with pytest.raises(ValidationError):
        ManagerSettingsUpdate(rebate_rate=101)


def test_batch_settings_accepts_deduplicated_explicit_account_ids():
    account_id = uuid.uuid4()
    payload = AccountBatchSettings(account_ids=[account_id, account_id], operator_name="王康")

    assert payload.account_ids == [account_id]
    assert payload.selectors == []


def test_batch_settings_requires_exactly_one_selection_method():
    with pytest.raises(ValidationError):
        AccountBatchSettings(operator_name="王康")
    with pytest.raises(ValidationError):
        AccountBatchSettings(selectors=["账户甲"], account_ids=[uuid.uuid4()], operator_name="王康")
