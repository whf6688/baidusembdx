from search_console.worker import extract_account_info, sync_account_details


def test_extract_account_info_from_root_data():
    assert extract_account_info({"data": [{"liceName": "主体甲"}]}) == {"liceName": "主体甲"}


def test_extract_account_info_from_body_data():
    assert extract_account_info({"body": {"data": [{"liceName": "主体乙"}]}}) == {"liceName": "主体乙"}


def test_extract_account_info_rejects_empty_response():
    assert extract_account_info({"body": {"data": []}}) is None


def test_account_subject_sync_is_disabled_without_api_calls():
    result = sync_account_details.run("project", "manager")
    assert result == {
        "status": "disabled", "reason": "manager_shared_subject", "run_id": None,
        "processed": 0, "updated": 0, "failed": 0,
    }
