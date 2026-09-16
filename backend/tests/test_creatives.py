import uuid
from types import SimpleNamespace

import pytest

from search_console.creatives import (
    CREATIVE_SEGMENT_REJECTION_THRESHOLD,
    SECOND_HOP_REJECTION_THRESHOLD,
    baidu_text_bytes,
    creative_combination_hash,
    creative_pool_summary,
    creative_review_action,
    extract_main_reason,
    select_random_creative_combinations,
    validate_segment_content,
)
from search_console.models import Account
from search_console.schemas import CreativeSegmentBulkCreate
from search_console.worker import _read_creative_review_chunk


def segment(segment_type: str, content: str, *, blacklisted: bool = False):
    return SimpleNamespace(
        id=uuid.uuid4(),
        segment_type=segment_type,
        content=content,
        is_blacklisted=blacklisted,
    )


def test_creative_segment_validation_uses_baidu_byte_rule():
    assert baidu_text_bytes("健康ABC") == 7
    assert validate_segment_content("title", "健康减重科学方法") == "健康减重科学方法"
    with pytest.raises(ValueError, match="不允许"):
        validate_segment_content("title", "健康 减重科学方法")


def test_bulk_segment_input_is_unique_case_insensitively():
    payload = CreativeSegmentBulkCreate(
        segment_type="title",
        contents=["HealthyWeightPlan", "healthyweightplan", "科学减重健康管理"],
    )
    assert payload.contents == ["HealthyWeightPlan", "科学减重健康管理"]


def test_bulk_segment_validation_reports_input_line_numbers():
    with pytest.raises(ValueError, match="第1行.*第2行"):
        CreativeSegmentBulkCreate(
            segment_type="title",
            contents=["【减肥】科学方法", "带 空格的减重方法"],
        )


def test_random_combinations_include_empty_description2_and_are_stable():
    segments = [
        *[segment("title", f"科学减重方案第{i}版") for i in range(10)],
        *[segment("description1", f"健康管理方法帮助控制体重第{i}版") for i in range(5)],
    ]
    first = select_random_creative_combinations(segments, set(), seed="same", limit=50)
    second = select_random_creative_combinations(segments, set(), seed="same", limit=50)
    assert len(first) == 50
    assert [row.combination_hash for row in first] == [row.combination_hash for row in second]
    assert all(row.description2 == "" for row in first)


def test_blacklisted_combination_is_never_selected_again():
    title = segment("title", "科学减重健康方案")
    description1 = segment("description1", "合理膳食运动管理健康体重")
    description2 = segment("description2", "立即了解科学健康管理方案")
    blocked = creative_combination_hash(title.id, description1.id, None)
    selected = select_random_creative_combinations(
        [title, description1, description2],
        {blocked},
        seed="blocked",
        limit=50,
    )
    assert len(selected) == 1
    assert selected[0].description2 == description2.content
    assert selected[0].combination_hash != blocked


def test_pool_summary_counts_description2_empty_as_an_option():
    rows = [
        segment("title", "科学减重健康方案"),
        segment("description1", "合理膳食运动管理健康体重"),
        segment("description2", "立即了解科学健康管理方案"),
    ]
    summary = creative_pool_summary(rows, set())
    assert summary["total_combination_count"] == 2
    assert summary["available_combination_count"] == 2


def test_extract_main_reason_three_from_offline_reasons():
    assert extract_main_reason({
        "offlineReasons": [{"mainReason": "3", "detailReason": "审核拒绝原因"}],
    }) == ("3", "审核拒绝原因")


def test_review_policy_only_blacklists_repeated_second_hop_rejections():
    assert SECOND_HOP_REJECTION_THRESHOLD == 5
    assert CREATIVE_SEGMENT_REJECTION_THRESHOLD == 50
    one_hop = creative_review_action("一跳空户", "3", current_rejections=10)
    assert one_hop == {
        "action": "delete_and_replenish_allow_resubmit",
        "increment_rejection": False,
        "blacklist": False,
    }
    second_hop = creative_review_action("二跳账户", "3", current_rejections=3)
    assert second_hop["action"] == "record_rejection_delete_and_replenish"
    assert second_hop["blacklist"] is False
    assert creative_review_action("二跳账户", "3", current_rejections=4)["blacklist"] is True


def test_creative_review_read_splits_and_skips_missing_ids():
    class FakeClient:
        def execute_read(self, context, service, payload):
            ids = payload["ids"]
            if 22 in ids:
                raise RuntimeError("百度返回业务错误：90114")
            return {
                "body": {
                    "data": [
                        {"creativeId": creative_id, "status": 51}
                        for creative_id in ids
                    ]
                }
            }

    account = Account(
        baidu_account_id=1001,
        login_name="account",
        manager_login_name="manager",
    )
    rows = _read_creative_review_chunk(
        FakeClient(), account, "task", [11, 22, 33], "0"
    )
    assert [row["creativeId"] for row in rows] == [11, 33]
