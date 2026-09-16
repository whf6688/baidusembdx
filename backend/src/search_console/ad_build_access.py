"""Pure helpers for enforcing operator-scoped ad-build account selection."""

from collections.abc import Iterable, Sequence
from typing import Protocol, TypeVar


class OperatorAccount(Protocol):
    baidu_account_id: int
    login_name: str
    operator_name: str | None


AccountT = TypeVar("AccountT", bound=OperatorAccount)


def accounts_in_operator_scope(accounts: Sequence[AccountT], operator_name: str | None) -> list[AccountT]:
    if operator_name is None:
        return list(accounts)
    return [account for account in accounts if account.operator_name == operator_name]


def specified_accounts_outside_scope(
    accounts: Sequence[AccountT],
    selectors: Iterable[str],
    operator_name: str | None,
) -> list[AccountT]:
    if operator_name is None:
        return []
    normalized = {value.strip() for value in selectors if value.strip()}
    return [
        account
        for account in accounts
        if account.operator_name != operator_name
        and (account.login_name in normalized or str(account.baidu_account_id) in normalized)
    ]
