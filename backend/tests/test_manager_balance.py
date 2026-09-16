import uuid
from types import SimpleNamespace

from search_console.models import Account
from search_console.manager_balance import resolve_manager_recharge_account


class ScalarRows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeDB:
    def __init__(self, rows, by_id=None):
        self.rows = rows
        self.by_id = by_id or {}

    def scalars(self, _query):
        return ScalarRows(self.rows)

    def get(self, model, key):
        assert model is Account
        return self.by_id.get(key)


def manager(**overrides):
    values = {
        "id": uuid.uuid4(),
        "financial_settings_mode": "manager_shared",
        "recharge_account": "充值账户01",
        "balance_account_id": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def account(manager_id, name, baidu_id):
    return SimpleNamespace(
        id=uuid.uuid4(),
        manager_id=manager_id,
        login_name=name,
        baidu_account_id=baidu_id,
    )


def test_recharge_account_is_matched_exactly_and_bound():
    row = manager()
    other = account(row.id, "其他账户", 1001)
    recharge = account(row.id, "充值账户01", 1002)
    result = resolve_manager_recharge_account(
        FakeDB([other, recharge]), row, update_binding=True
    )
    assert result is recharge
    assert row.balance_account_id == recharge.id


def test_missing_recharge_account_does_not_fall_back_to_first_child():
    row = manager(recharge_account="不存在的账户", balance_account_id=uuid.uuid4())
    result = resolve_manager_recharge_account(
        FakeDB([account(row.id, "其他账户", 1001)]), row, update_binding=True
    )
    assert result is None
    assert row.balance_account_id is None


def test_legacy_manager_keeps_historical_balance_binding():
    account_id = uuid.uuid4()
    row = manager(
        financial_settings_mode="legacy_per_account",
        balance_account_id=account_id,
        recharge_account=None,
    )
    historical = account(row.id, "历史账户", 1003)
    assert resolve_manager_recharge_account(
        FakeDB([], {account_id: historical}), row, update_binding=True
    ) is historical
