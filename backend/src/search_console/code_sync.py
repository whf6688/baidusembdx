"""Safe Git synchronization for this search project's own repository."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from .config import Settings, get_settings
from .models import BackgroundTask, TaskStatus


TASK_TYPE = "code_sync"
SHANGHAI = ZoneInfo("Asia/Shanghai")
_SECRET_PATTERNS = (
    re.compile(r"(https?://)[^/@\s]+@", re.IGNORECASE),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
)
_RETRYABLE_NETWORK_MARKERS = (
    "could not connect",
    "could not resolve host",
    "connection refused",
    "connection reset",
    "failed to connect",
    "network is unreachable",
    "remote end hung up",
    "temporary failure",
    "timed out",
    "timeout",
    "tls",
)
_FORBIDDEN_PARTS = {
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "playwright-report",
    "test-results",
}
_FORBIDDEN_ROOTS = {"data", "storage", "logs", "backups", "cache", "tmp"}
_FORBIDDEN_SUFFIXES = {
    ".db",
    ".db3",
    ".duckdb",
    ".key",
    ".log",
    ".pem",
    ".sqlite",
    ".sqlite3",
    ".token",
}


@dataclass(slots=True)
class GitResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def output(self) -> str:
        return "\n".join(value for value in (self.stdout, self.stderr) if value).strip()


def _sanitize(value: str) -> str:
    text = value or ""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(r"\1***@" if pattern is _SECRET_PATTERNS[0] else "***", text)
    return text.rstrip("\r\n")


def _ssh_command(settings: Settings) -> str | None:
    if not settings.code_sync_ssh_key_path.is_file():
        return None
    parts = [
        "ssh",
        "-i",
        str(settings.code_sync_ssh_key_path),
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "BatchMode=yes",
    ]
    if settings.code_sync_known_hosts_path.is_file():
        parts.extend(["-o", f"UserKnownHostsFile={settings.code_sync_known_hosts_path}"])
    else:
        parts.extend(["-o", "StrictHostKeyChecking=yes"])
    return " ".join(shlex.quote(part) for part in parts)


def run_git(
    args: list[str],
    *,
    settings: Settings | None = None,
    timeout: int = 180,
) -> GitResult:
    config = settings or get_settings()
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    ssh_command = _ssh_command(config)
    if ssh_command:
        environment["GIT_SSH_COMMAND"] = ssh_command
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=config.code_sync_repository_path,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=creationflags,
            check=False,
        )
        return GitResult(
            completed.returncode,
            _sanitize(completed.stdout),
            _sanitize(completed.stderr),
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return GitResult(124, _sanitize(output), f"Git 操作超过 {timeout} 秒未完成")
    except OSError as exc:
        return GitResult(127, "", _sanitize(str(exc)))


def normalize_repository_url(value: str) -> str:
    text = (value or "").strip().removesuffix("/").removesuffix(".git")
    if text.startswith("git@github.com:"):
        text = "https://github.com/" + text.removeprefix("git@github.com:")
    return text.casefold()


def repository_url_is_allowed(value: str, settings: Settings | None = None) -> bool:
    config = settings or get_settings()
    expected = {
        normalize_repository_url(config.code_sync_repository_https_url),
        normalize_repository_url(config.code_sync_repository_ssh_url),
    }
    return normalize_repository_url(value) in expected


def _split_null_paths(value: str) -> list[str]:
    return [part.replace("\\", "/") for part in value.split("\0") if part]


def _parse_status_paths(value: str) -> list[str]:
    records = value.split("\0")
    paths: list[str] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if len(record) < 4:
            continue
        code = record[:2]
        paths.append(record[3:].replace("\\", "/"))
        if "R" in code or "C" in code:
            index += 1
    return paths


def path_is_forbidden(path_text: str) -> bool:
    normalized = path_text.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")
    lowered = normalized.casefold()
    path = Path(lowered)
    if lowered.startswith(".env") or normalized == "=":
        return True
    if path.parts and path.parts[0] in _FORBIDDEN_ROOTS:
        return True
    if any(part in _FORBIDDEN_PARTS for part in path.parts):
        return True
    if path.suffix in _FORBIDDEN_SUFFIXES:
        return True
    name = path.name
    return any(marker in name for marker in ("secret", "credential", "access_token", "private_key"))


def _daily_parts(settings: Settings) -> tuple[int, int]:
    try:
        hour_text, minute_text = settings.code_sync_daily_time.split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    except (TypeError, ValueError):
        pass
    return 2, 0


def next_code_sync_run(now: datetime | None = None, settings: Settings | None = None) -> datetime:
    config = settings or get_settings()
    current = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    hour, minute = _daily_parts(config)
    scheduled = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if current >= scheduled:
        scheduled += timedelta(days=1)
    return scheduled


def repository_snapshot(settings: Settings | None = None) -> dict[str, Any]:
    config = settings or get_settings()
    base = {
        "available": False,
        "repository": "whf6688/baidusembdx",
        "repository_url": config.code_sync_repository_https_url,
        "branch": "",
        "remote": config.code_sync_remote,
        "remote_url": "",
        "remote_verified": False,
        "target_branch": config.code_sync_branch,
        "head": "",
        "last_commit_message": "",
        "dirty_count": 0,
        "syncable_count": 0,
        "excluded_count": 0,
        "ahead_count": 0,
        "behind_count": 0,
    }
    if not config.code_sync_repository_path.is_dir():
        return {**base, "availability_error": "搜索项目代码目录不存在"}
    if not (config.code_sync_repository_path / ".git").exists():
        return {**base, "availability_error": "搜索项目仓库尚未初始化"}

    branch = run_git(["branch", "--show-current"], settings=config)
    remote_url = run_git(["remote", "get-url", config.code_sync_remote], settings=config)
    head = run_git(["rev-parse", "--short", "HEAD"], settings=config)
    log = run_git(["log", "-1", "--format=%s"], settings=config)
    status = run_git(["status", "--porcelain", "-z", "--untracked-files=normal"], settings=config)
    if branch.returncode != 0 or remote_url.returncode != 0 or status.returncode != 0:
        detail = branch.output or remote_url.output or status.output or "无法读取仓库状态"
        return {**base, "availability_error": detail}

    paths = _parse_status_paths(status.stdout)
    syncable = [path for path in paths if not path_is_forbidden(path)]
    excluded = [path for path in paths if path_is_forbidden(path)]
    ahead_count = 0
    behind_count = 0
    remote_ref = run_git(
        ["show-ref", "--verify", "--quiet", f"refs/remotes/{config.code_sync_remote}/{config.code_sync_branch}"],
        settings=config,
    )
    if remote_ref.returncode == 0:
        counts = run_git(
            ["rev-list", "--left-right", "--count", f"{config.code_sync_remote}/{config.code_sync_branch}...HEAD"],
            settings=config,
        )
        if counts.returncode == 0:
            values = counts.stdout.split()
            if len(values) == 2:
                behind_count, ahead_count = (int(value) for value in values)
    return {
        **base,
        "available": True,
        "branch": branch.stdout,
        "remote_url": remote_url.stdout,
        "remote_verified": repository_url_is_allowed(remote_url.stdout, config),
        "head": head.stdout if head.returncode == 0 else "",
        "last_commit_message": log.stdout if log.returncode == 0 else "",
        "dirty_count": len(paths),
        "syncable_count": len(syncable),
        "excluded_count": len(excluded),
        "ahead_count": ahead_count,
        "behind_count": behind_count,
    }


def ensure_repository_initialized(settings: Settings) -> None:
    repository = settings.code_sync_repository_path
    repository.mkdir(parents=True, exist_ok=True)
    if (repository / ".git").exists():
        return
    if any(repository.iterdir()):
        raise RuntimeError("代码同步目录不是空目录且尚未初始化，已停止以避免覆盖文件")
    initialized = run_git(["init", "-b", settings.code_sync_branch], settings=settings)
    if initialized.returncode != 0:
        raise RuntimeError(initialized.output or "初始化搜索项目仓库失败")
    added = run_git(
        ["remote", "add", settings.code_sync_remote, settings.code_sync_repository_ssh_url],
        settings=settings,
    )
    if added.returncode != 0:
        raise RuntimeError(added.output or "配置搜索项目 GitHub 远端失败")


def _task_result(task: BackgroundTask) -> dict[str, Any]:
    return dict(task.result) if isinstance(task.result, dict) else {}


def update_task(
    db: Session,
    task: BackgroundTask,
    *,
    status: TaskStatus | None = None,
    node: str | None = None,
    progress: int | None = None,
    last_error: str | None = None,
    **result_updates: Any,
) -> None:
    result = _task_result(task)
    result.update(result_updates)
    task.result = result
    flag_modified(task, "result")
    if status is not None:
        task.status = status
    if node is not None:
        task.current_node = node
    if progress is not None:
        task.progress = progress
    task.last_error = _sanitize(last_error or "") or None
    task.heartbeat_at = datetime.now(UTC)
    db.commit()


def _is_retryable(result: GitResult) -> bool:
    output = result.output.casefold()
    return any(marker in output for marker in _RETRYABLE_NETWORK_MARKERS)


def _conflict_files(settings: Settings) -> list[str]:
    result = run_git(["diff", "--name-only", "--diff-filter=U", "-z"], settings=settings)
    return _split_null_paths(result.stdout) if result.returncode == 0 else []


def _commit_message(paths: list[str]) -> str:
    categories: list[str] = []
    mappings = (
        ("前端界面", ("frontend/",)),
        ("后台服务", ("backend/", "packages/")),
        ("部署配置", ("deploy/", "docker-compose.yml", ".gitignore", ".env.example")),
        ("文档", ("docs/", "readme")),
    )
    lowered = [path.casefold() for path in paths]
    for label, prefixes in mappings:
        if any(any(path.startswith(prefix.casefold()) for prefix in prefixes) for path in lowered):
            categories.append(label)
    return f"更新：同步{'、'.join(categories[:3] or ['百度搜索投放平台代码'])}"


def _remote_branch_exists(settings: Settings) -> tuple[bool, GitResult]:
    result = run_git(
        ["ls-remote", "--exit-code", "--heads", settings.code_sync_remote, settings.code_sync_branch],
        settings=settings,
        timeout=120,
    )
    if result.returncode == 0:
        return True, result
    if result.returncode == 2 and not result.output:
        return False, result
    return False, result


def execute_code_sync(db: Session, task: BackgroundTask, settings: Settings | None = None) -> dict[str, Any]:
    config = settings or get_settings()
    update_task(
        db,
        task,
        status=TaskStatus.RUNNING,
        node="inspect_repository",
        progress=5,
        sync_status="running",
        summary="正在检查搜索项目代码变更。",
        started_at=datetime.now(UTC).isoformat(),
    )
    try:
        ensure_repository_initialized(config)
        snapshot = repository_snapshot(config)
        if not snapshot["available"]:
            raise RuntimeError(str(snapshot.get("availability_error") or "搜索项目仓库不可用"))
        if not snapshot["remote_verified"]:
            raise RuntimeError("仓库远端不是搜索项目 whf6688/baidusembdx，已停止同步")
        if snapshot["branch"] != config.code_sync_branch:
            raise RuntimeError(
                f"当前分支为 {snapshot['branch'] or '未知'}，目标分支为 {config.code_sync_branch}，已停止同步"
            )

        status_result = run_git(["status", "--porcelain", "-z", "--untracked-files=normal"], settings=config)
        if status_result.returncode != 0:
            raise RuntimeError(status_result.output or "无法读取代码变更")
        changed_paths = _parse_status_paths(status_result.stdout)
        blocked_paths = [path for path in changed_paths if path_is_forbidden(path)]
        syncable_paths = [path for path in changed_paths if not path_is_forbidden(path)]
        commit_hash = snapshot.get("head") or None
        commit_message = None

        if syncable_paths:
            update_task(db, task, node="commit_changes", progress=25, summary="正在提交本地代码变更。")
            exclusions = [f":(exclude,literal){path.rstrip('/')}" for path in blocked_paths]
            added = run_git(["add", "-A", "--", ".", *exclusions], settings=config)
            if added.returncode != 0:
                raise RuntimeError(added.output or "暂存代码变更失败")
            staged = run_git(["diff", "--cached", "--name-only", "-z"], settings=config)
            staged_paths = _split_null_paths(staged.stdout) if staged.returncode == 0 else []
            if any(path_is_forbidden(path) for path in staged_paths):
                raise RuntimeError("暂存区包含不应同步的密钥或运行数据，已停止且未提交")
            if staged_paths:
                commit_message = _commit_message(staged_paths)
                committed = run_git(
                    [
                        "-c",
                        "user.name=baidu-search-sync",
                        "-c",
                        "user.email=baidu-search-sync@users.noreply.github.com",
                        "commit",
                        "-m",
                        commit_message,
                    ],
                    settings=config,
                    timeout=300,
                )
                if committed.returncode != 0:
                    raise RuntimeError(committed.output or "提交本地修改失败")
                commit = run_git(["rev-parse", "--short", "HEAD"], settings=config)
                commit_hash = commit.stdout if commit.returncode == 0 else None
                changed_paths = staged_paths

        remote_exists, remote_probe = _remote_branch_exists(config)
        if remote_probe.returncode not in (0, 2):
            raise RuntimeError(remote_probe.output or "无法检查远程 main 分支")
        if not changed_paths and int(snapshot.get("ahead_count") or 0) == 0 and remote_exists:
            update_task(
                db,
                task,
                status=TaskStatus.SUCCEEDED,
                node="completed",
                progress=100,
                sync_status="no_changes",
                summary=(
                    "没有需要同步的代码变更。"
                    + (f" 已跳过 {len(blocked_paths)} 个密钥或运行数据文件。" if blocked_paths else "")
                ),
                last_commit=commit_hash,
                last_commit_message=commit_message,
                changed_files=[],
                skipped_files=blocked_paths[:100],
                finished_at=datetime.now(UTC).isoformat(),
            )
            return _task_result(task)

        if remote_exists:
            update_task(db, task, node="pull_remote", progress=55, summary="正在拉取 GitHub main。")
            pulled = run_git(
                ["pull", "--no-rebase", config.code_sync_remote, config.code_sync_branch],
                settings=config,
                timeout=300,
            )
            conflicts = _conflict_files(config)
            if conflicts:
                update_task(
                    db,
                    task,
                    status=TaskStatus.BLOCKED,
                    node="merge_conflict",
                    progress=55,
                    last_error=pulled.output,
                    sync_status="conflict",
                    summary=f"合并发生冲突，已停止；共 {len(conflicts)} 个冲突文件。",
                    conflict_files=conflicts,
                    changed_files=changed_paths[:100],
                    finished_at=datetime.now(UTC).isoformat(),
                )
                return _task_result(task)
            if pulled.returncode != 0:
                raise RuntimeError(pulled.output or "拉取远程 main 失败，已保留本地提交")

        attempts = max(1, config.code_sync_max_retries + 1)
        last_push = GitResult(1, "", "尚未推送")
        for attempt in range(1, attempts + 1):
            update_task(
                db,
                task,
                node="push_remote",
                progress=min(95, 65 + attempt * 5),
                summary=f"正在推送到 GitHub main，第 {attempt}/{attempts} 次尝试。",
                attempt_count=attempt,
            )
            last_push = run_git(
                ["push", "-u", config.code_sync_remote, config.code_sync_branch],
                settings=config,
                timeout=300,
            )
            if last_push.returncode == 0:
                update_task(
                    db,
                    task,
                    status=TaskStatus.SUCCEEDED,
                    node="completed",
                    progress=100,
                    sync_status="success",
                    summary=f"代码已成功推送到 {config.code_sync_remote}/{config.code_sync_branch}。",
                    last_commit=commit_hash,
                    last_commit_message=commit_message,
                    changed_files=changed_paths[:100],
                    skipped_files=blocked_paths[:100],
                    finished_at=datetime.now(UTC).isoformat(),
                    attempt_count=attempt,
                )
                return _task_result(task)
            if attempt >= attempts or not _is_retryable(last_push):
                break
            time.sleep(min(300, 30 * (2 ** (attempt - 1))))
        raise RuntimeError(last_push.output or f"推送失败，已完成 {attempts} 次尝试")
    except Exception as exc:
        update_task(
            db,
            task,
            status=TaskStatus.FAILED,
            node="failed",
            progress=min(task.progress, 99),
            last_error=str(exc),
            sync_status="failed",
            summary="代码同步失败，搜索项目文件和已生成的本地提交均已保留。",
            finished_at=datetime.now(UTC).isoformat(),
        )
        return _task_result(task)


def active_code_sync_task(db: Session) -> BackgroundTask | None:
    return db.scalar(
        select(BackgroundTask)
        .where(
            BackgroundTask.task_type == TASK_TYPE,
            BackgroundTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
        )
        .order_by(desc(BackgroundTask.created_at))
        .limit(1)
    )


def latest_code_sync_task(db: Session) -> BackgroundTask | None:
    return db.scalar(
        select(BackgroundTask)
        .where(BackgroundTask.task_type == TASK_TYPE)
        .order_by(desc(BackgroundTask.created_at))
        .limit(1)
    )


def create_code_sync_task(db: Session, *, requested_by: str, trigger: str) -> BackgroundTask:
    active = active_code_sync_task(db)
    if active is not None:
        return active
    task = BackgroundTask(
        id=uuid.uuid4(),
        project_id=None,
        operation_id=None,
        task_type=TASK_TYPE,
        status=TaskStatus.PENDING,
        current_node="queued",
        progress=0,
        result={
            "request": {"requested_by": requested_by, "trigger": trigger},
            "sync_status": "running",
            "summary": "代码同步任务已进入执行队列。",
        },
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def code_sync_status(db: Session, settings: Settings | None = None) -> dict[str, Any]:
    config = settings or get_settings()
    snapshot = repository_snapshot(config)
    task = latest_code_sync_task(db)
    result = _task_result(task) if task else {}
    request = result.get("request") if isinstance(result.get("request"), dict) else {}
    running = bool(task and task.status in {TaskStatus.PENDING, TaskStatus.RUNNING})
    if running:
        status = "running"
    elif task:
        status = str(result.get("sync_status") or ("success" if task.status == TaskStatus.SUCCEEDED else "failed"))
    else:
        status = "idle" if snapshot["available"] else "failed"
    summary = str(result.get("summary") or "尚未执行搜索项目代码同步。")
    if not snapshot["available"]:
        summary = str(snapshot.get("availability_error") or summary)
    elif not snapshot["remote_verified"]:
        summary = "当前远端不是搜索项目 whf6688/baidusembdx，已禁止同步。"
        status = "failed"
    return {
        "enabled": config.code_sync_enabled,
        "running": running,
        "status": status,
        "trigger": request.get("trigger"),
        "schedule": config.code_sync_daily_time,
        "next_run_at": next_code_sync_run(settings=config).isoformat(),
        "last_started_at": result.get("started_at"),
        "last_finished_at": result.get("finished_at"),
        "last_commit": result.get("last_commit") or snapshot.get("head"),
        "last_commit_message": result.get("last_commit_message") or snapshot.get("last_commit_message"),
        "summary": summary,
        "last_error": task.last_error if task else None,
        "changed_files": result.get("changed_files") or [],
        "skipped_files": result.get("skipped_files") or [],
        "conflict_files": result.get("conflict_files") or [],
        "attempt_count": int(result.get("attempt_count") or 0),
        "task_id": str(task.id) if task else None,
        **snapshot,
    }
