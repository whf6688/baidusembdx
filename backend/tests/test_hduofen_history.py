from io import BytesIO

from openpyxl import Workbook

from search_console.hduofen_history import parse_history_filename, read_history_workbook


def _write_workbook(path, rows):
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    content = BytesIO()
    workbook.save(content)
    path.write_bytes(content.getvalue())


def test_parse_history_filename_supports_both_export_patterns(tmp_path):
    visitors = parse_history_filename(
        tmp_path / "实时访问详情260708_00_00_00至260708_23_59_59.xls"
    )
    conversions = parse_history_filename(
        tmp_path / "获客助手实时转化详情2026-07-08至2026-07-08.xls"
    )

    assert visitors.source_type == "visitors"
    assert visitors.start_at.isoformat() == "2026-07-08T00:00:00+08:00"
    assert conversions.source_type == "conversions"
    assert conversions.end_at.isoformat() == "2026-07-08T23:59:59+08:00"


def test_read_history_visitors_maps_account_remark_and_keyword(tmp_path):
    path = tmp_path / "实时访问详情260708_00_00_00至260708_23_59_59.xls"
    _write_workbook(path, [
        ["访问链接", "落地页备注", "追踪关键词", "访问时间"],
        ["https://example.test/?zhanghuid=123", "账户A", "减肥", "2026-07-08 12:30:00"],
    ])

    dataset = read_history_workbook(parse_history_filename(path))

    assert len(dataset.records) == 1
    assert dataset.records[0]["account_remark"] == "账户A"
    assert dataset.records[0]["keyword_encoded"] == "减肥"
    assert dataset.records[0]["start_time"] == "2026-07-08T12:30:00+08:00"
    assert dataset.records[0]["history_exclusion_reason"] is None
    assert dataset.outside_filename_window == 0


def test_history_row_outside_filename_range_is_quarantined(tmp_path):
    path = tmp_path / "复制实时详情260708_00_00_00至260708_23_59_59.xls"
    _write_workbook(path, [
        ["访问链接", "备注", "追踪关键词", "复制时间"],
        ["https://example.test/", "账户A", "减肥", "2026-07-09 00:00:01"],
    ])

    dataset = read_history_workbook(parse_history_filename(path))

    assert dataset.outside_filename_window == 1
    assert dataset.records[0]["history_exclusion_reason"] == "outside_filename_window"
