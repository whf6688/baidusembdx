import re
import uuid

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .db import SessionLocal
from .permissions import require_any_project_permission, require_project_permission
from .security import current_actor


PROJECT_PATH = re.compile(r"^/api/v1/projects/([0-9a-fA-F-]{36})(?:/(.*))?$")


def _required_access(suffix: str, method: str) -> tuple[tuple[str, ...], str] | None:
    clean = suffix.strip("/")
    if clean in {"", "access/me"}:
        return None
    if clean.startswith("members"):
        return (("member_management",), "view" if method == "GET" else "manage")
    if clean.startswith("ad-build-access/users"):
        return (("member_management",), "view" if method == "GET" else "manage")
    if clean == "ad-build-access/me":
        return (("auto_launch",), "view")
    if clean == "managers" and method == "GET":
        return (("account_management", "account_list", "auto_launch"), "view")
    if clean.startswith(("account-management", "managers", "account-drafts")):
        return (("account_management",), "view" if method == "GET" else "manage")
    if clean.startswith((
        "account-workspace", "account-selection", "custom-ids", "campaign-settings",
        "campaign-batch", "campaign-cache",
    )):
        if clean == "campaign-settings/current":
            return (("account_list",), "view")
        return (("account_list",), "view" if method == "GET" else "manage")
    if clean.startswith("accounts/"):
        return (("account_list",), "view" if method == "GET" else "manage")
    if clean == "accounts":
        return (("account_management", "account_list", "auto_launch"), "view")
    if clean.startswith(("reports", "tracking")):
        export = clean.endswith((".csv", ".xlsx"))
        return (("reports",), "manage" if method != "GET" or export else "view")
    if clean.startswith("finance"):
        return (("finance_reports",), "view" if method == "GET" else "manage")
    if clean.startswith((
        "materials", "material-keywords", "creative-", "creative-center", "keyword-tier",
        "negative-keywords", "reference-template", "ad-build",
    )):
        return (("auto_launch",), "view" if method == "GET" else "manage")
    if clean.startswith(("strategies", "preferences", "audit-events", "operations-center", "automation")):
        return (("strategies",), "view" if method == "GET" else "manage")
    if clean.startswith(("dashboard", "alerts", "tasks", "notifications")):
        return (
            ("account_management", "account_list", "auto_launch", "reports", "finance_reports", "strategies"),
            "view" if method == "GET" else "manage",
        )
    return None


class ProjectPermissionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        match = PROJECT_PATH.match(request.url.path)
        if not match:
            return await call_next(request)
        requirement = _required_access(match.group(2) or "", request.method.upper())
        if requirement is None:
            return await call_next(request)
        try:
            project_id = uuid.UUID(match.group(1))
            actor = current_actor(
                authorization=request.headers.get("authorization"),
                x_user=request.headers.get("x-user"),
                x_role=request.headers.get("x-role"),
                x_requested_role=request.headers.get("x-requested-role"),
                session_token=request.cookies.get("search_console_session"),
            )
            modules, level = requirement
            with SessionLocal() as db:
                if len(modules) == 1:
                    access = require_project_permission(db, project_id, actor, modules[0], level)
                else:
                    access = require_any_project_permission(db, project_id, actor, modules, level)
                clean_suffix = (match.group(2) or "").strip("/")
                if (
                    request.method.upper() != "GET"
                    and clean_suffix.startswith(("managers", "account-drafts"))
                    and not access.is_owner
                    and access.data_scope != "project"
                ):
                    raise HTTPException(
                        status_code=403,
                        detail="管家授权、同步和账户导入仅允许项目数据范围成员执行",
                    )
        except HTTPException as exc:
            code = "PROJECT_NOT_FOUND" if exc.status_code == 404 else "PERMISSION_DENIED"
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "request_id": getattr(request.state, "request_id", None),
                    "status": "error",
                    "data": None,
                    "error": {"code": code, "message": str(exc.detail)},
                },
            )
        return await call_next(request)
