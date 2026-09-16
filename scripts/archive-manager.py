"""Archive a project manager locally without making any Baidu requests."""
import argparse
import json
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from search_console.config import get_settings
from search_console.db import SessionLocal
from search_console.models import (
    Account, AccountManager, AdBuildBatch, AdBuildJob, AuditEvent, BackgroundTask,
    Operation, OperationStatus, Project, StrategyScheduleRun, TaskStatus,
)


def archive(db, login_name, apply=False):
    manager = db.scalar(select(AccountManager).where(AccountManager.login_name == login_name).with_for_update())
    if manager is None:
        raise RuntimeError('Manager not found')
    project = db.get(Project, manager.project_id)
    other_managers = db.scalar(select(func.count()).select_from(AccountManager).where(
        AccountManager.project_id == project.id, AccountManager.id != manager.id, AccountManager.is_active.is_(True),
    ))
    accounts = db.scalars(select(Account).where(Account.project_id == project.id,
        (Account.manager_id == manager.id) | (Account.manager_login_name == manager.login_name))).all()
    unrelated_active = db.scalar(select(func.count()).select_from(Account).where(
        Account.project_id == project.id, Account.is_active.is_(True), Account.id.not_in([a.id for a in accounts]),
    ))
    pause_project = not other_managers and not unrelated_active
    summary = {'project_id': str(project.id), 'manager_id': str(manager.id), 'accounts_preserved': len(accounts), 'project_paused': pause_project}
    if not apply:
        return summary
    if manager.auth_status == 'archived' and not manager.is_active:
        return {**summary, 'already_archived': True}
    now = datetime.now(UTC)
    prior = {'project_enabled': project.enabled, 'manager_active': manager.is_active,
             'manager_auth_status': manager.auth_status,
             'accounts': [{'id': str(a.id), 'is_active': a.is_active, 'permission_status': a.permission_status} for a in accounts]}
    manager.is_active = False
    manager.auth_status = 'archived'
    if pause_project:
        project.enabled = False
    for account in accounts:
        account.is_active = False
        account.permission_status = 'archived'
    params = {'application': get_settings().baidu_application_code, 'manager': manager.login_name,
              'owner_id': str(manager.baidu_user_id or '')}
    token_rows = db.execute(text('''SELECT id, owner_type FROM platform_core.authorization_tokens
        WHERE baidu_application_code=:application AND owner_type IN ('manager','mcc')
        AND (login_name=:manager OR owner_id=:owner_id) FOR UPDATE'''), params).mappings().all()
    prior['token_owner_types'] = [{'id': str(r['id']), 'owner_type': r['owner_type']} for r in token_rows]
    # Retain encrypted credentials, but make them ineligible for runtime selection.
    db.execute(text('''UPDATE platform_core.authorization_tokens SET owner_type='archived_' || owner_type
        WHERE baidu_application_code=:application AND owner_type IN ('manager','mcc')
        AND (login_name=:manager OR owner_id=:owner_id)'''), params)
    db.execute(text('''UPDATE platform_core.account_bindings SET permission_status='archived'
        WHERE baidu_application_code=:application AND manager_login_name=:manager'''), params)
    db.execute(text('''UPDATE platform_core.oauth_states SET consumed_at=now()
        WHERE consumed_at IS NULL AND context->>'manager_id'=:manager_id'''), {'manager_id': str(manager.id)})
    operations = db.scalars(select(Operation).where(Operation.target_account_id.in_([a.baidu_account_id for a in accounts]),
        Operation.status != OperationStatus.SUCCEEDED)).all()
    operation_ids = {o.id for o in operations}
    archived_account_ids = {str(a.id) for a in accounts}
    def targets_manager(task):
        request = (task.result or {}).get('request') or {}
        ids = request.get('account_ids') or []
        return (pause_project or task.operation_id in operation_ids
            or request.get('manager_id') == str(manager.id)
            or request.get('manager_login_name') == manager.login_name
            or (bool(ids) and set(map(str, ids)).issubset(archived_account_ids)))
    project_tasks = db.scalars(select(BackgroundTask).where(BackgroundTask.project_id == project.id,
        BackgroundTask.status != TaskStatus.SUCCEEDED)).all()
    tasks = [task for task in project_tasks if targets_manager(task)]
    prior['tasks'] = [{'id': str(t.id), 'status': t.status.value, 'current_node': t.current_node} for t in tasks]
    for task in tasks:
        task.status = TaskStatus.BLOCKED
        task.current_node = 'manager_archived'
        task.last_error = '管家已移除归档，停止同步与自动任务；历史数据保留'
        task.updated_at = now
    prior['operations'] = [{'id': str(o.id), 'status': o.status.value} for o in operations]
    for operation in operations:
        operation.status = OperationStatus.FAILED
    jobs = db.scalars(select(AdBuildJob).where(AdBuildJob.project_id == project.id)).all()
    prior['jobs'] = [{'id': str(j.id), 'status': j.status} for j in jobs]
    batches = db.scalars(select(AdBuildBatch).where(AdBuildBatch.job_id.in_([j.id for j in jobs]),
        AdBuildBatch.status != 'succeeded')).all()
    batches = [b for b in batches if pause_project or (b.account_ids and set(map(str, b.account_ids)).issubset(archived_account_ids))]
    prior['batches'] = [{'id': str(b.id), 'status': b.status} for b in batches]
    for batch in batches:
        batch.status = 'archived'
    db.flush()
    archived_job_ids = {batch.job_id for batch in batches}
    for job in jobs:
        if not pause_project and job.id not in archived_job_ids:
            continue
        remaining = db.scalar(select(func.count()).select_from(AdBuildBatch).where(
            AdBuildBatch.job_id == job.id, AdBuildBatch.status.not_in(['succeeded', 'archived'])))
        if not remaining and job.status != 'succeeded':
            job.status = 'archived'
    schedules = db.scalars(select(StrategyScheduleRun).where(StrategyScheduleRun.project_id == project.id,
        StrategyScheduleRun.status == 'queued')).all()
    for schedule in schedules:
        if pause_project or schedule.task_id in {t.id for t in tasks}:
            schedule.status = 'blocked'
    summary.update(tasks_stopped=len(tasks), operations_stopped=len(operations), batches_stopped=len(batches), tokens_archived=len(token_rows))
    db.add(AuditEvent(project_id=project.id, actor='user-request', action='manager.archive',
        target_type='account_manager', target_id=str(manager.id), summary='用户确认移除管家，停止关联账户任务并保留所有历史数据',
        details={'result': summary, 'previous_state': prior, 'baidu_requests': 0}))
    db.commit()
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('login_name')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    with SessionLocal() as db:
        print(json.dumps(archive(db, args.login_name, args.apply), ensure_ascii=False))
