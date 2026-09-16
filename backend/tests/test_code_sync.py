from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from search_console.code_sync import (
    execute_code_sync,
    next_code_sync_run,
    normalize_repository_url,
    path_is_forbidden,
    repository_snapshot,
    repository_url_is_allowed,
)
from search_console.config import Settings
from search_console.models import BackgroundTask, TaskStatus


def git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=path, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def test_repository_url_is_limited_to_search_repository() -> None:
    settings = Settings(_env_file=None)
    assert normalize_repository_url("git@github.com:whf6688/baidusembdx.git") == normalize_repository_url(
        "https://github.com/whf6688/baidusembdx.git"
    )
    assert repository_url_is_allowed("git@github.com:whf6688/baidusembdx.git", settings)
    assert not repository_url_is_allowed("git@github.com:whf6688/another-project.git", settings)


def test_sensitive_and_runtime_paths_are_never_syncable() -> None:
    assert path_is_forbidden(".env")
    assert not path_is_forbidden(".env.example")
    assert path_is_forbidden("data/postgres/PG_VERSION")
    assert path_is_forbidden("storage/raw-response.json")
    assert path_is_forbidden("deploy/private_key.pem")
    assert not path_is_forbidden("frontend/src/App.tsx")
    assert not path_is_forbidden("backend/src/search_console/data/baidu_regions.json")


def test_next_run_is_daily_two_am() -> None:
    timezone = ZoneInfo("Asia/Shanghai")
    settings = Settings(_env_file=None, code_sync_daily_time="02:00")
    before = datetime(2026, 9, 16, 1, 59, tzinfo=timezone)
    after = datetime(2026, 9, 16, 2, 1, tzinfo=timezone)
    assert next_code_sync_run(before, settings) == datetime(2026, 9, 16, 2, 0, tzinfo=timezone)
    assert next_code_sync_run(after, settings) == datetime(2026, 9, 17, 2, 0, tzinfo=timezone)


def test_sync_commits_and_pushes_to_configured_repository(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    remote.mkdir()
    work.mkdir()
    git(remote, "init", "--bare")
    git(work, "init", "-b", "main")
    git(work, "config", "user.name", "test")
    git(work, "config", "user.email", "test@example.invalid")
    (work / "README.md").write_text("initial\n", encoding="utf-8")
    git(work, "add", "README.md")
    git(work, "commit", "-m", "initial")
    git(work, "remote", "add", "origin", str(remote))
    git(work, "push", "-u", "origin", "main")
    (work / "README.md").write_text("updated\n", encoding="utf-8")

    settings = Settings(
        _env_file=None,
        code_sync_repository_path=work,
        code_sync_repository_https_url=str(remote),
        code_sync_repository_ssh_url=str(remote),
        code_sync_ssh_key_path=tmp_path / "missing-key",
        code_sync_known_hosts_path=tmp_path / "missing-hosts",
        code_sync_max_retries=0,
    )
    snapshot = repository_snapshot(settings)
    assert snapshot["available"] is True
    assert snapshot["remote_verified"] is True
    assert snapshot["syncable_count"] == 1

    class Database:
        def commit(self) -> None:
            return None

    task = BackgroundTask(task_type="code_sync", status=TaskStatus.PENDING, result={})
    result = execute_code_sync(Database(), task, settings)  # type: ignore[arg-type]
    assert task.status == TaskStatus.SUCCEEDED
    assert result["sync_status"] == "success"
    assert git(remote, "show", "main:README.md") == "updated"
