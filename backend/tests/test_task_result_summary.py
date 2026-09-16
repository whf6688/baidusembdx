from types import SimpleNamespace

from search_console.api import serialize_ad_build_nodes, serialize_task_row, task_result_summary
from search_console.models import OperationStatus, TaskStatus


def test_campaign_task_summary_reports_live_account_and_plan_progress():
    task = SimpleNamespace(
        task_type="campaign_batch_update",
        status=TaskStatus.RUNNING,
        last_error=None,
        result={
            "request": {
                "action": "schedule",
                "account_ids": ["a", "b", "c"],
            },
            "state": {
                "processed_accounts": 2,
                "updated_plan_count": 11,
                "unchanged_plan_count": 4,
                "failed_accounts": {"100": "error"},
            },
        },
    )

    assert task_result_summary(task) == (
        "修改时段：已处理 2/3 个账户，更新 11 个计划，"
        "无需修改 4 个，失败 1 个账户"
    )


def test_generic_success_without_metrics_has_clear_result():
    task = SimpleNamespace(
        task_type="reference_template_sync",
        status=TaskStatus.SUCCEEDED,
        last_error=None,
        result={},
    )

    assert task_result_summary(task) == "执行完成"


def test_task_row_exposes_account_context_and_readback():
    task = SimpleNamespace(
        id="task-id",
        task_type="search_ad_build_workflow",
        status=TaskStatus.SUCCEEDED,
        current_node="complete",
        progress=100,
        retry_count=0,
        last_error=None,
        result={
            "workflow_state": {
                "readback": {
                    "campaign_count": 3,
                    "adgroup_count": 3,
                    "keyword_count": 7725,
                    "creative_count": 150,
                    "audience_count": 1,
                }
            }
        },
        heartbeat_at=None,
        created_at=None,
        updated_at=None,
    )
    operation = SimpleNamespace(
        id="operation-id",
        operation_type="search_ad_build_workflow",
        target_account_id=86974869,
        payload={"target_login_name": "baidu-test-account"},
    )
    account = SimpleNamespace(
        login_name="baidu-test-account",
        manager_login_name="manager-test",
    )

    row = serialize_task_row(task, operation, account)

    assert row["account_name"] == "baidu-test-account"
    assert row["account_id"] == 86974869
    assert row["manager_login_name"] == "manager-test"
    assert row["readback"]["keyword_count"] == 7725


def test_historical_failed_attempt_is_not_resumable_after_operation_succeeds():
    task = SimpleNamespace(
        id="old-failed-task",
        task_type="search_ad_build_workflow",
        status=TaskStatus.FAILED,
        current_node="creatives_verified",
        progress=88,
        retry_count=3,
        last_error="creative rejected",
        result={},
        heartbeat_at=None,
        created_at=None,
        updated_at=None,
    )
    operation = SimpleNamespace(
        id="operation-id",
        operation_type="search_ad_build_workflow",
        target_account_id=86974869,
        status=OperationStatus.SUCCEEDED,
        payload={"target_login_name": "baidu-test-account"},
    )

    row = serialize_task_row(task, operation, None, is_latest_attempt=False)

    assert row["superseded"] is True
    assert row["can_resume"] is False


def test_latest_failed_attempt_remains_resumable():
    task = SimpleNamespace(
        id="latest-failed-task",
        task_type="search_ad_build_workflow",
        status=TaskStatus.FAILED,
        current_node="keywords_acknowledged",
        progress=72,
        retry_count=1,
        last_error="temporary error",
        result={},
        heartbeat_at=None,
        created_at=None,
        updated_at=None,
    )
    operation = SimpleNamespace(
        id="operation-id",
        operation_type="search_ad_build_workflow",
        target_account_id=86974869,
        status=OperationStatus.FAILED,
        payload={"target_login_name": "baidu-test-account"},
    )

    row = serialize_task_row(task, operation, None, is_latest_attempt=True)

    assert row["superseded"] is False
    assert row["can_resume"] is True


def test_campaign_task_exposes_action_and_disables_manual_resume_when_auto_retry_exists():
    task = SimpleNamespace(
        id="campaign-task",
        task_type="campaign_batch_update",
        status=TaskStatus.FAILED,
        current_node="campaign_batch_auto_retry_scheduled",
        progress=100,
        retry_count=0,
        last_error="2 个账户执行失败，已安排第 1 次自动安全续跑",
        result={
            "request": {"action": "schedule", "account_ids": ["a", "b"]},
            "state": {
                "failed_accounts": {"1001": "temporary error"},
                "auto_retry": {"task_id": "retry-task", "attempt": 1},
            },
        },
        heartbeat_at=None,
        created_at=None,
        updated_at=None,
    )

    row = serialize_task_row(task)

    assert row["execution_action"] == "schedule"
    assert row["can_resume"] is False


def test_cancelled_ad_build_keeps_completed_nodes_and_does_not_report_a_false_failure():
    task = SimpleNamespace(
        status=TaskStatus.BLOCKED,
        current_node="cancelled",
        progress=20,
        last_error=None,
        result={
            "cancelled": True,
            "workflow_state": {
                "timings": {
                    "material_preflight": {
                        "started_at": "2026-09-16T00:00:00+00:00",
                        "completed_at": "2026-09-16T00:00:01+00:00",
                        "duration_seconds": 1,
                    }
                }
            },
        },
    )

    nodes = serialize_ad_build_nodes(task)

    assert nodes[0]["status"] == "succeeded"
    assert all(node["status"] != "failed" for node in nodes)
    assert all(node["message"] is None for node in nodes)


def test_scheduled_ad_build_reports_every_node_as_pending_before_dispatch():
    task = SimpleNamespace(
        status=TaskStatus.PENDING,
        current_node="scheduled_ad_build_wait",
        progress=0,
        last_error=None,
        result={"scheduled_for": "2026-09-17T02:00:00+00:00"},
    )

    nodes = serialize_ad_build_nodes(task)

    assert {node["status"] for node in nodes} == {"pending"}
