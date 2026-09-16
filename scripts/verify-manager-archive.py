"""Read-only verification; never decrypts tokens or invokes Baidu."""
import json
import sys

from sqlalchemy import func, select, text
from search_console.config import get_settings
from search_console.db import SessionLocal
from search_console.models import Account, AccountManager, AuditEvent, BackgroundTask, MaterialKeyword, PerformanceDaily, Project
from search_console.task_guard import archived_scope

with SessionLocal() as db:
    manager = db.scalar(select(AccountManager).where(AccountManager.login_name == sys.argv[1]))
    assert manager and manager.auth_status == 'archived' and not manager.is_active
    audit = db.scalar(select(AuditEvent).where(AuditEvent.action == 'manager.archive', AuditEvent.target_id == str(manager.id)).order_by(AuditEvent.created_at.desc()))
    account_ids = select(Account.id).where(Account.manager_id == manager.id)
    total = db.scalar(select(func.count()).select_from(Account).where(Account.manager_id == manager.id))
    active = db.scalar(select(func.count()).select_from(Account).where(Account.manager_id == manager.id, Account.is_active.is_(True)))
    assert active == 0
    assert total == audit.details['result']['accounts_preserved']
    params = {'application': get_settings().baidu_application_code, 'manager': manager.login_name, 'since': audit.created_at}
    eligible = db.scalar(text('''SELECT count(*) FROM platform_core.authorization_tokens
        WHERE baidu_application_code=:application AND login_name=:manager AND owner_type IN ('manager','mcc')'''), params)
    granted = db.scalar(text('''SELECT count(*) FROM platform_core.account_bindings
        WHERE baidu_application_code=:application AND manager_login_name=:manager AND permission_status='granted' '''), params)
    calls = db.scalar(text('''SELECT count(*) FROM platform_core.api_audit
        WHERE baidu_application_code=:application AND manager_login_name=:manager AND created_at>=:since'''), params)
    assert eligible == 0 and granted == 0
    tasks = db.scalars(select(BackgroundTask).where(BackgroundTask.project_id == manager.project_id, BackgroundTask.current_node == 'manager_archived').limit(10)).all()
    assert all(archived_scope(db, {'task_id': str(task.id)})[0] for task in tasks)
    peers = db.scalars(select(AccountManager).where(AccountManager.id != manager.id, AccountManager.is_active.is_(True))).all()
    print(json.dumps({
        'archived': True, 'accounts_preserved': total, 'active_accounts': active,
        'material_keywords_preserved': db.scalar(select(func.count()).select_from(MaterialKeyword).where(MaterialKeyword.project_id == manager.project_id)),
        'daily_fact_rows_preserved': db.scalar(select(func.count()).select_from(PerformanceDaily).where(PerformanceDaily.account_id.in_(account_ids))),
        'selectable_tokens': eligible, 'granted_bindings': granted, 'baidu_calls_since_archive': calls,
        'queued_task_guard_verified': len(tasks), 'project_enabled': db.get(Project, manager.project_id).enabled,
        'other_active_managers': [m.login_name for m in peers],
    }, ensure_ascii=False))
