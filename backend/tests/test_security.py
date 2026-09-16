from types import SimpleNamespace

from search_console.models import Role
from search_console import security


def production_settings():
    return SimpleNamespace(
        app_env="production",
        trust_proxy_auth=True,
        web_login_enabled=False,
        app_secret="unused",
    )


def actor(monkeypatch, username: str, requested_role: str | None = None):
    monkeypatch.setattr(security, "get_settings", production_settings)
    return security.current_actor(
        authorization=None,
        x_user=username,
        x_role="operator",
        x_requested_role=requested_role,
        session_token=None,
    )


def test_admin_login_is_always_admin(monkeypatch):
    result = actor(monkeypatch, "admin", "operator")
    assert result.username == "admin"
    assert result.role == Role.ADMIN


def test_wang_kang_is_an_operator(monkeypatch):
    assert actor(monkeypatch, "wang_kang").role == Role.OPERATOR
    assert actor(monkeypatch, "wang_kang", "admin").role == Role.OPERATOR


def test_wang_cong_is_an_operator_even_when_admin_requested(monkeypatch):
    result = actor(monkeypatch, "wang_cong", "admin")
    assert result.username == "wang_cong"
    assert result.role == Role.OPERATOR


def test_signed_session_round_trip():
    token = security.create_access_token("wang_kang", Role.OPERATOR, "test-secret", 60)
    result = security.verify_access_token(token, "test-secret")
    assert result.username == "wang_kang"
    assert result.role == Role.OPERATOR


def test_signed_session_rejects_modified_payload():
    token = security.create_access_token("wang_kang", Role.OPERATOR, "test-secret", 60)
    encoded, signature = token.split(".", 1)
    changed = ("A" if encoded[0] != "A" else "B") + encoded[1:]
    try:
        security.verify_access_token(f"{changed}.{signature}", "test-secret")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 401
    else:
        raise AssertionError("modified session token was accepted")
