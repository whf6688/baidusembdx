from dataclasses import dataclass

from search_console.ad_build_access import accounts_in_operator_scope, specified_accounts_outside_scope


@dataclass
class AccountStub:
    baidu_account_id: int
    login_name: str
    operator_name: str | None


ACCOUNTS = [
    AccountStub(1001, "wk-account", "王康"),
    AccountStub(1002, "wc-account", "王聪"),
    AccountStub(1003, "unassigned", None),
]


def test_operator_scope_contains_only_own_accounts():
    assert [row.baidu_account_id for row in accounts_in_operator_scope(ACCOUNTS, "王康")] == [1001]
    assert [row.baidu_account_id for row in accounts_in_operator_scope(ACCOUNTS, "王聪")] == [1002]


def test_admin_scope_keeps_all_accounts():
    assert accounts_in_operator_scope(ACCOUNTS, None) == ACCOUNTS


def test_specified_account_cannot_cross_operator_by_login_or_id():
    by_login = specified_accounts_outside_scope(ACCOUNTS, ["wc-account"], "王康")
    by_id = specified_accounts_outside_scope(ACCOUNTS, ["1002"], "王康")
    assert [row.baidu_account_id for row in by_login] == [1002]
    assert [row.baidu_account_id for row in by_id] == [1002]


def test_own_specified_account_is_allowed():
    assert specified_accounts_outside_scope(ACCOUNTS, ["wk-account", "1001"], "王康") == []
