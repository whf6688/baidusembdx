import base64
import hashlib
import hmac
import os
import threading
from pathlib import Path

import bcrypt
from passlib.hash import apr_md5_crypt
from redis import Redis
from redis.exceptions import RedisError

from .config import Settings


_DUMMY_BCRYPT_HASH = b"$2b$12$C6UzMDM.H6dfI/f/IKcEe.3eSxMK3VEdh/CkZ9buO8pSp9yWAd68q"
_CREDENTIAL_LOCK = threading.Lock()


def _credential_hash(path: Path, username: str) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        saved_username, separator, password_hash = line.partition(":")
        if separator and hmac.compare_digest(saved_username, username):
            return password_hash.strip()
    return None


def _verify_password(password: str, password_hash: str) -> bool:
    if password_hash.startswith(("$2a$", "$2b$", "$2y$")):
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    if password_hash.startswith("$apr1$"):
        return bool(apr_md5_crypt.verify(password, password_hash))
    if password_hash.startswith("{SHA}"):
        digest = base64.b64encode(hashlib.sha1(password.encode()).digest()).decode()
        return hmac.compare_digest(password_hash[5:], digest)
    return False


def verify_web_credentials(settings: Settings, username: str, password: str) -> bool:
    password_hash = _credential_hash(settings.auth_htpasswd_path, username)
    if password_hash is None:
        # Keep unknown users close to the cost of a real password check.
        bcrypt.checkpw(password.encode(), _DUMMY_BCRYPT_HASH)
        return False
    try:
        return _verify_password(password, password_hash)
    except (ValueError, TypeError):
        return False


def _credential_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []


def _write_credential_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def _write_private_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def update_web_credential(
    path: Path,
    *,
    old_username: str | None,
    new_username: str,
    password: str | None,
) -> None:
    """Rename a login and/or replace its password without exposing the hash."""
    with _CREDENTIAL_LOCK:
        lines = _credential_lines(path)
        entries = {
            username: password_hash
            for line in lines
            for username, separator, password_hash in [line.partition(":")]
            if separator
        }
        old_hash = entries.get(old_username or "")
        if password is None and old_hash is None:
            raise KeyError("credential_missing")
        if old_username:
            entries.pop(old_username, None)
        entries.pop(new_username, None)
        entries[new_username] = (
            bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
            if password is not None
            else old_hash
        )
        _write_credential_lines(path, [f"{username}:{password_hash}" for username, password_hash in entries.items()])


def update_system_owner_credential(
    settings: Settings,
    *,
    old_username: str,
    new_username: str,
    password: str | None,
) -> None:
    """Update the fixed owner's login while keeping its identity and permissions immutable."""
    credential_path = settings.auth_htpasswd_path
    username_path = settings.system_owner_username_path
    with _CREDENTIAL_LOCK:
        original_lines = _credential_lines(credential_path)
        entries = {
            username: password_hash
            for line in original_lines
            for username, separator, password_hash in [line.partition(":")]
            if separator
        }
        if new_username != old_username and new_username in entries:
            raise ValueError("credential_exists")
        old_hash = entries.get(old_username)
        if old_hash is None:
            raise KeyError("credential_missing")
        entries.pop(old_username, None)
        entries[new_username] = (
            bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
            if password is not None
            else old_hash
        )
        _write_credential_lines(
            credential_path,
            [f"{username}:{password_hash}" for username, password_hash in entries.items()],
        )
        try:
            _write_private_text(username_path, f"{new_username}\n")
        except OSError:
            _write_credential_lines(credential_path, original_lines)
            raise


def _attempt_key(client_ip: str, username: str) -> str:
    identity = hashlib.sha256(f"{client_ip}\0{username.lower()}".encode()).hexdigest()
    return f"search-console:login-attempts:{identity}"


def login_is_rate_limited(settings: Settings, client_ip: str, username: str) -> bool:
    try:
        redis = Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
        current = redis.get(_attempt_key(client_ip, username))
        return current is not None and int(current) >= settings.auth_login_max_attempts
    except (RedisError, ValueError):
        return False


def record_login_failure(settings: Settings, client_ip: str, username: str) -> None:
    try:
        redis = Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
        key = _attempt_key(client_ip, username)
        count = redis.incr(key)
        if count == 1:
            redis.expire(key, settings.auth_login_window_seconds)
    except RedisError:
        return


def clear_login_failures(settings: Settings, client_ip: str, username: str) -> None:
    try:
        Redis.from_url(
            settings.redis_url, socket_connect_timeout=1, socket_timeout=1
        ).delete(_attempt_key(client_ip, username))
    except RedisError:
        return
