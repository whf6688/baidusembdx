import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import search_console.ad_build_executor as executor_module

from search_console.ad_builds import (
    account_configuration_issues,
    account_workflow_overrides,
    account_workflow_steps,
    build_ad_build_preview,
    build_keyword_tracking_url,
    build_ocpc_project_name,
    build_plan_pause_schedule,
    build_plan_pause_schedule_from_windows,
    keyword_uploaded_adgroup_ids,
)
from search_console.ad_build_executor import (
    _adgroup_mobile_final_url,
    _approved_creative_candidates,
    _creative_readback_key,
    _create_adgroups,
    _create_creatives,
    _pack_keyword_unit_batches,
    _upload_keywords,
)
from search_console.schemas import AdBuildPreviewRequest


NOW = datetime(2026, 7, 14, 1, 0, tzinfo=UTC)
PROJECT_ID = uuid.uuid4()


def test_ocpc_project_name_uses_managed_project_name_and_beijing_execution_time():
    assert build_ocpc_project_name(
        "减肥搜索",
        datetime(2026, 9, 16, 7, 30, tzinfo=UTC),
    ) == "减肥搜索_0916_15"


def test_ocpc_project_name_rejects_names_that_exceed_baidu_limit():
    with pytest.raises(ValueError, match="最多 12 个字符"):
        build_ocpc_project_name(
            "这是一个超过十二个字符的项目名称",
            datetime(2026, 9, 16, 7, 30, tzinfo=UTC),
        )


def test_keyword_upload_fills_ten_thousand_across_unit_boundaries():
    units = [(index, f"A_{index:02d}", [{}] * 2217) for index in range(1, 6)]
    units.append((6, "B_01", [{}] * 355))
    batches = _pack_keyword_unit_batches(units)
    assert [row[1] for row in batches[0]] == ["A_01", "A_02", "A_03", "A_04", "A_05"]
    assert [len(row[2]) for row in batches[0]] == [2217, 2217, 2217, 2217, 1132]
    assert sum(len(row[2]) for row in batches[0]) == 10000
    assert [row[1] for row in batches[1]] == ["A_05", "B_01"]
    assert [len(row[2]) for row in batches[1]] == [1085, 355]
    assert all(sum(len(row[2]) for row in batch) <= 10000 for batch in batches)


def test_keyword_upload_sends_exact_ten_thousand_in_one_request():
    batches = _pack_keyword_unit_batches([(1, "A_01", [{}] * 10000)])
    assert len(batches) == 1
    assert len(batches[0]) == 1
    assert len(batches[0][0][2]) == 10000


def test_keyword_upload_only_leaves_the_final_request_under_ten_thousand():
    batches = _pack_keyword_unit_batches([(1, "A_01", [{}] * 21868)])
    assert [sum(len(row[2]) for row in batch) for batch in batches] == [10000, 10000, 1868]


def test_successful_keyword_upload_skips_post_write_readback(monkeypatch):
    read_calls = []
    saved_nodes = []

    def fake_read_keywords(*args):
        read_calls.append(args)
        return []

    monkeypatch.setattr(executor_module, "_read_keywords", fake_read_keywords)
    monkeypatch.setattr(
        executor_module,
        "_save",
        lambda db, task, state, node, progress: saved_nodes.append(node),
    )

    class Client:
        def execute_write(self, context, service, payload):
            assert service == "keyword.add"
            assert len(payload["keywordTypes"]) == 2
            return {"header": {}}

    row = account(1001, account_type="一跳空户")
    row.manager_login_name = "manager"
    operation = SimpleNamespace(id=uuid.uuid4(), payload={})
    task = SimpleNamespace()
    state = {}
    results = _upload_keywords(
        SimpleNamespace(),
        task,
        Client(),
        row,
        operation,
        state,
        [{"name": "A成本_01", "campaign_name": "A成本", "keywords": ["关键词一", "关键词二"]}],
        {"A成本_01": 2001},
        {
            "关键词一": SimpleNamespace(keyword_utf8_encoded="%E5%85%B3%E9%94%AE%E8%AF%8D%E4%B8%80"),
            "关键词二": SimpleNamespace(keyword_utf8_encoded="%E5%85%B3%E9%94%AE%E8%AF%8D%E4%BA%8C"),
        },
        {"A成本": 3001},
    )

    assert len(read_calls) == 1
    assert results[0]["verification_mode"] == "api_acknowledged"
    assert results[0]["post_write_readback_skipped"] is True
    assert results[0]["uploaded_keyword_count"] == 2
    assert "keywords_acknowledged_1" in saved_nodes


def test_keyword_upload_defers_unactivated_account_after_901676(monkeypatch):
    submitted_sizes = []

    monkeypatch.setattr(
        executor_module,
        "_read_keywords",
        lambda *args: [{"keyword": "已有关键词"}],
    )
    monkeypatch.setattr(executor_module, "_save", lambda *args: None)

    class Client:
        def execute_write(self, context, service, payload):
            size = len(payload["keywordTypes"])
            submitted_sizes.append(size)
            raise RuntimeError("百度返回业务错误：901676")

    row = account(1002, account_type="一跳空户")
    row.manager_login_name = "manager"
    keywords = ["已有关键词", "待传关键词1", "待传关键词2"]
    materials = {
        keyword.casefold(): SimpleNamespace(keyword_utf8_encoded="encoded")
        for keyword in keywords
    }
    state = {}
    results = _upload_keywords(
        SimpleNamespace(),
        SimpleNamespace(),
        Client(),
        row,
        SimpleNamespace(id=uuid.uuid4(), payload={}),
        state,
        [{"name": "A成本_01", "campaign_name": "A成本", "keywords": keywords}],
        {"A成本_01": 2002},
        materials,
        {"A成本": 3002},
    )

    assert submitted_sizes == [2]
    assert state["keyword_upload_deferred"]["reason_code"] == "901676"
    assert state["keyword_upload_deferred"]["remaining_keyword_count"] == 2
    assert state["keyword_completion_mode"] == "deferred_until_account_activation"
    assert results[0]["uploaded_keyword_count"] == 1
    assert results[0]["complete"] is False


def test_creative_replacement_uses_only_approved_combinations_most_proven_first():
    title = SimpleNamespace(id=uuid.uuid4(), content="审核通过创意标题")
    description = SimpleNamespace(id=uuid.uuid4(), content="这是已经通过百度审核的创意描述")

    def combination(value: str, *, blacklisted: bool = False):
        return SimpleNamespace(
            id=uuid.uuid4(),
            combination_hash=value,
            title_segment_id=title.id,
            description1_segment_id=description.id,
            description2_segment_id=None,
            is_blacklisted=blacklisted,
        )

    proven = combination("proven")
    approved = combination("approved")
    active = combination("active")
    blocked = combination("blocked", blacklisted=True)
    unapproved = combination("unapproved")
    candidates = _approved_creative_candidates(
        [approved, active, blocked, unapproved, proven],
        [title, description],
        {proven.id: 8, approved.id: 3, active.id: 10, blocked.id: 20},
        {active.combination_hash},
    )

    assert [row.combination_hash for row in candidates] == ["proven", "approved"]


def test_direct_creative_rejection_records_and_replaces_assignment(monkeypatch):
    assignment_id = uuid.uuid4()
    operation = SimpleNamespace(
        id=uuid.uuid4(),
        payload={
            "creative_combinations": [{
                "assignment_id": str(assignment_id),
                "title": "审核标题示例",
                "description1": "审核描述示例内容",
                "description2": "",
            }],
        },
    )
    row = account(1003, link="https://example.com/page")
    row.manager_login_name = "manager"
    monkeypatch.setattr(executor_module, "_read_creatives", lambda *args: [])

    class Client:
        def execute_write(self, context, service, payload):
            assert service == "creative.add"
            raise RuntimeError("百度返回业务错误：90180006493")

    class ReplacementInvoked(Exception):
        pass

    def replace(db, current_operation, assignment_ids, *, reason):
        assert current_operation is operation
        assert assignment_ids == [str(assignment_id)]
        assert "审核通过组合" in reason
        raise ReplacementInvoked

    monkeypatch.setattr(executor_module, "_replace_creative_assignments", replace)

    with pytest.raises(ReplacementInvoked):
        _create_creatives(
            SimpleNamespace(),
            Client(),
            row,
            operation,
            {2003: 3003},
            [2003],
            "example.com",
        )


def account(
    account_id: int,
    *,
    subject: str = "主体甲",
    manager: str = "管家甲",
    lifecycle: str = "空账户",
    account_type: str = "二跳账户",
    page_type: str | None = "科普账户",
    promotion_page: str | None = "科普基木鱼",
    link: str | None = "https://example.com/page?userid={userid}",
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        baidu_account_id=account_id,
        login_name=f"账户{account_id}",
        account_subject=subject,
        manager_login_name=manager,
        lifecycle_stage=lifecycle,
        account_type=account_type,
        page_type=page_type,
        promotion_page=promotion_page,
        landing_url_template=link,
        permission_status="granted",
        is_active=True,
    )


def test_adgroup_mobile_final_url_uses_promotion_link_and_baidu_account_id():
    row = account(86458980, link="https://example.com/page/")
    assert _adgroup_mobile_final_url(row) == "https://example.com/page/?zhanghuid=86458980"


def test_adgroup_mobile_final_url_preserves_existing_query_parameters():
    row = account(
        86458980,
        link=(
            "https://sp.vejianzhan.com/site/wjzinvqnc/"
            "e02e4e93-cce5-46db-845f-64493ef1a7fe"
            "?id=ghgcwb7016&newEb=2"
        ),
    )
    assert _adgroup_mobile_final_url(row) == (
        "https://sp.vejianzhan.com/site/wjzinvqnc/"
        "e02e4e93-cce5-46db-845f-64493ef1a7fe"
        "?id=ghgcwb7016&newEb=2&zhanghuid=86458980"
    )


def test_adgroup_mobile_final_url_replaces_old_account_parameter():
    row = account(
        82915223,
        link="https://example.com/page?id=1&zhanghuid=1&newEb=2#content",
    )
    assert _adgroup_mobile_final_url(row) == (
        "https://example.com/page?id=1&newEb=2&zhanghuid=82915223#content"
    )


def test_adgroup_ack_is_checkpointed_when_baidu_readback_is_delayed(monkeypatch):
    monkeypatch.setattr(executor_module, "_read_adgroups", lambda *_: [])
    monkeypatch.setattr(executor_module.time, "sleep", lambda _: None)

    class Client:
        def execute_write(self, _context, service, payload):
            assert service == "adgroup.add"
            assert payload["adgroupTypes"][0]["adgroupName"] == "A成本_01"
            return {"data": [{"adgroupName": "A成本_01", "adgroupId": 9001}]}

    row = account(86458980, link="https://example.com/page/")
    row.manager_login_name = "manager"
    operation = SimpleNamespace(id=uuid.uuid4(), payload={})

    result = _create_adgroups(
        Client(),
        row,
        operation,
        7001,
        [{"name": "A成本_01"}],
        1.0,
    )

    assert result.unit_ids == {"A成本_01": 9001}
    assert result.pending_names == ["A成本_01"]


def preview(rows, **changes):
    values = {
        "project_id": PROJECT_ID,
        "selection_mode": "random",
        "quantity": 2,
        "selection_seed": "seed-1",
        "execution_mode": "immediate",
    }
    values.update(changes)
    payload = AdBuildPreviewRequest(**values)
    return build_ad_build_preview(rows, payload, material_keyword_count=12, writes_enabled=False, now=NOW)


def test_specified_accounts_use_exact_login_or_account_id():
    rows = [account(101), account(102)]
    result = preview(
        rows,
        selection_mode="specified_accounts",
        account_selectors=["账户101", "102"],
        quantity=None,
    )
    assert result["selected_account_ids"] == [101, 102]
    assert result["can_submit"] is True


def test_specified_managers_take_all_empty_accounts_under_each_manager():
    rows = [
        account(101, manager="管家甲"),
        account(102, manager="管家甲", lifecycle="投放中"),
        account(103, manager="管家乙"),
    ]
    result = preview(
        rows,
        selection_mode="specified_managers",
        manager_login_names=["管家甲"],
        quantity=None,
    )
    assert result["selected_account_ids"] == [101]
    assert result["can_submit"] is True


def test_specified_managers_apply_quantity_to_each_selected_manager():
    rows = [
        account(101, manager="管家甲"),
        account(102, manager="管家甲"),
        account(103, manager="管家甲"),
        account(201, manager="管家乙"),
        account(202, manager="管家乙"),
        account(203, manager="管家乙"),
    ]
    result = preview(
        rows,
        selection_mode="specified_managers",
        manager_login_names=["管家甲", "管家乙"],
        quantity=2,
    )
    assert result["selected_account_ids"] == [101, 102, 201, 202]
    assert result["subject_allocation"] == {"管家甲": 2, "管家乙": 2}
    assert result["can_submit"] is True


def test_multi_subjects_allocate_as_evenly_as_capacity_allows():
    rows = [account(100 + index, subject=f"主体{subject}") for index, subject in enumerate("甲乙丙甲乙丙甲乙丙")]
    result = preview(rows, selection_mode="multi_subjects", quantity=8)
    counts = list(result["subject_allocation"].values())
    assert result["selected_count"] == 8
    assert max(counts) - min(counts) <= 1


def test_specified_subjects_take_all_empty_accounts_only():
    rows = [account(1, subject="甲"), account(2, subject="甲", lifecycle="投放中"), account(3, subject="乙")]
    result = preview(rows, selection_mode="specified_subjects", subject_names=["甲"], quantity=None)
    assert result["selected_account_ids"] == [1]


def test_random_mode_is_stable_for_same_seed_and_changes_with_new_seed():
    rows = [account(index) for index in range(1, 15)]
    first = preview(rows, quantity=5, selection_seed="same")
    repeated = preview(rows, quantity=5, selection_seed="same")
    changed = preview(rows, quantity=5, selection_seed="different")
    assert first["selected_account_ids"] == repeated["selected_account_ids"]
    assert first["selected_account_ids"] != changed["selected_account_ids"]


def test_scheduled_queue_splits_one_hundred_accounts_into_requested_batch_size():
    rows = [account(index) for index in range(1, 101)]
    start = NOW + timedelta(hours=2)
    result = preview(
        rows,
        quantity=100,
        execution_mode="scheduled",
        scheduled_at=start,
        batch_size=12,
        batch_interval_minutes=30,
    )
    assert result["batch_count"] == 9
    assert [batch["account_count"] for batch in result["batches"]] == [12] * 8 + [4]
    assert result["batches"][1]["scheduled_at"] - result["batches"][0]["scheduled_at"] == timedelta(minutes=30)


def test_scheduled_queue_uses_date_time_cartesian_slots_and_stops_when_complete():
    rows = [account(index) for index in range(1, 101)]
    result = preview(
        rows,
        quantity=100,
        execution_mode="scheduled",
        scheduled_dates=["2026-07-15", "2026-07-16", "2026-07-17", "2026-07-18"],
        scheduled_times=["10:00", "14:00", "18:00"],
        batch_size=10,
    )
    assert result["can_submit"] is True
    assert result["batch_count"] == 10
    assert result["required_batch_count"] == 10
    assert result["available_schedule_slot_count"] == 12
    assert result["unused_schedule_slot_count"] == 2
    assert result["batches"][0]["scheduled_at"] == datetime(2026, 7, 15, 2, 0, tzinfo=UTC)
    assert result["batches"][-1]["scheduled_at"] == datetime(2026, 7, 18, 2, 0, tzinfo=UTC)


def test_finite_schedule_discards_past_slots_and_starts_from_nearest_future_slot():
    rows = [account(index) for index in range(1, 5)]
    now = datetime(2026, 7, 17, 10, 0, tzinfo=UTC)  # 18:00 Beijing time
    request = AdBuildPreviewRequest(
        project_id=PROJECT_ID,
        selection_mode="random",
        quantity=4,
        execution_mode="scheduled",
        scheduled_dates=["2026-07-17", "2026-07-18"],
        scheduled_times=["09:00", "15:00", "19:00"],
        batch_size=1,
    )
    result = build_ad_build_preview(
        accounts=rows,
        payload=request,
        material_keyword_count=12,
        writes_enabled=True,
        now=now,
        creative_summary={
            "segment_counts": {"title": 1, "description1": 1, "description2": 0},
            "available_combination_count": 50,
            "blacklisted_combination_count": 0,
            "fingerprint": "test",
        },
    )
    assert result["can_submit"] is True
    assert result["available_schedule_slot_count"] == 4
    assert [batch["scheduled_at"] for batch in result["batches"]] == [
        datetime(2026, 7, 17, 11, 0, tzinfo=UTC),
        datetime(2026, 7, 18, 1, 0, tzinfo=UTC),
        datetime(2026, 7, 18, 7, 0, tzinfo=UTC),
        datetime(2026, 7, 18, 11, 0, tzinfo=UTC),
    ]
    assert not any("必须全部晚于当前时间" in error for error in result["errors"])
    assert any("已自动作废 2 个" in warning for warning in result["warnings"])


def test_scheduled_times_only_accept_whole_hours():
    try:
        AdBuildPreviewRequest(
            project_id=PROJECT_ID,
            selection_mode="random",
            quantity=1,
            execution_mode="scheduled",
            scheduled_dates=["2026-07-18"],
            scheduled_times=["09:30"],
        )
    except ValueError as exc:
        assert "仅支持整点" in str(exc)
    else:
        raise AssertionError("expected non-hour schedule time to be rejected")


def test_finite_schedule_blocks_when_date_time_slots_are_not_enough():
    rows = [account(index) for index in range(1, 101)]
    result = preview(
        rows,
        quantity=100,
        execution_mode="scheduled",
        scheduled_dates=["2026-07-15"],
        scheduled_times=["10:00", "14:00", "18:00"],
        batch_size=10,
    )
    assert result["can_submit"] is False
    assert result["batch_count"] == 3
    assert any("需要 10 批" in error for error in result["errors"])


def test_unlimited_schedule_repeats_selected_times_until_queue_is_complete():
    rows = [account(index) for index in range(1, 6)]
    result = preview(
        rows,
        quantity=5,
        execution_mode="scheduled",
        scheduled_dates=["2026-07-14"],
        scheduled_times=["08:00", "10:00"],
        schedule_unlimited=True,
        batch_size=1,
    )
    assert result["can_submit"] is True
    assert result["batch_count"] == 5
    assert result["available_schedule_slot_count"] is None
    assert [batch["scheduled_at"] for batch in result["batches"]] == [
        datetime(2026, 7, 14, 2, 0, tzinfo=UTC),
        datetime(2026, 7, 15, 0, 0, tzinfo=UTC),
        datetime(2026, 7, 15, 2, 0, tzinfo=UTC),
        datetime(2026, 7, 16, 0, 0, tzinfo=UTC),
        datetime(2026, 7, 16, 2, 0, tzinfo=UTC),
    ]


def test_missing_required_page_configuration_blocks_submission():
    row = account(1, promotion_page=None)
    result = preview(
        [row],
        selection_mode="specified_accounts",
        account_selectors=["账户1"],
        quantity=None,
    )
    assert result["can_submit"] is False
    assert result["blocked_count"] == 1
    assert "缺少推广页面" in account_configuration_issues(row, require_empty=False)


def test_material_library_is_required_by_account_workflow():
    payload = AdBuildPreviewRequest(
        project_id=PROJECT_ID,
        selection_mode="random",
        quantity=1,
    )
    result = build_ad_build_preview([account(1)], payload, material_keyword_count=0, writes_enabled=False, now=NOW)
    assert result["can_submit"] is False
    assert any("物料中心" in error for error in result["errors"])


def test_preembedded_keywords_never_receive_a_url():
    row = account(1, account_type="一跳预埋户", link=None)
    overrides = account_workflow_overrides(row)
    steps = account_workflow_steps(row)
    assert overrides["skip_campaign_and_adgroup_creation"] is True
    assert overrides["campaign_action"] == "update_existing_to_current_template"
    assert overrides["adgroup_action"] == "reuse_existing_no_create"
    assert overrides["keyword_url_mode"] == "none"
    assert overrides["keyword_landing_url"] is None
    assert overrides["creative_targeting"] == {
        "scope": "keyword_uploaded_existing_adgroups_only",
        "adgroup_ids_source": "keyword_upload_result.successful_adgroup_ids",
        "requires_uploaded_keyword_count": True,
        "exclude_other_existing_adgroups": True,
        "distribution": "round_robin_across_target_adgroups",
        "empty_scope_action": "block_without_creative_write",
    }
    assert account_configuration_issues(row, require_empty=False) == []
    assert [step["key"] for step in steps] == [
        "account_budget",
        "account_regions",
        "campaign",
        "ocpc",
        "keywords",
        "audience",
        "creative",
    ]
    assert next(step for step in steps if step["key"] == "campaign")["label"] == "更新已有计划"
    assert "本次实际上传成功关键词的已有单元" in next(
        step for step in steps if step["key"] == "creative"
    )["detail"]
    assert [step["key"] for step in steps].index("ocpc") < [step["key"] for step in steps].index("keywords")


def test_preembedded_creatives_only_target_units_with_uploaded_keywords():
    assert keyword_uploaded_adgroup_ids([
        {"adgroup_id": 101, "uploaded_keyword_count": 12},
        {"adgroup_id": 102, "uploaded_keyword_count": 0},
        {"adgroup_id": 103, "uploaded_keyword_count": 3},
        {"adgroup_id": 101, "uploaded_keyword_count": 2},
    ]) == [101, 103]


def test_uploaded_keyword_result_rejects_missing_target_unit():
    try:
        keyword_uploaded_adgroup_ids([{"uploaded_keyword_count": 1}])
    except ValueError as exc:
        assert "adgroup_id" in str(exc)
    else:
        raise AssertionError("关键词上传成功但缺少单元ID时必须阻断创意新建")


def test_one_hop_empty_accounts_never_receive_a_keyword_url():
    row = account(2, account_type="一跳空户", link="https://example.com/creative-page")
    overrides = account_workflow_overrides(row)
    assert overrides["skip_campaign_and_adgroup_creation"] is False
    assert overrides["keyword_url_mode"] == "none"
    assert overrides["keyword_landing_url"] is None
    assert build_keyword_tracking_url(row, "%E6%B5%8B%E8%AF%95%E5%85%B3%E9%94%AE%E8%AF%8D") is None
    assert account_configuration_issues(row, require_empty=False) == []


def test_second_hop_keyword_url_encodes_literal_keyword_and_preserves_query_and_fragment():
    row = account(
        3,
        account_type="二跳账户",
        link=(
            "https://example.com/page?source=search&userid={userid}"
            "&keywordid={keywordid}&kw_enc_utf8={kw_enc_utf8}#content"
        ),
    )
    expected = (
        "https://example.com/page?source=search&zhanghuid=3"
        "&keyword=%E5%A4%A7%E5%94%90%E8%BE%A3%E5%A6%88%E5%87%8F%E8%82%A5"
        "&e_adposition={adposition}#content"
    )
    assert build_keyword_tracking_url(
        row,
        "%E5%A4%A7%E5%94%90%E8%BE%A3%E5%A6%88%E5%87%8F%E8%82%A5",
    ) == expected
    assert "userid=" not in expected
    assert "keywordid=" not in expected
    assert "kw_enc_utf8=" not in expected
    overrides = account_workflow_overrides(row)
    assert overrides["keyword_url_mode"] == "per_keyword_utf8_encoded"
    assert overrides["keyword_landing_url"] is None
    assert overrides["keyword_url_generation"]["account_parameter"] == "zhanghuid"
    assert overrides["keyword_url_generation"]["position_macro"] == "{adposition}"
    assert overrides["keyword_url_generation"]["encoded_value_source"] == "material_keywords.keyword_utf8_encoded"


def test_online_window_is_inverted_to_baidu_pause_schedule():
    schedule = build_plan_pause_schedule(True, [1], 8, 23)
    assert schedule[:2] == [
        {"weekDay": 1, "startHour": 0, "endHour": 8},
        {"weekDay": 1, "startHour": 23, "endHour": 24},
    ]
    assert schedule[2] == {"weekDay": 2, "startHour": 0, "endHour": 24}
    assert build_plan_pause_schedule(False, [1, 2, 3, 4, 5, 6, 7], 8, 23) == []


def test_independent_online_windows_are_inverted_without_losing_gaps():
    schedule = build_plan_pause_schedule_from_windows(True, [
        {"weekDay": 1, "startHour": 8, "endHour": 12},
        {"weekDay": 1, "startHour": 14, "endHour": 18},
        {"weekDay": 2, "startHour": 9, "endHour": 24},
    ])

    assert schedule[:4] == [
        {"weekDay": 1, "startHour": 0, "endHour": 8},
        {"weekDay": 1, "startHour": 12, "endHour": 14},
        {"weekDay": 1, "startHour": 18, "endHour": 24},
        {"weekDay": 2, "startHour": 0, "endHour": 9},
    ]


def test_ad_build_preview_uses_weekly_grid_windows_for_baidu_pause_schedule():
    result = preview(
        [account(1), account(2)],
        online_schedule_enabled=True,
        online_schedule=[
            {"weekDay": 1, "startHour": 8, "endHour": 12},
            {"weekDay": 1, "startHour": 14, "endHour": 18},
            {"weekDay": 2, "startHour": 9, "endHour": 24},
        ],
    )

    assert result["build_settings"]["online_schedule"] == [
        {"weekDay": 1, "startHour": 8, "endHour": 12},
        {"weekDay": 1, "startHour": 14, "endHour": 18},
        {"weekDay": 2, "startHour": 9, "endHour": 24},
    ]
    assert result["build_settings"]["plan_pause_schedule"][:4] == [
        {"weekDay": 1, "startHour": 0, "endHour": 8},
        {"weekDay": 1, "startHour": 12, "endHour": 14},
        {"weekDay": 1, "startHour": 18, "endHour": 24},
        {"weekDay": 2, "startHour": 0, "endHour": 9},
    ]


def test_online_window_defaults_to_08_through_24_and_does_not_add_an_end_pause():
    payload = AdBuildPreviewRequest(
        project_id=PROJECT_ID,
        selection_mode="random",
        quantity=1,
    )

    assert payload.online_start_hour == 8
    assert payload.online_end_hour == 24
    assert build_plan_pause_schedule(True, [1], payload.online_start_hour, payload.online_end_hour)[:2] == [
        {"weekDay": 1, "startHour": 0, "endHour": 8},
        {"weekDay": 2, "startHour": 0, "endHour": 24},
    ]


def test_cross_midnight_window_carries_selected_day_into_the_next_day():
    payload = AdBuildPreviewRequest(
        project_id=PROJECT_ID,
        selection_mode="random",
        quantity=1,
        online_schedule_enabled=True,
        online_weekdays=[1],
        online_start_hour=12,
        online_end_hour=2,
    )

    assert build_plan_pause_schedule(True, payload.online_weekdays, 12, 2) == [
        {"weekDay": 1, "startHour": 0, "endHour": 12},
        {"weekDay": 2, "startHour": 2, "endHour": 24},
        {"weekDay": 3, "startHour": 0, "endHour": 24},
        {"weekDay": 4, "startHour": 0, "endHour": 24},
        {"weekDay": 5, "startHour": 0, "endHour": 24},
        {"weekDay": 6, "startHour": 0, "endHour": 24},
        {"weekDay": 7, "startHour": 0, "endHour": 24},
    ]


def test_cross_midnight_window_rolls_sunday_into_monday():
    schedule = build_plan_pause_schedule(True, [7], 12, 2)

    assert schedule[0] == {"weekDay": 1, "startHour": 2, "endHour": 24}
    assert schedule[-1] == {"weekDay": 7, "startHour": 0, "endHour": 12}


def test_all_days_cross_midnight_window_pauses_only_the_daytime_gap():
    schedule = build_plan_pause_schedule(True, [1, 2, 3, 4, 5, 6, 7], 12, 2)

    assert schedule == [
        {"weekDay": weekday, "startHour": 2, "endHour": 12}
        for weekday in range(1, 8)
    ]


def test_online_window_rejects_equal_start_and_end_hours():
    with pytest.raises(ValueError, match="开始和结束时间不能相同"):
        AdBuildPreviewRequest(
            project_id=PROJECT_ID,
            selection_mode="random",
            quantity=1,
            online_schedule_enabled=True,
            online_start_hour=12,
            online_end_hour=12,
        )


def test_project_is_created_before_keywords_for_regular_accounts():
    steps = account_workflow_steps(account(1))
    keys = [step["key"] for step in steps]
    assert keys.index("ocpc") < keys.index("keywords")


def test_creative_readback_key_matches_baidu_merged_descriptions():
    submitted = _creative_readback_key(1001, "标题", "描述一", "描述二")
    read_back = _creative_readback_key(1001, "标题", "描述一描述二", "")
    assert submitted == read_back
