from datetime import UTC, datetime, timedelta

from search_console.models import SyncWatermark
from search_console.worker import _watermarks_are_fresh


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _DB:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self, _statement):
        return _Rows(self.rows)


def _watermark(source: str, status: str, captured_at: datetime) -> SyncWatermark:
    return SyncWatermark(
        source=source,
        scope="project-id",
        status=status,
        snapshot_at=captured_at,
    )


def test_partial_account_report_does_not_become_a_project_level_failure():
    now = datetime(2026, 9, 17, 8, 0, tzinfo=UTC)
    healthy, details = _watermarks_are_fresh(
        _DB([_watermark("baidu_account_report", "failed", now - timedelta(minutes=5))]),
        "project-id",
        sources=("baidu_account_report",),
        now=now,
    )

    assert healthy is True
    assert details["baidu_account_report"]["status"] == "partial"
    assert details["baidu_account_report"]["protection_scope"] == "account"


def test_systemic_hduofen_failure_still_pauses_the_related_strategy():
    now = datetime(2026, 9, 17, 8, 0, tzinfo=UTC)
    healthy, details = _watermarks_are_fresh(
        _DB([_watermark("hduofen_capture", "failed", now - timedelta(minutes=5))]),
        "project-id",
        sources=("hduofen_capture",),
        now=now,
    )

    assert healthy is False
    assert details["hduofen_capture"]["status"] == "failed"
    assert details["hduofen_capture"]["protection_scope"] == "project"
