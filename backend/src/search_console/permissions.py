import uuid
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Account, ProjectAdBuildAccess
from .security import Actor, owner_usernames


PermissionLevel = Literal["hidden", "view", "manage"]
DataScope = Literal["self", "team", "project"]

MODULES = (
    "account_management",
    "account_list",
    "auto_launch",
    "reports",
    "finance_reports",
    "member_management",
    "strategies",
)
LEVEL_RANK = {"hidden": 0, "view": 1, "manage": 2}
DEFAULT_MEMBER_PERMISSIONS: dict[str, PermissionLevel] = {
    "account_management": "hidden",
    "account_list": "view",
    "auto_launch": "hidden",
    "reports": "view",
    "finance_reports": "hidden",
    "member_management": "hidden",
    "strategies": "hidden",
}
OWNER_PERMISSIONS: dict[str, PermissionLevel] = {key: "manage" for key in MODULES}


@dataclass(frozen=True)
class ProjectAccess:
    is_owner: bool
    member: ProjectAdBuildAccess | None
    permissions: dict[str, PermissionLevel]
    operator_names: tuple[str, ...] | None

    @property
    def data_scope(self) -> DataScope:
        return "project" if self.is_owner or self.member is None else self.member.data_scope  # type: ignore[return-value]


def is_system_owner(actor: Actor) -> bool:
    return actor.username in owner_usernames()


def normalize_permissions(value: dict | None) -> dict[str, PermissionLevel]:
    source = value if isinstance(value, dict) else {}
    result: dict[str, PermissionLevel] = {}
    for module in MODULES:
        level = source.get(module, DEFAULT_MEMBER_PERMISSIONS[module])
        result[module] = level if level in LEVEL_RANK else DEFAULT_MEMBER_PERMISSIONS[module]
    return result


def ad_build_operator_names(access: ProjectAccess) -> tuple[str, ...] | None:
    """Return the stricter auto-launch scope, independent of general data visibility."""
    if access.is_owner:
        return None
    if access.member is None or not access.member.operator_name:
        return ()
    return (access.member.operator_name,)


def get_project_member(
    db: Session,
    project_id: uuid.UUID,
    username: str,
    *,
    active_only: bool = True,
) -> ProjectAdBuildAccess | None:
    filters = [
        ProjectAdBuildAccess.project_id == project_id,
        ProjectAdBuildAccess.username == username,
    ]
    if active_only:
        filters.append(ProjectAdBuildAccess.is_active.is_(True))
    return db.scalar(select(ProjectAdBuildAccess).where(*filters))


def project_access(db: Session, project_id: uuid.UUID, actor: Actor) -> ProjectAccess:
    if is_system_owner(actor):
        return ProjectAccess(True, None, OWNER_PERMISSIONS.copy(), None)
    member = get_project_member(db, project_id, actor.username)
    if member is None:
        raise HTTPException(status_code=404, detail="项目不存在或没有访问权限")
    permissions = normalize_permissions(member.permissions)
    if member.data_scope == "project":
        operator_names = None
    elif member.data_scope == "team":
        direct_reports = db.scalars(select(ProjectAdBuildAccess).where(
            ProjectAdBuildAccess.project_id == project_id,
            ProjectAdBuildAccess.supervisor_id == member.id,
            ProjectAdBuildAccess.is_active.is_(True),
        )).all()
        operator_names = tuple(dict.fromkeys([
            member.operator_name,
            *(row.operator_name for row in direct_reports),
        ]))
    else:
        operator_names = (member.operator_name,)
    return ProjectAccess(False, member, permissions, operator_names)


def require_project_permission(
    db: Session,
    project_id: uuid.UUID,
    actor: Actor,
    module: str,
    level: PermissionLevel = "view",
) -> ProjectAccess:
    access = project_access(db, project_id, actor)
    actual = access.permissions.get(module, "hidden")
    if LEVEL_RANK.get(actual, 0) < LEVEL_RANK[level]:
        raise HTTPException(status_code=403, detail="当前成员没有该功能权限")
    return access


def require_any_project_permission(
    db: Session,
    project_id: uuid.UUID,
    actor: Actor,
    modules: tuple[str, ...],
    level: PermissionLevel = "view",
) -> ProjectAccess:
    access = project_access(db, project_id, actor)
    if not any(
        LEVEL_RANK.get(access.permissions.get(module, "hidden"), 0) >= LEVEL_RANK[level]
        for module in modules
    ):
        raise HTTPException(status_code=403, detail="当前成员没有该功能权限")
    return access


def require_account_scope(access: ProjectAccess, account: Account) -> None:
    if access.operator_names is not None and account.operator_name not in access.operator_names:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ACCOUNT_SCOPE_DENIED",
                "message": "目标账户不在当前成员的数据范围内",
            },
        )


def access_payload(access: ProjectAccess) -> dict:
    member = access.member
    return {
        "is_system_owner": access.is_owner,
        "member_id": str(member.id) if member else None,
        "permissions": access.permissions,
        "data_scope": access.data_scope,
        "operator_names": list(access.operator_names) if access.operator_names is not None else None,
        "supervisor_id": str(member.supervisor_id) if member and member.supervisor_id else None,
        "version": member.version if member else 1,
    }
