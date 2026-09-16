import base64
import binascii
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass

from fastapi import Cookie, Depends, Header, HTTPException

from .config import get_settings
from .models import Role


@dataclass(frozen=True)
class Actor:
    username: str
    role: Role


SESSION_COOKIE_NAME = "search_console_session"
_LOGIN_USERNAME = re.compile(r"^[A-Za-z0-9._@-]{1,100}$")


def system_owner_username() -> str:
    settings = get_settings()
    path = getattr(settings, "system_owner_username_path", None)
    if path:
        try:
            saved = path.read_text(encoding="utf-8").strip()
            if _LOGIN_USERNAME.fullmatch(saved):
                return saved
        except OSError:
            pass
    return getattr(settings, "system_owner_username", "admin").strip()


def owner_usernames() -> set[str]:
    configured = system_owner_username()
    return {name for name in {configured, "local-admin"} if name}


def current_actor(
    authorization: str | None = Header(default=None),
    x_user: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
    x_requested_role: str | None = Header(default=None),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> Actor:
    settings = get_settings()
    if getattr(settings, "web_login_enabled", False):
        if not session_token:
            raise HTTPException(
                status_code=401,
                detail={"code": "AUTHENTICATION_REQUIRED", "message": "请先登录"},
            )
        verified = verify_access_token(session_token, settings.app_secret)
        return Actor(
            username=verified.username,
            role=Role.ADMIN if verified.username in owner_usernames() else Role.OPERATOR,
        )
    if settings.app_env != "local":
        if settings.trust_proxy_auth and x_user:
            if x_user in owner_usernames():
                return Actor(username=x_user, role=Role.ADMIN)
            return Actor(username=x_user, role=Role.OPERATOR)
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="需要登录")
        verified = verify_access_token(authorization.removeprefix("Bearer ").strip(), settings.app_secret)
        return Actor(
            username=verified.username,
            role=Role.ADMIN if verified.username in owner_usernames() else Role.OPERATOR,
        )
    local_user = x_user or "local-admin"
    if local_user in owner_usernames():
        return Actor(username=local_user, role=Role.ADMIN)
    return Actor(username=local_user, role=Role.OPERATOR)


def create_access_token(username: str, role: Role, secret: str, ttl_seconds: int) -> str:
    payload = {
        "sub": username,
        "role": role.value,
        "exp": int(time.time()) + ttl_seconds,
    }
    encoded_payload = base64.urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).decode().rstrip("=")
    signature = hmac.new(secret.encode(), encoded_payload.encode(), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{encoded_payload}.{encoded_signature}"


def verify_access_token(token: str, secret: str) -> Actor:
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        expected = hmac.new(secret.encode(), encoded_payload.encode(), hashlib.sha256).digest()
        signature = base64.urlsafe_b64decode(encoded_signature + "==")
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        payload = json.loads(base64.urlsafe_b64decode(encoded_payload + "=="))
        if int(payload["exp"]) <= int(time.time()):
            raise ValueError("expired")
        return Actor(username=str(payload["sub"]), role=Role(payload["role"]))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, binascii.Error) as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "SESSION_EXPIRED", "message": "登录已失效，请重新登录"},
        ) from exc


def require_roles(*allowed: Role):
    def dependency(actor: Actor = Depends(current_actor)) -> Actor:
        if actor.role not in allowed:
            raise HTTPException(status_code=403, detail="当前角色没有执行此操作的权限")
        return actor

    return dependency
