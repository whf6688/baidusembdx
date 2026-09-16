from datetime import UTC, datetime
from types import SimpleNamespace

from search_console.models import AccountType
from search_console.tracking_ingestion import (
    event_time_for_source,
    extract_account_remark,
    extract_hduofen_url_fields,
    extract_tracking_keyword,
    get_existing_tracking_material_keywords,
    is_gibberish_tracking_keyword,
    resolve_hduofen_account,
    source_event_id,
)


def test_extract_hduofen_url_fields_uses_zhanghuid_and_decodes_keyword():
    account_id, url_keyword = extract_hduofen_url_fields(
        "https://example.test/page?zhanghuid=81451518&keyword=%E8%B4%BE%E7%8E%B2%E5%87%8F%E8%82%A5"
    )

    assert account_id == 81451518
    assert url_keyword == "贾玲减肥"


def test_extract_hduofen_url_fields_stops_at_malformed_second_question_mark():
    account_id, url_keyword = extract_hduofen_url_fields(
        "https://example.test/page?zhanghuid=k2026051908?bd_vid=0"
        "&keyword=减肥方法?extra=ignored"
    )

    assert account_id == "k2026051908"
    assert url_keyword == "减肥方法"


def test_tracking_keyword_only_uses_tracking_field_not_search_term():
    assert extract_tracking_keyword({"keyword_encoded": " 贾玲减肥 ", "serach_text": "搜索词"}) == "贾玲减肥"
    assert extract_tracking_keyword({"keyword_encoded": "", "serach_text": "搜索词"}) is None


def test_gibberish_tracking_keyword_detects_control_characters():
    assert is_gibberish_tracking_keyword("正常减肥关键词") is False
    assert is_gibberish_tracking_keyword("乱码\u0080关键词") is True
    assert is_gibberish_tracking_keyword("锟斤拷关键词") is True


def test_hduofen_tracking_never_creates_material_keywords():
    existing = SimpleNamespace(keyword_text="已有关键词")

    class ExistingRows:
        def all(self):
            return [existing]

    class ReadOnlySession:
        def __init__(self):
            self.add_called = False

        def scalars(self, _statement):
            return ExistingRows()

        def add(self, _row):
            self.add_called = True

    session = ReadOnlySession()
    rows, created = get_existing_tracking_material_keywords(
        session, "project-id", {"已有关键词", "好多粉新关键词"}
    )

    assert rows == {"已有关键词": existing}
    assert created == 0
    assert session.add_called is False


def test_deleted_marker_keyword_links_to_existing_normalized_material():
    existing = SimpleNamespace(keyword_text="减肥方法")

    class ExistingRows:
        def all(self):
            return [existing]

    class ReadOnlySession:
        def scalars(self, _statement):
            return ExistingRows()

    rows, created = get_existing_tracking_material_keywords(
        ReadOnlySession(), "project-id", {"减肥方法[已删除]"}
    )

    assert rows == {"减肥方法[已删除]": existing}
    assert created == 0


def test_conversion_time_prefers_add_time_in_milliseconds():
    fallback = datetime(2026, 7, 14, tzinfo=UTC)

    result = event_time_for_source(
        "conversions",
        {"isAdd_time": 1783962020000, "start_time": 1783962004000},
        fallback,
    )

    assert result == datetime.fromtimestamp(1783962020, UTC)


def test_source_event_id_falls_back_to_stable_payload_hash():
    first = source_event_id({"user_uuid": "shared", "sessions": "session-1"})
    second = source_event_id({"user_uuid": "shared", "sessions": "session-2"})

    assert first != second


def test_account_resolution_prefers_zhanghuid_then_exact_remark():
    by_id = {
        123: SimpleNamespace(baidu_account_id=123, login_name="账户A", account_type=AccountType.SECOND_HOP),
        456: SimpleNamespace(baidu_account_id=456, login_name="账户B", account_type=AccountType.EMPTY),
    }
    by_name = {"账户A": [by_id[123]], "账户B": [by_id[456]]}

    account, account_id, reason = resolve_hduofen_account(
        {
            "complete_url": "https://example.test/?zhanghuid=123",
            "account_remark": "账户B",
        },
        by_id,
        by_name,
    )
    assert account is by_id[123]
    assert account_id == 123
    assert reason is None

    account, account_id, reason = resolve_hduofen_account(
        {"complete_url": "https://example.test/", "account_remark": " 账户B "},
        by_id,
        by_name,
    )
    assert extract_account_remark({"account_remark": " 账户B "}) == "账户B"
    assert account is by_id[456]
    assert account_id == 456
    assert reason is None


def test_explicit_remark_mapping_is_used_only_without_zhanghuid():
    direct = SimpleNamespace(baidu_account_id=123, login_name="二跳账户")
    mapped = SimpleNamespace(baidu_account_id=456, login_name="baidu-QWW迈禾ICP390b0929")
    remark_map = {"qww迈禾icp390b0929": mapped}

    account, account_id, reason = resolve_hduofen_account(
        {
            "complete_url": "https://example.test/?zhanghuid=123",
            "account_remark": "QWW迈禾ICP390b0929",
        },
        {123: direct},
        {},
        {},
        remark_map,
    )
    assert account is direct
    assert account_id == 123
    assert reason is None

    account, account_id, reason = resolve_hduofen_account(
        {
            "complete_url": "https://example.test/",
            "account_remark": " QWW迈禾ICP390b0929 ",
        },
        {},
        {},
        {},
        remark_map,
    )
    assert account is mapped
    assert account_id == 456
    assert reason is None


def test_ambiguous_account_remark_is_not_guessed():
    duplicate = [
        SimpleNamespace(baidu_account_id=1, login_name="重复账户"),
        SimpleNamespace(baidu_account_id=2, login_name="重复账户"),
    ]

    account, account_id, reason = resolve_hduofen_account(
        {"complete_url": "https://example.test/", "account_remark": "重复账户"},
        {},
        {"重复账户": duplicate},
    )

    assert account is None
    assert account_id is None
    assert reason == "remark_account_ambiguous"


def test_custom_zhanghuid_mapping_is_checked_before_direct_account_id():
    mapped = SimpleNamespace(baidu_account_id=456, login_name="表内账户")

    account, account_id, reason = resolve_hduofen_account(
        {"complete_url": "https://example.test/?zhanghuid=k2026042201"},
        {},
        {},
        {"k2026042201": mapped},
    )

    assert account is mapped
    assert account_id == 456
    assert reason is None


def test_numeric_zhanghuid_prefers_direct_account_before_custom_mapping():
    direct = SimpleNamespace(baidu_account_id=123, login_name="二跳账户")
    custom = SimpleNamespace(baidu_account_id=456, login_name="一跳账户")

    account, account_id, reason = resolve_hduofen_account(
        {"complete_url": "https://example.test/?zhanghuid=123"},
        {123: direct},
        {},
        {"123": custom},
    )

    assert account is direct
    assert account_id == 123
    assert reason is None


def test_truncated_remark_uses_unique_login_name_prefix():
    expected = SimpleNamespace(
        baidu_account_id=123,
        login_name="baidu-wz-超群CWR45934爆量",
        account_type=AccountType.SECOND_HOP,
    )

    account, account_id, reason = resolve_hduofen_account(
        {
            "complete_url": "https://example.test/",
            "account_remark": "baidu-wz-超群CWR45934爆",
        },
        {},
        {expected.login_name: [expected]},
    )

    assert account is expected
    assert account_id == 123
    assert reason is None


def test_truncated_remark_with_multiple_prefix_candidates_is_not_guessed():
    candidates = [
        SimpleNamespace(
            baidu_account_id=1,
            login_name="baidu-zjgjxj盈欣鹤MPZ46061国际",
            account_type=AccountType.SECOND_HOP,
        ),
        SimpleNamespace(
            baidu_account_id=2,
            login_name="baidu-zjgjxj盈欣鹤MPZ46062国际",
            account_type=AccountType.SECOND_HOP,
        ),
    ]

    account, account_id, reason = resolve_hduofen_account(
        {
            "complete_url": "https://example.test/",
            "account_remark": "baidu-zjgjxj盈欣鹤MPZ46",
        },
        {},
        {candidate.login_name: [candidate] for candidate in candidates},
    )

    assert account is None
    assert account_id is None
    assert reason == "remark_account_ambiguous"


def test_jimuyu_remark_only_matches_second_hop_prefix():
    second_hop = SimpleNamespace(
        baidu_account_id=123,
        login_name="K基木鱼-减肥账户001",
        account_type=AccountType.SECOND_HOP,
    )
    first_hop = SimpleNamespace(
        baidu_account_id=456,
        login_name="K基木鱼-减肥账户002",
        account_type=AccountType.PREEMBEDDED,
    )

    account, account_id, reason = resolve_hduofen_account(
        {
            "complete_url": "https://example.test/",
            "account_remark": "K基木鱼-减肥账户00",
        },
        {},
        {
            second_hop.login_name: [second_hop],
            first_hop.login_name: [first_hop],
        },
    )

    assert account is second_hop
    assert account_id == 123
    assert reason is None
