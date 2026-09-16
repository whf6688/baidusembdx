from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from baidu_platform_core import BaiduCallContext, FernetTokenCipher

from .account_lifecycle import EMPTY
from .config import Settings, get_settings
from .db import get_db
from .manager_archive import archive_manager
from .manager_balance import refresh_manager_recharge_balance, resolve_manager_recharge_account
from .models import Account, AccountManager, AccountType, AuditEvent, Project, Role
from .schemas import ManagerStatusUpdate
from .security import Actor, require_roles


management_router = APIRouter(prefix="/api/v1", tags=["Baidu OAuth"])
callback_router = APIRouter(prefix="/api/baidu/oauth", tags=["Baidu OAuth"])


def oauth_signature(secret_key: str, params: dict[str, str]) -> str:
    ordered_json = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    source = base64.b64encode(ordered_json.encode("utf-8"))
    padded_length = ((len(source) + 15) // 16) * 16
    padded = source.ljust(padded_length, b"\0")
    encryptor = Cipher(
        algorithms.AES(secret_key[:16].encode("utf-8")),
        modes.CBC(bytes(16)),
    ).encryptor()
    return (encryptor.update(padded) + encryptor.finalize()).hex().upper()


def verify_callback_signature(secret_key: str, params: dict[str, str], signature: str) -> bool:
    expected = oauth_signature(secret_key, params)
    return hmac.compare_digest(expected, signature.upper())


def state_digest(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def require_oauth_configuration(settings: Settings, *, require_scope: bool = False) -> None:
    required = [
        ("BAIDU_APP_ID", settings.baidu_app_id),
        ("BAIDU_APP_SECRET", settings.baidu_app_secret),
        ("BAIDU_OAUTH_CALLBACK_URL", settings.baidu_oauth_callback_url),
        ("PLATFORM_TOKEN_ENCRYPTION_KEY", settings.platform_token_encryption_key),
    ]
    if require_scope:
        required.append(("BAIDU_OAUTH_SCOPE", settings.baidu_oauth_scope))
    missing = [
        name
        for name, value in required
        if not value
    ]
    if missing:
        raise HTTPException(status_code=503, detail=f"OAuth 配置缺失：{', '.join(missing)}")


def build_authorization_url(settings: Settings, state: str) -> str:
    query = urlencode(
        {
            "platformId": settings.baidu_oauth_platform_id,
            "appId": settings.baidu_app_id,
            "scope": settings.baidu_oauth_scope,
            "state": state,
            "callback": settings.baidu_oauth_callback_url,
        }
    )
    return f"{settings.baidu_oauth_authorize_url}?{query}"


def post_oauth_json(url: str, payload: dict) -> dict:
    try:
        response = httpx.post(url, json=payload, timeout=httpx.Timeout(20, connect=5))
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="百度 OAuth 服务暂时不可用") from exc
    if result.get("code") != 0 or not isinstance(result.get("data"), dict):
        message = str(result.get("message") or "百度 OAuth 返回失败")
        raise HTTPException(status_code=400, detail=message)
    return result["data"]


def fetch_all_authorized_accounts(
    settings: Settings,
    *,
    open_id: str,
    access_token: str,
    user_id: int,
) -> dict:
    """Read every child account returned by the authorized manager.

    Baidu paginates the OAuth user-info child list by the largest ucId from the
    previous page. Keep this in the authorization boundary so callers never
    handle or log plaintext tokens.
    """

    marker = 1
    first_page: dict | None = None
    accounts_by_id: dict[int, dict] = {}
    for _ in range(200):
        page = post_oauth_json(
            settings.baidu_oauth_user_info_url,
            {
                "openId": open_id,
                "accessToken": access_token,
                "userId": user_id,
                "needSubList": True,
                "pageSize": 500,
                "lastPageMaxUcId": marker,
            },
        )
        if first_page is None:
            first_page = dict(page)
        page_accounts = list(page.get("subUserList") or [])
        page_ids: list[int] = []
        for item in page_accounts:
            try:
                account_id = int(item["ucId"])
            except (KeyError, TypeError, ValueError):
                continue
            page_ids.append(account_id)
            accounts_by_id[account_id] = {
                "ucId": account_id,
                "ucName": str(item.get("ucName") or account_id),
            }
        if not page.get("hasNext"):
            break
        next_marker = max(page_ids, default=marker)
        if next_marker <= marker:
            raise HTTPException(status_code=502, detail="百度子账户分页游标异常，已停止同步")
        marker = next_marker
    else:
        raise HTTPException(status_code=502, detail="百度子账户分页超过安全上限，已停止同步")

    result = first_page or {}
    result["subUserList"] = list(accounts_by_id.values())
    return result


def normalize_mcc_service_accounts(result: dict) -> list[dict]:
    """Convert the dedicated MCC account-list response to OAuth list fields."""

    data = result.get("data")
    if not isinstance(data, list):
        body = result.get("body")
        data = body.get("data") if isinstance(body, dict) else []
    accounts_by_id: dict[int, dict] = {}
    for item in data if isinstance(data, list) else []:
        try:
            account_id = int(item["userid"])
        except (KeyError, TypeError, ValueError):
            continue
        accounts_by_id[account_id] = {
            "ucId": account_id,
            "ucName": str(item.get("username") or account_id),
        }
    return list(accounts_by_id.values())


def merge_authorized_accounts(*account_lists: list[dict]) -> list[dict]:
    """Merge account sources without allowing a partial source to remove rows."""

    accounts_by_id: dict[int, dict] = {}
    for rows in account_lists:
        for item in rows:
            try:
                account_id = int(item["ucId"])
            except (KeyError, TypeError, ValueError):
                continue
            accounts_by_id[account_id] = {
                "ucId": account_id,
                "ucName": str(item.get("ucName") or account_id),
            }
    return list(accounts_by_id.values())


def sync_project_accounts(
    db: Session,
    *,
    settings: Settings,
    project_id: uuid.UUID,
    manager: AccountManager,
    manager_name: str,
    user_info: dict,
    authorized_account_ids: set[int] | None = None,
) -> dict[str, int]:
    if manager.auth_status == "archived" or manager.is_active is False:
        raise HTTPException(status_code=409, detail="账户管家已移除归档，禁止重新同步账户")
    account_type = int(user_info.get("userAcctType") or 1)
    sub_accounts = list(user_info.get("subUserList") or [])
    if account_type not in (2, 4) and not sub_accounts:
        sub_accounts = [{"ucId": manager.baidu_user_id, "ucName": manager_name}]

    returned_ids: set[int] = set()
    created = 0
    updated = 0
    conflicts = 0
    authorization_pending = 0
    now = datetime.now(UTC)
    for item in sub_accounts:
        try:
            target_id = int(item["ucId"])
        except (KeyError, TypeError, ValueError):
            continue
        target_name = str(item.get("ucName") or target_id)
        permission_status = (
            "granted"
            if authorized_account_ids is None or target_id in authorized_account_ids
            else "pending_oauth"
        )
        if permission_status != "granted":
            authorization_pending += 1
        returned_ids.add(target_id)
        db.execute(
            text(
                """
                INSERT INTO platform_core.account_bindings(
                    baidu_application_code, manager_login_name, target_account_id,
                    target_login_name, permission_status
                ) VALUES (:application, :manager, :target_id, :target_name, :permission_status)
                ON CONFLICT (baidu_application_code, target_account_id) DO UPDATE SET
                    manager_login_name=excluded.manager_login_name,
                    target_login_name=excluded.target_login_name,
                    permission_status=excluded.permission_status
                """
            ),
            {
                "application": settings.baidu_application_code,
                "manager": manager_name,
                "target_id": target_id,
                "target_name": target_name,
                "permission_status": permission_status,
            },
        )
        account = db.scalar(select(Account).where(Account.baidu_account_id == target_id))
        if account and account.project_id != project_id:
            conflicts += 1
            continue
        if account is None:
            account = Account(
                project_id=project_id,
                manager_id=manager.id,
                baidu_account_id=target_id,
                login_name=target_name,
                manager_login_name=manager_name,
                account_type=AccountType.SECOND_HOP,
                lifecycle_stage=EMPTY,
                active_keyword_count=0,
                lifecycle_evaluated_at=now,
                balance=0,
                rebate_rate=(
                    manager.rebate_rate
                    if manager.financial_settings_mode != "legacy_per_account"
                    else None
                ),
                recharge_account=(
                    manager.recharge_account
                    if manager.financial_settings_mode != "legacy_per_account"
                    else None
                ),
                permission_status=permission_status,
                is_active=True,
                last_synced_at=now,
            )
            db.add(account)
            created += 1
        else:
            account.manager_id = manager.id
            account.login_name = target_name
            account.manager_login_name = manager_name
            account.permission_status = permission_status
            if manager.financial_settings_mode != "legacy_per_account":
                account.rebate_rate = manager.rebate_rate
                account.recharge_account = manager.recharge_account
            account.is_active = True
            account.last_synced_at = now
            updated += 1

    deactivated = 0
    existing_rows = db.scalars(
        select(Account).where(Account.project_id == project_id, Account.manager_id == manager.id)
    ).all()
    for account in existing_rows:
        if account.baidu_account_id not in returned_ids and account.is_active:
            account.is_active = False
            account.permission_status = "revoked"
            account.last_synced_at = now
            deactivated += 1

    db.flush()
    resolve_manager_recharge_account(db, manager, update_binding=True)

    manager.login_name = manager_name
    manager.auth_status = "authorized"
    manager.last_synced_at = now
    return {
        "account_count": len(returned_ids) - conflicts,
        "created_count": created,
        "updated_count": updated,
        "deactivated_count": deactivated,
        "conflict_count": conflicts,
        "authorization_pending_count": authorization_pending,
    }


def expiry_from_response(data: dict, absolute_key: str, seconds_key: str) -> datetime:
    seconds = data.get(seconds_key)
    if seconds is not None:
        try:
            return datetime.now(UTC) + timedelta(seconds=max(0, int(seconds)))
        except (TypeError, ValueError):
            pass
    raw = str(data.get(absolute_key) or "")
    for pattern in ("%Y%m%d%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(raw, pattern).replace(tzinfo=UTC)
        except ValueError:
            continue
    return datetime.now(UTC)


@management_router.get("/oauth/baidu/configuration")
def oauth_configuration(
    request: Request,
    _: Actor = Depends(require_roles(Role.ADMIN)),
    settings: Settings = Depends(get_settings),
):
    return {
        "request_id": request.state.request_id,
        "status": "ok",
        "data": {
            "app_id": settings.baidu_app_id,
            "callback_url": settings.baidu_oauth_callback_url,
            "scope_configured": bool(settings.baidu_oauth_scope),
            "isolated_authorization_center": True,
            "writes_enabled": settings.baidu_writes_enabled,
        },
    }


@management_router.post("/projects/{project_id}/managers/{manager_id}/oauth/start")
def start_oauth(
    project_id: uuid.UUID,
    manager_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN)),
    settings: Settings = Depends(get_settings),
):
    require_oauth_configuration(settings, require_scope=True)
    project = db.get(Project, project_id)
    manager = db.get(AccountManager, manager_id)
    if not project or not manager or manager.project_id != project_id:
        raise HTTPException(status_code=404, detail="项目或账户管家不存在")

    if manager.auth_status == "archived" or manager.is_active is False:
        raise HTTPException(status_code=409, detail="账户管家已移除归档，不能授权或同步")

    route = "local" if settings.app_env == "local" else "cloud"
    state = f"search-{route}.{secrets.token_urlsafe(32)}"
    context = json.dumps(
        {
            "project_id": str(project_id),
            "manager_id": str(manager_id),
            "manager_login_name": manager.login_name,
            "created_by": actor.username,
        },
        ensure_ascii=False,
    )
    db.execute(
        text(
            """
            INSERT INTO platform_core.oauth_states(state_hash, context, expires_at)
            VALUES (:state_hash, CAST(:context AS jsonb), :expires_at)
            """
        ),
        {
            "state_hash": state_digest(state),
            "context": context,
            "expires_at": datetime.now(UTC) + timedelta(minutes=10),
        },
    )
    manager.auth_status = "oauth_started"
    db.commit()
    return {
        "request_id": request.state.request_id,
        "status": "ok",
        "data": {"authorization_url": build_authorization_url(settings, state), "expires_in": 600},
    }


@management_router.post("/projects/{project_id}/accounts/{account_id}/oauth/start")
def start_account_oauth(
    project_id: uuid.UUID,
    account_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
    settings: Settings = Depends(get_settings),
):
    """Start an OAuth grant for one child account without re-syncing its manager."""
    require_oauth_configuration(settings, require_scope=True)
    account = db.scalar(select(Account).where(
        Account.id == account_id,
        Account.project_id == project_id,
        Account.is_active.is_(True),
    ))
    if account is None or account.manager_id is None:
        raise HTTPException(status_code=404, detail="当前项目中不存在该账户或账户未绑定管家")
    manager = db.get(AccountManager, account.manager_id)
    if manager is None or manager.is_active is False or manager.auth_status == "archived":
        raise HTTPException(status_code=409, detail="账户所属管家已归档，不能继续授权")

    route = "local" if settings.app_env == "local" else "cloud"
    state = f"search-account-{route}.{secrets.token_urlsafe(32)}"
    context = json.dumps({
        "authorization_type": "account",
        "project_id": str(project_id),
        "manager_id": str(manager.id),
        "manager_login_name": manager.login_name,
        "account_id": str(account.id),
        "target_account_id": account.baidu_account_id,
        "target_login_name": account.login_name,
        "created_by": actor.username,
    }, ensure_ascii=False)
    db.execute(text("""
        INSERT INTO platform_core.oauth_states(state_hash, context, expires_at)
        VALUES (:state_hash, CAST(:context AS jsonb), :expires_at)
    """), {
        "state_hash": state_digest(state),
        "context": context,
        "expires_at": datetime.now(UTC) + timedelta(minutes=10),
    })
    account.permission_status = "oauth_started"
    db.commit()
    return {
        "request_id": request.state.request_id,
        "status": "ok",
        "data": {"authorization_url": build_authorization_url(settings, state), "expires_in": 600},
    }


@management_router.post("/projects/{project_id}/managers/{manager_id}/accounts/sync")
def sync_manager_accounts(
    project_id: uuid.UUID,
    manager_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
    settings: Settings = Depends(get_settings),
):
    require_oauth_configuration(settings)
    project = db.get(Project, project_id)
    manager = db.get(AccountManager, manager_id)
    if not project or not manager or manager.project_id != project_id:
        raise HTTPException(status_code=404, detail="项目或账户管家不存在")

    if manager.auth_status == "archived" or manager.is_active is False:
        raise HTTPException(status_code=409, detail="账户管家已移除归档，不能授权或同步")
    if not manager.baidu_user_id or manager.auth_status not in {"authorized", "granted"}:
        raise HTTPException(status_code=409, detail="账户管家尚未完成百度 OAuth 授权")

    token_row = db.execute(
        text(
            """
            SELECT open_id, access_token_encrypted, expires_at
            FROM platform_core.authorization_tokens
            WHERE baidu_application_code=:application
              AND owner_type IN ('manager', 'mcc')
              AND (owner_id=:owner_id OR login_name=:login_name)
            ORDER BY updated_at DESC
            LIMIT 1
            """
        ),
        {
            "application": settings.baidu_application_code,
            "owner_id": str(manager.baidu_user_id),
            "login_name": manager.login_name,
        },
    ).mappings().first()
    if not token_row:
        raise HTTPException(status_code=409, detail="公共授权中心没有该管家的 Token，请重新授权")
    if token_row["expires_at"] <= datetime.now(UTC) + timedelta(minutes=2):
        raise HTTPException(status_code=409, detail="管家 Token 已过期，请重新授权")

    cipher = FernetTokenCipher(settings.platform_token_encryption_key)
    user_info = fetch_all_authorized_accounts(
        settings,
        open_id=str(token_row["open_id"] or ""),
        access_token=cipher.decrypt(token_row["access_token_encrypted"]),
        user_id=manager.baidu_user_id,
    )
    oauth_accounts = list(user_info.get("subUserList") or [])
    authorized_account_ids = {
        int(item["ucId"])
        for item in oauth_accounts
        if item.get("ucId") is not None
    }
    manager_name = str(user_info.get("masterName") or manager.login_name)
    account_source = "oauth_user_info"
    context_account = db.scalar(
        select(Account)
        .where(Account.manager_id == manager.id, Account.is_active.is_(True))
        .order_by(Account.baidu_account_id)
    )
    if context_account is not None:
        context_account_id = context_account.baidu_account_id
        context_login_name = context_account.login_name
        # Release the token/account-binding read transaction before the shared
        # runtime initializes and reserves its audited API lease.
        db.commit()
        try:
            from .worker import platform_client

            mcc_result = platform_client().execute_read(
                BaiduCallContext(
                    app_code="search",
                    baidu_application_code=settings.baidu_application_code,
                    manager_login_name=manager_name,
                    target_account_id=context_account_id,
                    target_login_name=context_login_name,
                    request_batch=f"manager-account-sync:{manager.id}",
                    idempotency_key=uuid.uuid4().hex,
                ),
                "mcc.accounts.get",
                {},
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="百度账户管家专用账户列表读取失败，本次未修改账户数据，请稍后重试",
            ) from exc
        mcc_accounts = normalize_mcc_service_accounts(mcc_result)
        if not mcc_accounts:
            raise HTTPException(
                status_code=502,
                detail="百度账户管家专用接口未返回账户，本次未修改账户数据",
            )
        user_info["subUserList"] = merge_authorized_accounts(
            oauth_accounts,
            mcc_accounts,
        )
        account_source = "oauth_user_info+mcc_service"
    result = sync_project_accounts(
        db,
        settings=settings,
        project_id=project_id,
        manager=manager,
        manager_name=manager_name,
        user_info=user_info,
        authorized_account_ids=authorized_account_ids,
    )
    result["account_source"] = account_source
    db.add(
        AuditEvent(
            project_id=project_id,
            actor=actor.username,
            action="manager.accounts.sync",
            target_type="account_manager",
            target_id=str(manager.id),
            summary="从账户管家同步下辖账户",
            details=result,
        )
    )
    db.commit()
    try:
        balance = refresh_manager_recharge_balance(
            db,
            manager,
            request_batch=f"manager-balance-refresh:{manager.id}",
        )
        result["balance_refresh"] = {"status": "succeeded", **balance}
        db.add(
            AuditEvent(
                project_id=project_id,
                actor=actor.username,
                action="manager.balance.refresh",
                target_type="account_manager",
                target_id=str(manager.id),
                summary="读取充值账户余额",
                details=balance,
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        result["balance_refresh"] = {
            "status": "failed",
            "message": str(exc)[:300],
        }
    return {"request_id": request.state.request_id, "status": "ok", "data": result}


@management_router.post("/projects/{project_id}/managers/{manager_id}/balance/refresh")
def refresh_manager_balance(
    project_id: uuid.UUID,
    manager_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    manager = db.scalar(
        select(AccountManager)
        .where(AccountManager.id == manager_id)
        .with_for_update()
    )
    if not manager or manager.project_id != project_id:
        raise HTTPException(status_code=404, detail="项目或账户管家不存在")
    if manager.auth_status == "archived" or manager.is_active is False:
        raise HTTPException(status_code=409, detail="账户管家已删除归档，不能刷新余额")
    if manager.auth_status not in {"authorized", "granted"}:
        raise HTTPException(status_code=409, detail="账户管家尚未完成百度 OAuth 授权")

    # Release the manager row lock before the shared client reserves its own
    # database-backed rate-limit and audit records.
    db.commit()
    try:
        result = refresh_manager_recharge_balance(
            db,
            manager,
            request_batch=f"manager-balance-manual:{manager.id}",
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail="百度充值账户余额读取失败，请稍后重试") from exc
    db.add(
        AuditEvent(
            project_id=project_id,
            actor=actor.username,
            action="manager.balance.refresh",
            target_type="account_manager",
            target_id=str(manager.id),
            summary="手动读取充值账户余额",
            details=result,
        )
    )
    db.commit()
    return {"request_id": request.state.request_id, "status": "ok", "data": result}


@management_router.post("/projects/{project_id}/managers/{manager_id}/archive")
def archive_project_manager(
    project_id: uuid.UUID,
    manager_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
    settings: Settings = Depends(get_settings),
):
    manager = db.scalar(
        select(AccountManager)
        .where(AccountManager.id == manager_id)
        .with_for_update()
    )
    if not manager or manager.project_id != project_id:
        raise HTTPException(status_code=404, detail="项目或账户管家不存在")
    result = archive_manager(
        db,
        manager=manager,
        application_code=settings.baidu_application_code,
        actor=actor.username,
    )
    db.commit()
    return {"request_id": request.state.request_id, "status": "ok", "data": result}


@management_router.post("/projects/{project_id}/managers/{manager_id}/status")
def update_project_manager_status(
    project_id: uuid.UUID,
    manager_id: uuid.UUID,
    payload: ManagerStatusUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    """Pause or resume a manager without removing accounts, tokens, or history."""

    manager = db.scalar(
        select(AccountManager)
        .where(AccountManager.id == manager_id)
        .with_for_update()
    )
    if not manager or manager.project_id != project_id:
        raise HTTPException(status_code=404, detail="项目或账户管家不存在")
    if manager.auth_status == "archived":
        raise HTTPException(status_code=409, detail="账户管家已删除归档，不能停用或恢复")

    changed = manager.is_active != payload.is_active
    manager.is_active = payload.is_active
    account_count = db.scalar(
        select(func.count()).select_from(Account).where(Account.manager_id == manager.id)
    ) or 0
    summary = "恢复使用账户管家" if payload.is_active else "停用账户管家，保留下辖账户、授权和历史数据"
    db.add(
        AuditEvent(
            project_id=project_id,
            actor=actor.username,
            action="manager.resume" if payload.is_active else "manager.pause",
            target_type="account_manager",
            target_id=str(manager.id),
            summary=summary,
            details={
                "is_active": payload.is_active,
                "changed": changed,
                "account_count": account_count,
                "accounts_preserved": True,
                "authorization_preserved": True,
                "historical_data_preserved": True,
            },
        )
    )
    db.commit()
    return {
        "request_id": request.state.request_id,
        "status": "ok",
        "data": {
            "manager_id": str(manager.id),
            "is_active": manager.is_active,
            "changed": changed,
            "account_count": account_count,
            "accounts_preserved": True,
            "authorization_preserved": True,
            "historical_data_preserved": True,
        },
    }


@management_router.post("/projects/{project_id}/managers/{manager_id}/accounts/subjects/sync")
def queue_account_subject_sync(
    project_id: uuid.UUID,
    manager_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
):
    raise HTTPException(status_code=409, detail="当前项目已停用逐账户主体同步；每个账户管家按同一主体管理")


@callback_router.get("/callback")
def oauth_callback(
    request: Request,
    app_id: str = Query(alias="appId"),
    auth_code: str = Query(alias="authCode"),
    user_id: str = Query(alias="userId"),
    timestamp: str = Query(),
    signature: str = Query(),
    state: str = Query(),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    require_oauth_configuration(settings)
    if not hmac.compare_digest(app_id, settings.baidu_app_id):
        raise HTTPException(status_code=400, detail="回调应用不匹配")
    try:
        timestamp_ms = int(timestamp)
        numeric_user_id = int(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="回调参数格式错误") from exc
    if abs(int(time.time() * 1000) - timestamp_ms) > 10 * 60 * 1000:
        raise HTTPException(status_code=400, detail="回调时间戳已过期")

    signed_params = {
        "appId": app_id,
        "authCode": auth_code,
        "state": state,
        "timestamp": timestamp,
        "userId": user_id,
    }
    if not verify_callback_signature(settings.baidu_app_secret, signed_params, signature):
        raise HTTPException(status_code=400, detail="回调签名校验失败")

    state_row = db.execute(
        text(
            """
            SELECT context, expires_at, consumed_at
            FROM platform_core.oauth_states
            WHERE state_hash=:state_hash
            FOR UPDATE
            """
        ),
        {"state_hash": state_digest(state)},
    ).mappings().first()
    if not state_row or state_row["consumed_at"] is not None:
        raise HTTPException(status_code=400, detail="OAuth state 无效或已使用")
    if state_row["expires_at"] <= datetime.now(UTC):
        raise HTTPException(status_code=400, detail="OAuth state 已过期")

    archived_manager = db.get(AccountManager, uuid.UUID(state_row["context"]["manager_id"]))
    if not archived_manager or archived_manager.auth_status == "archived" or archived_manager.is_active is False:
        raise HTTPException(status_code=409, detail="账户管家已移除归档，禁止继续授权")

    token_data = post_oauth_json(
        settings.baidu_oauth_access_token_url,
        {
            "appId": settings.baidu_app_id,
            "authCode": auth_code,
            "secretKey": settings.baidu_app_secret,
            "grantType": "auth_code",
            "userId": numeric_user_id,
        },
    )
    access_token = str(token_data.get("accessToken") or "")
    refresh_token = str(token_data.get("refreshToken") or "")
    open_id = str(token_data.get("openId") or "")
    if not access_token or not refresh_token:
        raise HTTPException(status_code=502, detail="百度未返回完整授权令牌")

    context = state_row["context"]
    is_account_authorization = context.get("authorization_type") == "account"
    if is_account_authorization and numeric_user_id != int(context["target_account_id"]):
        raise HTTPException(status_code=409, detail="授权登录账户与所选账户不一致，请使用所选百度账户登录")
    user_info = fetch_all_authorized_accounts(
        settings,
        open_id=open_id,
        access_token=access_token,
        user_id=numeric_user_id,
    )
    manager_name = str(
        context.get("target_login_name") if is_account_authorization
        else user_info.get("masterName") or context.get("manager_login_name") or ""
    )
    account_type = int(user_info.get("userAcctType") or 1)
    owner_type = "account" if is_account_authorization else ("manager" if account_type in (2, 4) else "account")
    cipher = FernetTokenCipher(settings.platform_token_encryption_key)

    db.execute(
        text(
            """
            INSERT INTO platform_core.authorization_tokens(
                id, baidu_application_code, owner_type, owner_id, login_name,
                user_id, open_id, access_token_encrypted, refresh_token_encrypted,
                expires_at, refresh_expires_at
            ) VALUES (
                :id, :application, :owner_type, :owner_id, :login_name,
                :user_id, :open_id, :access_token, :refresh_token,
                :expires_at, :refresh_expires_at
            )
            ON CONFLICT (baidu_application_code, owner_type, owner_id) DO UPDATE SET
                login_name=excluded.login_name,
                user_id=excluded.user_id,
                open_id=excluded.open_id,
                access_token_encrypted=excluded.access_token_encrypted,
                refresh_token_encrypted=excluded.refresh_token_encrypted,
                expires_at=excluded.expires_at,
                refresh_expires_at=excluded.refresh_expires_at,
                updated_at=now()
            """
        ),
        {
            "id": uuid.uuid4(),
            "application": settings.baidu_application_code,
            "owner_type": owner_type,
            "owner_id": str(numeric_user_id),
            "login_name": manager_name,
            "user_id": numeric_user_id,
            "open_id": open_id,
            "access_token": cipher.encrypt(access_token),
            "refresh_token": cipher.encrypt(refresh_token),
            "expires_at": expiry_from_response(token_data, "expiresTime", "expiresIn"),
            "refresh_expires_at": expiry_from_response(
                token_data, "refreshExpiresTime", "refreshExpiresIn"
            ),
        },
    )

    manager = db.get(AccountManager, uuid.UUID(context["manager_id"]))
    if not manager or manager.project_id != uuid.UUID(context["project_id"]):
        raise HTTPException(status_code=409, detail="授权对应的账户管家已不存在")
    if is_account_authorization:
        account = db.get(Account, uuid.UUID(context["account_id"]))
        if not account or account.project_id != manager.project_id or account.manager_id != manager.id:
            raise HTTPException(status_code=409, detail="授权对应的账户已不存在或已变更管家")
        account.permission_status = "granted"
        account.last_synced_at = datetime.now(UTC)
        db.execute(text("""
            UPDATE platform_core.account_bindings
            SET permission_status='granted', target_login_name=:login_name
            WHERE baidu_application_code=:application AND target_account_id=:target_id
        """), {
            "application": settings.baidu_application_code,
            "target_id": account.baidu_account_id,
            "login_name": account.login_name,
        })
        db.add(AuditEvent(
            project_id=manager.project_id,
            actor=str(context.get("created_by") or "oauth-callback"),
            action="account.oauth.authorized",
            target_type="account",
            target_id=str(account.id),
            summary="完成单账户百度 OAuth 授权",
            details={"baidu_account_id": account.baidu_account_id},
        ))
        db.execute(
            text("UPDATE platform_core.oauth_states SET consumed_at=now() WHERE state_hash=:state_hash"),
            {"state_hash": state_digest(state)},
        )
        db.commit()
        destination = (
            f"{settings.frontend_base_url.rstrip('/')}"
            f"/?page=accounts&oauth=success&account_authorized=1"
            f"&project_id={manager.project_id}&oauth_window=1"
        )
        return RedirectResponse(destination, status_code=303)
    manager.baidu_user_id = numeric_user_id
    sync_result = sync_project_accounts(
        db,
        settings=settings,
        project_id=manager.project_id,
        manager=manager,
        manager_name=manager_name,
        user_info=user_info,
    )
    db.add(
        AuditEvent(
            project_id=manager.project_id,
            actor=str(context.get("created_by") or "oauth-callback"),
            action="manager.oauth.authorized",
            target_type="account_manager",
            target_id=str(manager.id),
            summary="完成百度 OAuth 授权并同步下辖账户",
            details=sync_result,
        )
    )
    db.execute(
        text("UPDATE platform_core.oauth_states SET consumed_at=now() WHERE state_hash=:state_hash"),
        {"state_hash": state_digest(state)},
    )
    db.commit()
    balance_status = "succeeded"
    try:
        balance = refresh_manager_recharge_balance(
            db,
            manager,
            request_batch=f"manager-balance-oauth:{manager.id}",
        )
        db.add(
            AuditEvent(
                project_id=manager.project_id,
                actor=str(context.get("created_by") or "oauth-callback"),
                action="manager.balance.refresh",
                target_type="account_manager",
                target_id=str(manager.id),
                summary="授权完成后读取充值账户余额",
                details=balance,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        balance_status = "failed"
    destination = (
        f"{settings.frontend_base_url.rstrip('/')}"
        f"/?page=accounts&oauth=success&accounts={sync_result['account_count']}"
        f"&project_id={manager.project_id}&balance={balance_status}&oauth_window=1"
    )
    return RedirectResponse(destination, status_code=303)
