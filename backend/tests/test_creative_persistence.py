import uuid
from types import SimpleNamespace

from search_console.creative_persistence import (
    ensure_creative_center_combination,
    record_second_hop_creative_rejection,
)
from search_console.models import CreativeSegment


class FakeSession:
    def __init__(self):
        self.calls = []

    def add(self, row):
        self.calls.append(("add", row))

    def flush(self, rows):
        self.calls.append(("flush", list(rows)))


def candidate():
    return SimpleNamespace(
        combination_hash="hash-1",
        title_id=uuid.uuid4(),
        description1_id=uuid.uuid4(),
        description2_id=uuid.uuid4(),
    )


def test_new_combination_is_registered_and_flushed_before_assignment_use():
    db = FakeSession()
    rows = {}
    row = ensure_creative_center_combination(db, uuid.uuid4(), candidate(), rows)
    assert [name for name, _ in db.calls] == ["add", "flush"]
    assert db.calls[1][1] == [row]
    assert rows["hash-1"] is row


def test_registered_combination_is_reused_without_another_write():
    db = FakeSession()
    existing = SimpleNamespace(combination_hash="hash-1")
    rows = {"hash-1": existing}
    assert ensure_creative_center_combination(db, uuid.uuid4(), candidate(), rows) is existing
    assert db.calls == []


class RejectionSession:
    def __init__(self, segments):
        self.segments = {row.id: row for row in segments}

    def get(self, model, row_id):
        assert model is CreativeSegment
        return self.segments.get(row_id)


def test_second_hop_rejection_increments_combination_and_each_non_empty_segment():
    title = SimpleNamespace(id=uuid.uuid4(), rejection_count=0, is_blacklisted=False)
    description1 = SimpleNamespace(id=uuid.uuid4(), rejection_count=2, is_blacklisted=False)
    combination = SimpleNamespace(
        title_segment_id=title.id,
        description1_segment_id=description1.id,
        description2_segment_id=None,
        rejection_count=0,
        is_blacklisted=False,
        blacklist_reason=None,
        blacklisted_at=None,
    )

    combination_blacklisted, segment_blacklisted_count = (
        record_second_hop_creative_rejection(
            RejectionSession([title, description1]),
            combination,
        )
    )

    assert combination.rejection_count == 1
    assert combination.is_blacklisted is False
    assert combination_blacklisted is False
    assert title.rejection_count == 1
    assert description1.rejection_count == 3
    assert segment_blacklisted_count == 0


def test_second_hop_rejection_applies_combination_and_segment_thresholds():
    title = SimpleNamespace(
        id=uuid.uuid4(),
        rejection_count=49,
        is_blacklisted=False,
        blacklist_reason=None,
    )
    description1 = SimpleNamespace(
        id=uuid.uuid4(),
        rejection_count=49,
        is_blacklisted=False,
        blacklist_reason=None,
    )
    combination = SimpleNamespace(
        title_segment_id=title.id,
        description1_segment_id=description1.id,
        description2_segment_id=None,
        rejection_count=4,
        is_blacklisted=False,
        blacklist_reason=None,
        blacklisted_at=None,
    )

    combination_blacklisted, segment_blacklisted_count = (
        record_second_hop_creative_rejection(
            RejectionSession([title, description1]),
            combination,
        )
    )

    assert combination.rejection_count == 5
    assert combination.is_blacklisted is True
    assert combination.blacklisted_at is not None
    assert combination_blacklisted is True
    assert title.rejection_count == 50
    assert description1.rejection_count == 50
    assert title.is_blacklisted is True
    assert description1.is_blacklisted is True
    assert segment_blacklisted_count == 2
