import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from .creatives import (
    CREATIVE_SEGMENT_REJECTION_THRESHOLD,
    SECOND_HOP_REJECTION_THRESHOLD,
)
from .models import CreativeCombination, CreativeSegment


def ensure_creative_center_combination(
    db: Session,
    project_id: uuid.UUID,
    candidate: Any,
    combination_map: dict[str, CreativeCombination],
) -> CreativeCombination:
    """Register a generated combination in the creative center before it is assigned."""
    existing = combination_map.get(candidate.combination_hash)
    if existing is not None:
        return existing
    combination = CreativeCombination(
        id=uuid.uuid4(),
        project_id=project_id,
        title_segment_id=candidate.title_id,
        description1_segment_id=candidate.description1_id,
        description2_segment_id=candidate.description2_id,
        combination_hash=candidate.combination_hash,
    )
    db.add(combination)
    # CreativeAssignment stores only combination_id and has no ORM relationship.
    # Flush the creative-center parent explicitly before creating the child row.
    db.flush([combination])
    combination_map[candidate.combination_hash] = combination
    return combination


def record_second_hop_creative_rejection(
    db: Session,
    combination: CreativeCombination,
) -> tuple[bool, int]:
    """Record one second-hop rejection against the combination and its source segments."""
    combination.rejection_count = int(combination.rejection_count or 0) + 1
    combination_blacklisted = False
    if (
        combination.rejection_count >= SECOND_HOP_REJECTION_THRESHOLD
        and not combination.is_blacklisted
    ):
        combination.is_blacklisted = True
        combination.blacklist_reason = "二跳账户同一组合累计5次审核不通过"
        combination.blacklisted_at = datetime.now(UTC)
        combination_blacklisted = True

    segment_blacklisted_count = 0
    segment_ids = {
        combination.title_segment_id,
        combination.description1_segment_id,
        combination.description2_segment_id,
    }
    for segment_id in segment_ids - {None}:
        segment = db.get(CreativeSegment, segment_id)
        if segment is None:
            continue
        segment.rejection_count = int(segment.rejection_count or 0) + 1
        if (
            segment.rejection_count >= CREATIVE_SEGMENT_REJECTION_THRESHOLD
            and not segment.is_blacklisted
        ):
            segment.is_blacklisted = True
            segment.blacklist_reason = "二跳账户创意原料累计50次审核不通过"
            segment_blacklisted_count += 1

    return combination_blacklisted, segment_blacklisted_count
