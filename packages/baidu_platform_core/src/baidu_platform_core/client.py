import json
import math
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import create_engine, text

from .context import BaiduCallContext, WritePolicy
from .errors import PermissionContextError, RateLimitError, TokenUnavailableError, WriteDisabledError
from .schema import ensure_platform_schema


TRANSIENT_READ_BUSINESS_ERROR_CODES = {"8001"}


def baidu_business_error_message(failure: dict[str, Any]) -> str:
    """Keep Baidu's own explanation visible instead of exposing only a code."""

    code = str(failure.get("code") or "unknown")
    explanations: list[str] = []
    for key in ("message", "description", "reason", "detail", "failMessage"):
        value = failure.get(key)
        if value is not None and str(value).strip():
            text_value = str(value).strip()
            if text_value not in explanations:
                explanations.append(text_value)
    message = f"百度返回业务错误：{code}"
    if explanations:
        message += "；百度原始说明：" + "；".join(explanations)
    return message


class BaiduPlatformClient:
    """Shared, audited Baidu API boundary.

    Tokens remain encrypted in PostgreSQL. A deployment must inject a token decryptor;
    this package deliberately has no fallback to environment or project-local tokens.
    """

    def __init__(
        self,
        database_url: str,
        base_url: str,
        write_policy: WritePolicy,
        token_decryptor=None,
        token_encryptor=None,
        oauth_app_id: str = "",
        oauth_app_secret: str = "",
        oauth_refresh_url: str = "",
        endpoints: dict[str, str] | None = None,
        write_timeout_seconds: float = 20,
    ):
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.base_url = base_url.rstrip("/")
        self.write_policy = write_policy
        self.token_decryptor = token_decryptor
        self.token_encryptor = token_encryptor
        self.oauth_app_id = oauth_app_id
        self.oauth_app_secret = oauth_app_secret
        self.oauth_refresh_url = oauth_refresh_url
        self.endpoints = endpoints or {}
        self.write_timeout_seconds = max(20.0, float(write_timeout_seconds))
        self._initialized = False

    def initialize(self) -> None:
        if not self._initialized:
            ensure_platform_schema(self.engine)
            self._initialized = True

    def _validate_binding(self, context: BaiduCallContext) -> None:
        with self.engine.connect() as connection:
            row = connection.execute(text("""
                SELECT target_login_name, permission_status
                FROM platform_core.account_bindings
                WHERE baidu_application_code=:application AND target_account_id=:account
                  AND manager_login_name=:manager
            """), {"application": context.baidu_application_code, "account": context.target_account_id, "manager": context.manager_login_name}).mappings().first()
        if not row or row["target_login_name"] != context.target_login_name or row["permission_status"] != "granted":
            raise PermissionContextError("目标子账户归属或权限预检未通过")

    def _reserve_rate_limit(self, context: BaiduCallContext, service: str, limit_per_minute: int = 120) -> None:
        bucket = f"{context.baidu_application_code}:{service}"
        with self.engine.begin() as connection:
            # Serialize the sliding-window reservation for this Baidu service.
            # This keeps multiple workers/projects from racing past the shared
            # application quota while still allowing immediate calls whenever
            # a real lease is available.
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:bucket))"),
                {"bucket": bucket},
            )
            lease_window = connection.execute(text("""
                SELECT count(*) AS lease_count, min(lease_at) AS oldest_lease_at
                FROM platform_core.rate_limit_leases
                WHERE bucket_key=:bucket AND lease_at > now() - interval '1 minute'
            """), {"bucket": bucket}).mappings().one()
            if int(lease_window["lease_count"] or 0) >= limit_per_minute:
                oldest = lease_window["oldest_lease_at"]
                retry_after = 1
                if oldest is not None:
                    retry_after = max(
                        1,
                        math.ceil(
                            ((oldest + timedelta(minutes=1)) - datetime.now(UTC)).total_seconds()
                        ),
                    )
                raise RateLimitError(
                    "共享百度应用当前接口限频已满",
                    retry_after_seconds=retry_after,
                    source="local_sliding_window",
                )
            connection.execute(text("""
                INSERT INTO platform_core.rate_limit_leases(bucket_key, app_code, request_batch)
                VALUES (:bucket, :app_code, :batch)
            """), {"bucket": bucket, "app_code": context.app_code, "batch": context.request_batch})

    @staticmethod
    def _baidu_retry_after(response: httpx.Response) -> int:
        raw = response.headers.get("Retry-After")
        try:
            return max(1, math.ceil(float(raw))) if raw else 1
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _expiry_from_response(
        data: dict, absolute_key: str, seconds_key: str
    ) -> datetime:
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

    def _audit_token_refresh(
        self,
        context: BaiduCallContext,
        *,
        status_code: int | None,
        elapsed_ms: int,
        status: str,
    ) -> None:
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO platform_core.api_audit(
                            app_code, baidu_application_code,
                            manager_login_name, service, status_code,
                            elapsed_ms, request_batch, result_summary
                        ) VALUES (
                            :app_code, :application, :manager, 'oauth.refresh',
                            :status_code, :elapsed, :batch,
                            CAST(:result AS jsonb)
                        )
                        """
                    ),
                    {
                        "app_code": context.app_code,
                        "application": context.baidu_application_code,
                        "manager": context.manager_login_name,
                        "status_code": status_code,
                        "elapsed": elapsed_ms,
                        "batch": context.request_batch,
                        "result": json.dumps({"status": status}),
                    },
                )
        except Exception:
            # Refresh availability must not depend on an auxiliary audit insert.
            pass

    def _refresh_token(self, context: BaiduCallContext, token_id: Any) -> str:
        if not all(
            (
                self.token_encryptor,
                self.oauth_app_id,
                self.oauth_app_secret,
                self.oauth_refresh_url,
            )
        ):
            raise TokenUnavailableError(
                "公共授权中心 Token 已过期且未配置自动刷新"
            )

        started = time.perf_counter()
        status_code: int | None = None
        try:
            with self.engine.begin() as connection:
                # This row lock serializes refreshes across API/worker processes.
                # A waiting process rechecks expiry and reuses the new token.
                row = connection.execute(
                    text(
                        """
                        SELECT id, user_id, access_token_encrypted,
                               refresh_token_encrypted, expires_at,
                               refresh_expires_at
                        FROM platform_core.authorization_tokens
                        WHERE id=:token_id
                        FOR UPDATE
                        """
                    ),
                    {"token_id": token_id},
                ).mappings().first()
                if not row:
                    raise TokenUnavailableError("公共授权中心没有可用的管家 Token")
                if row["expires_at"] > datetime.now(UTC) + timedelta(minutes=2):
                    return self.token_decryptor(row["access_token_encrypted"])
                if (
                    row["refresh_expires_at"] is not None
                    and row["refresh_expires_at"] <= datetime.now(UTC)
                ):
                    raise TokenUnavailableError(
                        "刷新 Token 已过期，请重新授权账户管家"
                    )

                refresh_token = self.token_decryptor(
                    row["refresh_token_encrypted"]
                )
                payload = {
                    "appId": self.oauth_app_id,
                    "refreshToken": refresh_token,
                    "secretKey": self.oauth_app_secret,
                    "userId": int(row["user_id"]),
                }
                with httpx.Client(timeout=httpx.Timeout(20, connect=5)) as client:
                    response = client.post(self.oauth_refresh_url, json=payload)
                    status_code = response.status_code
                    response.raise_for_status()
                    result = response.json()
                data = result.get("data")
                if result.get("code") != 0 or not isinstance(data, dict):
                    message = str(result.get("message") or "百度返回失败")
                    raise TokenUnavailableError(
                        f"百度 OAuth Token 刷新失败：{message}"
                    )
                access_token = str(data.get("accessToken") or "")
                next_refresh_token = str(data.get("refreshToken") or "")
                if not access_token or not next_refresh_token:
                    raise TokenUnavailableError("百度 OAuth 未返回完整刷新令牌")

                expires_at = self._expiry_from_response(
                    data, "expiresTime", "expiresIn"
                )
                refresh_expires_at = row["refresh_expires_at"]
                if data.get("refreshExpiresIn") is not None or data.get(
                    "refreshExpiresTime"
                ):
                    refresh_expires_at = self._expiry_from_response(
                        data, "refreshExpiresTime", "refreshExpiresIn"
                    )
                connection.execute(
                    text(
                        """
                        UPDATE platform_core.authorization_tokens
                        SET access_token_encrypted=:access_token,
                            refresh_token_encrypted=:refresh_token,
                            expires_at=:expires_at,
                            refresh_expires_at=:refresh_expires_at,
                            updated_at=now()
                        WHERE id=:token_id
                        """
                    ),
                    {
                        "token_id": token_id,
                        "access_token": self.token_encryptor(access_token),
                        "refresh_token": self.token_encryptor(
                            next_refresh_token
                        ),
                        "expires_at": expires_at,
                        "refresh_expires_at": refresh_expires_at,
                    },
                )
            self._audit_token_refresh(
                context,
                status_code=status_code,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                status="succeeded",
            )
            return access_token
        except TokenUnavailableError:
            self._audit_token_refresh(
                context,
                status_code=status_code,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                status="failed",
            )
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            self._audit_token_refresh(
                context,
                status_code=status_code,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                status="failed",
            )
            raise TokenUnavailableError(
                "百度 OAuth Token 刷新服务暂时不可用"
            ) from exc

    def _token(self, context: BaiduCallContext) -> str:
        if not self.token_decryptor:
            raise TokenUnavailableError("未配置公共授权中心 Token 解密器，禁止降级读取本地 Token")
        with self.engine.connect() as connection:
            row = connection.execute(text("""
                SELECT id, access_token_encrypted, expires_at
                FROM platform_core.authorization_tokens
                WHERE baidu_application_code=:application
                  AND (
                    (owner_type='account' AND (owner_id=:target_id OR login_name=:target_name))
                    OR
                    (owner_type IN ('manager', 'mcc') AND (owner_id=:owner OR login_name=:owner))
                  )
                ORDER BY CASE WHEN owner_type='account' THEN 0 ELSE 1 END, updated_at DESC
                LIMIT 1
            """), {
                "application": context.baidu_application_code,
                "owner": context.manager_login_name,
                "target_id": str(context.target_account_id),
                "target_name": context.target_login_name,
            }).mappings().first()
        if not row:
            raise TokenUnavailableError("公共授权中心没有可用的管家 Token")
        if row["expires_at"] > datetime.now(UTC) + timedelta(minutes=2):
            return self.token_decryptor(row["access_token_encrypted"])
        return self._refresh_token(context, row["id"])

    def _idempotency_start(self, context: BaiduCallContext, service: str) -> dict | None:
        with self.engine.begin() as connection:
            existing = connection.execute(text("SELECT status, result_summary FROM platform_core.idempotency_records WHERE idempotency_key=:key"), {"key": context.idempotency_key}).mappings().first()
            if existing and existing["status"] == "succeeded":
                return existing["result_summary"]
            if not existing:
                connection.execute(text("""
                    INSERT INTO platform_core.idempotency_records(idempotency_key, app_code, target_account_id, service, status)
                    VALUES (:key, :app_code, :account, :service, 'running')
                """), {"key": context.idempotency_key, "app_code": context.app_code, "account": context.target_account_id, "service": service})
        return None

    def execute_write(self, context: BaiduCallContext, service: str, payload: dict[str, Any]) -> dict[str, Any]:
        context.validate(write=True)
        if not self.write_policy.enabled:
            raise WriteDisabledError("百度真实写操作处于关闭状态")
        self.initialize()
        self._validate_binding(context)
        prior = self._idempotency_start(context, service)
        if prior:
            return prior
        endpoint = self.endpoints.get(service)
        if not endpoint:
            raise ValueError(f"未在公共运行时注册接口：{service}")
        self._reserve_rate_limit(context, service)
        token = self._token(context)
        started = time.perf_counter()
        status_code = None
        error_code = None
        result: dict[str, Any] = {}
        try:
            with httpx.Client(
                timeout=httpx.Timeout(self.write_timeout_seconds, connect=5)
            ) as client:
                request_body = {
                    "header": {"userName": context.target_login_name, "accessToken": token},
                    "body": payload,
                }
                response = client.post(f"{self.base_url}/{endpoint.lstrip('/')}", json=request_body)
                status_code = response.status_code
                if response.status_code == 429:
                    raise RateLimitError(
                        "百度接口返回限频",
                        retry_after_seconds=self._baidu_retry_after(response),
                        source="baidu_http_429",
                    )
                response.raise_for_status()
                result = response.json()
                failures = result.get("header", {}).get("failures") or []
                if failures:
                    error_code = str(failures[0].get("code"))
                    # Baidu batch writes may return successful rows together
                    # with item-level failures. Preserve that response so the
                    # business executor can checkpoint successes and handle
                    # only the rejected items. A zero-success response remains
                    # a failed write and is never treated as partial success.
                    if int(result.get("header", {}).get("succ") or 0) <= 0:
                        raise RuntimeError(baidu_business_error_message(failures[0]))
            with self.engine.begin() as connection:
                connection.execute(text("UPDATE platform_core.idempotency_records SET status='succeeded', result_summary=CAST(:result AS jsonb), updated_at=now() WHERE idempotency_key=:key"), {"result": json.dumps(result, ensure_ascii=False), "key": context.idempotency_key})
            return result
        finally:
            elapsed = int((time.perf_counter() - started) * 1000)
            with self.engine.begin() as connection:
                connection.execute(text("""
                    INSERT INTO platform_core.api_audit(app_code, baidu_application_code, manager_login_name, target_account_id, target_login_name, service, status_code, baidu_error_code, elapsed_ms, request_batch, idempotency_key, result_summary)
                    VALUES (:app_code,:application,:manager,:account,:login,:service,:status,:error,:elapsed,:batch,:key,CAST(:result AS jsonb))
                """), {"app_code": context.app_code, "application": context.baidu_application_code, "manager": context.manager_login_name, "account": context.target_account_id, "login": context.target_login_name, "service": service, "status": status_code, "error": error_code, "elapsed": elapsed, "batch": context.request_batch, "key": context.idempotency_key, "result": json.dumps(result, ensure_ascii=False) if result else None})

    def execute_read(self, context: BaiduCallContext, service: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute a target-account read through shared permission, rate-limit and audit controls."""
        context.validate(write=False)
        self.initialize()
        self._validate_binding(context)
        endpoint = self.endpoints.get(service)
        if not endpoint:
            raise ValueError(f"未在公共运行时注册接口：{service}")
        self._reserve_rate_limit(context, service)
        token = self._token(context)
        started = time.perf_counter()
        status_code = None
        error_code = None
        result: dict[str, Any] = {}
        try:
            request_body = {
                "header": {"userName": context.target_login_name, "accessToken": token},
                "body": payload,
            }
            for attempt in range(3):
                error_code = None
                try:
                    with httpx.Client(timeout=httpx.Timeout(20, connect=5)) as client:
                        response = client.post(f"{self.base_url}/{endpoint.lstrip('/')}", json=request_body)
                        status_code = response.status_code
                        if response.status_code == 429:
                            raise RateLimitError(
                                "百度接口返回限频",
                                retry_after_seconds=self._baidu_retry_after(response),
                                source="baidu_http_429",
                            )
                        if response.status_code >= 500:
                            response.raise_for_status()
                        result = response.json()
                        response.raise_for_status()
                    failures = result.get("header", {}).get("failures") or []
                    if failures:
                        error_code = str(failures[0].get("code"))
                        if (
                            error_code in TRANSIENT_READ_BUSINESS_ERROR_CODES
                            and attempt < 2
                        ):
                            time.sleep(attempt + 1)
                            continue
                        raise RuntimeError(baidu_business_error_message(failures[0]))
                    break
                except (httpx.TransportError, httpx.HTTPStatusError):
                    if attempt == 2:
                        raise
                    time.sleep(attempt + 1)
            return result
        finally:
            elapsed = int((time.perf_counter() - started) * 1000)
            with self.engine.begin() as connection:
                connection.execute(text("""
                    INSERT INTO platform_core.api_audit(app_code, baidu_application_code, manager_login_name, target_account_id, target_login_name, service, status_code, baidu_error_code, elapsed_ms, request_batch, idempotency_key, result_summary)
                    VALUES (:app_code,:application,:manager,:account,:login,:service,:status,:error,:elapsed,:batch,NULL,CAST(:result AS jsonb))
                """), {"app_code": context.app_code, "application": context.baidu_application_code, "manager": context.manager_login_name, "account": context.target_account_id, "login": context.target_login_name, "service": service, "status": status_code, "error": error_code, "elapsed": elapsed, "batch": context.request_batch, "result": json.dumps(result, ensure_ascii=False) if result else None})

    def verify_write(self, context: BaiduCallContext, result: dict[str, Any]) -> dict[str, Any]:
        context.validate(write=True)
        identifiers = result.get("data") or result.get("body") or result
        return {"status": "requires_registered_readback", "identifiers": identifiers}
