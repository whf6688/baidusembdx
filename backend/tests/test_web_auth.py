from types import SimpleNamespace

import bcrypt

from search_console.web_auth import (
    update_system_owner_credential,
    update_web_credential,
    verify_web_credentials,
)


def test_web_credentials_accept_valid_password(tmp_path):
    path = tmp_path / "users.htpasswd"
    password_hash = bcrypt.hashpw(b"a-long-test-password", bcrypt.gensalt()).decode()
    path.write_text(f"admin:{password_hash}\n", encoding="utf-8")
    settings = SimpleNamespace(auth_htpasswd_path=path)

    assert verify_web_credentials(settings, "admin", "a-long-test-password") is True
    assert verify_web_credentials(settings, "admin", "wrong-password") is False
    assert verify_web_credentials(settings, "unknown", "a-long-test-password") is False


def test_web_credentials_fail_when_file_is_missing(tmp_path):
    settings = SimpleNamespace(auth_htpasswd_path=tmp_path / "missing")
    assert verify_web_credentials(settings, "admin", "any-password") is False


def test_web_credential_can_change_login_without_changing_identity(tmp_path):
    path = tmp_path / "users.htpasswd"
    original_hash = bcrypt.hashpw(b"old-password", bcrypt.gensalt()).decode()
    path.write_text(f"old_login:{original_hash}\n", encoding="utf-8")
    settings = SimpleNamespace(auth_htpasswd_path=path)

    update_web_credential(
        path,
        old_username="old_login",
        new_username="new_login",
        password="new-password",
    )

    assert verify_web_credentials(settings, "old_login", "old-password") is False
    assert verify_web_credentials(settings, "new_login", "new-password") is True


def test_system_owner_credential_updates_login_marker_and_password(tmp_path):
    credential_path = tmp_path / "users.htpasswd"
    username_path = tmp_path / "system-owner.username"
    original_hash = bcrypt.hashpw(b"old-password", bcrypt.gensalt()).decode()
    credential_path.write_text(f"owner_login:{original_hash}\nmember:member-hash\n", encoding="utf-8")
    settings = SimpleNamespace(
        auth_htpasswd_path=credential_path,
        system_owner_username_path=username_path,
    )

    update_system_owner_credential(
        settings,
        old_username="owner_login",
        new_username="new_owner",
        password="new-password",
    )

    assert username_path.read_text(encoding="utf-8").strip() == "new_owner"
    assert verify_web_credentials(settings, "owner_login", "old-password") is False
    assert verify_web_credentials(settings, "new_owner", "new-password") is True
    assert "member:member-hash" in credential_path.read_text(encoding="utf-8")
