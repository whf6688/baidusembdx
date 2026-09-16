"""Prevent queued messages from reviving archived project work."""
import inspect
import uuid

from celery import Task
from sqlalchemy import func, select

from .db import SessionLocal
from .models import Account, AccountManager, AdBuildBatch, AdBuildJob, BackgroundTask, Operation, Project, TaskStatus


def archived_task_accounts(db, task):
    operation_id = getattr(task, 'operation_id', None)
    if operation_id:
        operation = db.get(Operation, operation_id)
        if operation and db.scalar(select(Account.id).where(
            Account.baidu_account_id == operation.target_account_id, Account.permission_status == 'archived')):
            return True
    request = (getattr(task, 'result', None) or {}).get('request') or {}
    manager_id = request.get('manager_id')
    if manager_id:
        manager = db.get(AccountManager, uuid.UUID(str(manager_id)))
        if manager and (manager.auth_status == 'archived' or manager.is_active is False):
            return True
    ids = request.get('account_ids') or []
    if ids:
        try:
            ids = {uuid.UUID(str(value)) for value in ids}
        except ValueError:
            return False
        archived = db.scalar(select(func.count()).select_from(Account).where(
            Account.id.in_(ids), Account.permission_status == 'archived'))
        return archived == len(ids)
    return False


def archived_scope(db, parameters):
    project_ids = []
    task = None
    for name in ('task_id', 'project_id', 'batch_id', 'manager_id'):
        value = parameters.get(name)
        if not value:
            continue
        try:
            identifier = uuid.UUID(str(value))
        except ValueError:
            continue
        if name == 'project_id':
            project_ids.append(identifier)
        elif name == 'task_id':
            task = db.get(BackgroundTask, identifier)
            if task:
                if task.current_node == 'manager_archived':
                    return True, task
                if archived_task_accounts(db, task):
                    return True, task
                project_ids.append(task.project_id)
        elif name == 'batch_id':
            batch = db.get(AdBuildBatch, identifier)
            if batch:
                if batch.status == 'archived':
                    return True, task
                job = db.get(AdBuildJob, batch.job_id)
                if job:
                    project_ids.append(job.project_id)
        else:
            manager = db.get(AccountManager, identifier)
            if manager:
                if manager.auth_status == 'archived' or manager.is_active is False:
                    return True, task
                project_ids.append(manager.project_id)
    for project_id in project_ids:
        project = db.get(Project, project_id) if project_id else None
        if project and project.enabled is False:
            return True, task
    return False, task


class ProjectScopeTask(Task):
    def __call__(self, *args, **kwargs):
        parameters = inspect.signature(self.run).bind(*args, **kwargs).arguments
        if any(parameters.get(name) for name in ('task_id', 'project_id', 'batch_id', 'manager_id')):
            with SessionLocal() as db:
                blocked, task = archived_scope(db, parameters)
                if blocked:
                    if task and task.status != TaskStatus.SUCCEEDED:
                        task.status = TaskStatus.BLOCKED
                        task.current_node = 'manager_archived'
                        task.last_error = '管家或项目已停用归档，禁止继续执行'
                        db.commit()
                    return {'status': 'blocked', 'reason': 'manager_or_project_archived'}
        return super().__call__(*args, **kwargs)
