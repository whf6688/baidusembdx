import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from search_console.models import AccountManager, AdBuildBatch, AdBuildJob, BackgroundTask, Project
from search_console.task_guard import archived_scope, archived_task_accounts, ProjectScopeTask
from search_console.oauth import sync_project_accounts


class FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def get(self, model, key):
        return self.rows.get((model, key))


def test_old_queued_task_is_blocked_after_manager_archival():
    task_id = uuid.uuid4()
    task = SimpleNamespace(current_node='manager_archived')
    assert archived_scope(FakeDB({(BackgroundTask, task_id): task}), {'task_id': str(task_id)}) == (True, task)


def test_archived_project_blocks_project_task_and_ad_build_batch():
    project_id, task_id, batch_id, job_id = [uuid.uuid4() for _ in range(4)]
    task = SimpleNamespace(current_node='queued', project_id=project_id)
    db = FakeDB({
        (Project, project_id): SimpleNamespace(enabled=False),
        (BackgroundTask, task_id): task,
        (AdBuildBatch, batch_id): SimpleNamespace(status='scheduled', job_id=job_id),
        (AdBuildJob, job_id): SimpleNamespace(project_id=project_id),
    })
    assert archived_scope(db, {'task_id': str(task_id)})[0]
    assert archived_scope(db, {'project_id': str(project_id)})[0]
    assert archived_scope(db, {'batch_id': str(batch_id)})[0]


def test_other_project_and_global_schedules_are_not_blocked():
    project_id = uuid.uuid4()
    db = FakeDB({(Project, project_id): SimpleNamespace(enabled=True)})
    assert archived_scope(db, {'project_id': str(project_id)}) == (False, None)
    assert archived_scope(db, {}) == (False, None)


def test_manager_subject_sync_is_blocked():
    manager_id = uuid.uuid4()
    db = FakeDB({(AccountManager, manager_id): SimpleNamespace(auth_status='archived', is_active=False)})
    assert archived_scope(db, {'manager_id': str(manager_id)})[0]


def test_paused_manager_is_blocked_without_being_archived():
    manager_id = uuid.uuid4()
    db = FakeDB({
        (AccountManager, manager_id): SimpleNamespace(
            auth_status='authorized',
            is_active=False,
            project_id=uuid.uuid4(),
        )
    })
    assert archived_scope(db, {'manager_id': str(manager_id)})[0]


def test_sync_cannot_reactivate_archived_accounts():
    with pytest.raises(HTTPException) as error:
        sync_project_accounts(None, settings=None, project_id=uuid.uuid4(),
            manager=SimpleNamespace(auth_status='archived', is_active=False), manager_name='archived', user_info={})
    assert error.value.status_code == 409


def test_mixed_account_task_can_continue_for_other_manager():
    task = SimpleNamespace(result={'request': {'account_ids': [str(uuid.uuid4()), str(uuid.uuid4())]}})
    db = SimpleNamespace(scalar=lambda query: 1)
    assert not archived_task_accounts(db, task)
    db.scalar = lambda query: 2
    assert archived_task_accounts(db, task)


def test_worker_tasks_use_persistent_archive_guard():
    from search_console.worker import celery_app
    task = celery_app.tasks['search_console.worker.execute_operation']
    assert isinstance(task, ProjectScopeTask)
