from datetime import UTC, date, datetime

from search_console.tracking import _deduplicate_records, _selected_query_bounds


def test_deduplicate_records_uses_stable_id_and_keeps_latest_value():
    records = [
        {"id": "visit-1", "complete_url": "https://example.test/old"},
        {"id": "visit-1", "complete_url": "https://example.test/new"},
        {"id": "visit-2", "complete_url": "https://example.test/other"},
    ]

    result = _deduplicate_records(records)

    assert len(result) == 2
    assert result[0]["complete_url"] == "https://example.test/new"


def test_deduplicate_records_hashes_rows_without_identifiers():
    record = {"complete_url": "https://example.test/page", "city": "北京"}

    result = _deduplicate_records([record, dict(record)])

    assert result == [record]


def test_deduplicate_records_does_not_treat_shared_user_uuid_as_event_id():
    records = [
        {"user_uuid": "shared", "sessions": "session-1"},
        {"user_uuid": "shared", "sessions": "session-2"},
    ]

    assert _deduplicate_records(records) == records


def test_selected_query_bounds_use_full_historical_days():
    captured_at = datetime(2026, 7, 14, 3, 30, tzinfo=UTC)

    result = _selected_query_bounds(
        captured_at,
        date(2026, 7, 10),
        date(2026, 7, 12),
    )

    assert result == ("2026-07-10 00:00:00", "2026-07-12 23:59:59")


def test_selected_query_bounds_cap_today_at_capture_time():
    captured_at = datetime(2026, 7, 14, 3, 30, 45, tzinfo=UTC)

    result = _selected_query_bounds(
        captured_at,
        date(2026, 7, 14),
        date(2026, 7, 14),
    )

    assert result == ("2026-07-14 00:00:00", "2026-07-14 11:30:45")
