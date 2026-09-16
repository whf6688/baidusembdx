from search_console.permission_middleware import _required_access
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from search_console.permissions import (
    DEFAULT_MEMBER_PERMISSIONS,
    ProjectAccess,
    normalize_permissions,
    require_account_scope,
)


def test_new_member_permissions_are_least_privilege():
    assert normalize_permissions(None) == DEFAULT_MEMBER_PERMISSIONS


def test_ordinary_member_cannot_receive_member_management_manage():
    permissions = normalize_permissions({"member_management": "manage"})
    assert permissions["member_management"] == "view"


def test_invalid_permission_levels_fall_back_to_module_defaults():
    permissions = normalize_permissions({"account_list": "owner", "reports": "write"})
    assert permissions["account_list"] == "view"
    assert permissions["reports"] == "view"


def test_navigation_routes_require_matching_modules():
    assert _required_access("members", "GET") == (("member_management",), "view")
    assert _required_access("members/member-id", "PATCH") == (("member_management",), "manage")
    assert _required_access("account-workspace", "GET") == (("account_list",), "view")
    assert _required_access("reports/account-daily.xlsx", "GET") == (("reports",), "manage")
    assert _required_access("ad-build-access/users", "PATCH") == (("member_management",), "manage")


def test_account_scope_denial_uses_structured_error_code():
    access = ProjectAccess(
        is_owner=False,
        member=None,
        permissions=DEFAULT_MEMBER_PERMISSIONS,
        operator_names=("王康",),
    )
    with pytest.raises(HTTPException) as captured:
        require_account_scope(access, SimpleNamespace(operator_name="王聪"))
    assert captured.value.status_code == 403
    assert captured.value.detail["code"] == "ACCOUNT_SCOPE_DENIED"
