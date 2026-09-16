from datetime import UTC, datetime, timedelta

import pytest

from baidu_platform_core import BaiduCallContext, BaiduPlatformClient, PermissionContextError
from baidu_platform_core.context import WritePolicy
from baidu_platform_core.client import baidu_business_error_message
from baidu_platform_core.errors import RateLimitError
from search_console.worker import rate_limit_retry_seconds


def context(**overrides):
    values = dict(app_code="search", baidu_application_code="shared", manager_login_name="manager", target_account_id=1001, target_login_name="account", request_batch="batch", idempotency_key="idempotent-key")
    values.update(overrides)
    return BaiduCallContext(**values)


def test_search_context_is_valid():
    context().validate(write=True)


def test_rate_limit_delay_uses_actual_retry_value():
    error = RateLimitError(
        "百度接口返回限频",
        retry_after_seconds=7,
        source="baidu_http_429",
    )

    assert error.retry_after_seconds == 7
    assert error.source == "baidu_http_429"
    assert rate_limit_retry_seconds(error) == 7


def test_rate_limit_delay_is_safely_bounded():
    assert rate_limit_retry_seconds(
        RateLimitError("short", retry_after_seconds=0)
    ) == 1
    assert rate_limit_retry_seconds(
        RateLimitError("long", retry_after_seconds=999)
    ) == 300


def test_baidu_business_error_keeps_original_explanation():
    message = baidu_business_error_message({
        "code": 90180007000,
        "message": "推广网址公司与账户公司不一致",
    })

    assert "90180007000" in message
    assert "百度原始说明：推广网址公司与账户公司不一致" in message


def test_baidu_retry_after_header_is_honored():
    response = type("Response", (), {"headers": {"Retry-After": "2.4"}})()

    assert BaiduPlatformClient._baidu_retry_after(response) == 3


def test_write_requires_explicit_target():
    with pytest.raises(PermissionContextError):
        context(target_account_id=0).validate(write=True)


def test_app_code_cannot_create_second_application_identity():
    with pytest.raises(ValueError):
        context(app_code="search-second-app").validate()


def test_shared_client_exposes_audited_read_boundary(monkeypatch):
    audit_calls = []

    class FakeConnection:
        def execute(self, statement, params):
            audit_calls.append(params)

    class FakeTransaction:
        def __enter__(self):
            return FakeConnection()

        def __exit__(self, *_):
            return False

    class FakeEngine:
        def begin(self):
            return FakeTransaction()

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"data": [{"liceName": "测试主体"}]}

        def raise_for_status(self):
            return None

    class FakeHttpClient:
        def __init__(self, **_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def post(self, url, json):
            assert url.endswith("AccountService/getAccountInfo")
            assert json["body"] == {"accountFields": ["userId", "liceName"]}
            return FakeResponse()

    client = BaiduPlatformClient(
        "postgresql+psycopg://unused:unused@localhost/unused",
        "https://api.baidu.com",
        WritePolicy(enabled=False),
        token_decryptor=lambda value: value,
        endpoints={"account.get": "json/sms/service/AccountService/getAccountInfo"},
    )
    client.engine = FakeEngine()
    client.initialize = lambda: None
    client._validate_binding = lambda _: None
    client._reserve_rate_limit = lambda *_: None
    client._token = lambda _: "encrypted-token-is-not-logged"
    monkeypatch.setattr("baidu_platform_core.client.httpx.Client", FakeHttpClient)

    result = client.execute_read(
        context(), "account.get", {"accountFields": ["userId", "liceName"]}
    )

    assert result["data"][0]["liceName"] == "测试主体"
    assert audit_calls[0]["app_code"] == "search"
    assert audit_calls[0]["account"] == 1001


def test_read_retries_baidu_transient_business_error_8001(monkeypatch):
    responses = [
        {"header": {"failures": [{"code": 8001}]}},
        {"header": {"failures": [{"code": 8001}]}},
        {"data": [{"userId": 1001, "budget": 50}]},
    ]
    calls = []

    class FakeConnection:
        def execute(self, _statement, _params):
            return None

    class FakeTransaction:
        def __enter__(self):
            return FakeConnection()

        def __exit__(self, *_):
            return False

    class FakeEngine:
        def begin(self):
            return FakeTransaction()

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

        def raise_for_status(self):
            return None

    class FakeHttpClient:
        def __init__(self, **_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def post(self, _url, json):
            calls.append(json)
            return FakeResponse(responses[len(calls) - 1])

    client = BaiduPlatformClient(
        "postgresql+psycopg://unused:unused@localhost/unused",
        "https://api.baidu.com",
        WritePolicy(enabled=False),
        token_decryptor=lambda value: value,
        endpoints={"account.get": "account/get"},
    )
    client.engine = FakeEngine()
    client.initialize = lambda: None
    client._validate_binding = lambda _: None
    client._reserve_rate_limit = lambda *_: None
    client._token = lambda _: "token"
    monkeypatch.setattr("baidu_platform_core.client.httpx.Client", FakeHttpClient)
    monkeypatch.setattr("baidu_platform_core.client.time.sleep", lambda _: None)

    result = client.execute_read(
        context(), "account.get", {"accountFields": ["userId", "budget"]}
    )

    assert len(calls) == 3
    assert result["data"][0]["budget"] == 50


def test_expired_token_is_refreshed_and_encrypted_under_lock(monkeypatch):
    updates = []
    refresh_payloads = []
    token_row = {
        "id": "token-id",
        "user_id": 72398156,
        "access_token_encrypted": "old-access",
        "refresh_token_encrypted": "old-refresh",
        "expires_at": datetime.now(UTC) - timedelta(minutes=1),
        "refresh_expires_at": datetime.now(UTC) + timedelta(days=10),
    }

    class FakeResult:
        def __init__(self, row=None):
            self.row = row

        def mappings(self):
            return self

        def first(self):
            return self.row

    class FakeConnection:
        def execute(self, statement, params):
            if "SELECT id, user_id" in str(statement):
                return FakeResult(token_row)
            updates.append(params)
            return FakeResult()

    class FakeTransaction:
        def __enter__(self):
            return FakeConnection()

        def __exit__(self, *_):
            return False

    class FakeEngine:
        def begin(self):
            return FakeTransaction()

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "code": 0,
                "data": {
                    "accessToken": "new-access",
                    "refreshToken": "new-refresh",
                    "expiresIn": 86400,
                    "refreshExpiresIn": 2592000,
                },
            }

    class FakeHttpClient:
        def __init__(self, **_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def post(self, url, json):
            assert url == "https://u.baidu.com/oauth/refreshToken"
            refresh_payloads.append(json)
            return FakeResponse()

    client = BaiduPlatformClient(
        "postgresql+psycopg://unused:unused@localhost/unused",
        "https://api.baidu.com",
        WritePolicy(enabled=False),
        token_decryptor=lambda value: f"plain:{value}",
        token_encryptor=lambda value: f"encrypted:{value}",
        oauth_app_id="app-id",
        oauth_app_secret="app-secret",
        oauth_refresh_url="https://u.baidu.com/oauth/refreshToken",
    )
    client.engine = FakeEngine()
    client._audit_token_refresh = lambda *_args, **_kwargs: None
    monkeypatch.setattr("baidu_platform_core.client.httpx.Client", FakeHttpClient)

    token = client._refresh_token(context(), "token-id")

    assert token == "new-access"
    assert refresh_payloads == [
        {
            "appId": "app-id",
            "refreshToken": "plain:old-refresh",
            "secretKey": "app-secret",
            "userId": 72398156,
        }
    ]
    assert updates[0]["access_token"] == "encrypted:new-access"
    assert updates[0]["refresh_token"] == "encrypted:new-refresh"
