import hashlib
import math
import random
import re
from dataclasses import dataclass
from typing import Iterable


CREATIVE_COUNT_PER_ACCOUNT = 50
SECOND_HOP_REJECTION_THRESHOLD = 5
CREATIVE_SEGMENT_REJECTION_THRESHOLD = 50
SEGMENT_TYPES = ("title", "description1", "description2")
SEGMENT_LABELS = {
    "title": "创意标题",
    "description1": "创意描述1",
    "description2": "创意描述2",
}
SEGMENT_BYTE_LIMITS = {
    "title": (9, 50),
    "description1": (9, 80),
    "description2": (1, 80),
}
FORBIDDEN_CREATIVE_TEXT = re.compile(r"[<>_「」［］〈〉【】\[\]‘’“”。＋，－？＿\s]")


def baidu_text_bytes(value: str) -> int:
    """Apply Baidu's documented creative byte rule; wildcard contents do not count."""
    without_wildcards = re.sub(r"\{[^{}]+\}", "", value)
    return sum(1 if ord(char) < 128 else 2 for char in without_wildcards)


def validate_segment_content(segment_type: str, content: str) -> str:
    if segment_type not in SEGMENT_TYPES:
        raise ValueError("创意段类型不正确")
    normalized = str(content or "").strip()
    if not normalized:
        raise ValueError(f"{SEGMENT_LABELS[segment_type]}不能为空")
    if FORBIDDEN_CREATIVE_TEXT.search(normalized):
        raise ValueError(f"{SEGMENT_LABELS[segment_type]}包含百度不允许的空格或特殊符号")
    minimum, maximum = SEGMENT_BYTE_LIMITS[segment_type]
    length = baidu_text_bytes(normalized)
    if length < minimum or length > maximum:
        raise ValueError(f"{SEGMENT_LABELS[segment_type]}按百度字节规则必须在 {minimum} 到 {maximum} 之间，当前为 {length}")
    return normalized


def creative_combination_hash(title_id, description1_id, description2_id=None) -> str:
    canonical = f"{title_id}|{description1_id}|{description2_id or ''}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CreativeCandidate:
    combination_hash: str
    title_id: object
    description1_id: object
    description2_id: object | None
    title: str
    description1: str
    description2: str


def creative_pool_summary(segments: Iterable, blacklisted_hashes: Iterable[str]) -> dict:
    active = [row for row in segments if not row.is_blacklisted]
    grouped = {
        segment_type: sorted((row for row in active if row.segment_type == segment_type), key=lambda row: str(row.id))
        for segment_type in SEGMENT_TYPES
    }
    blacklisted = sorted(set(blacklisted_hashes))
    total = len(grouped["title"]) * len(grouped["description1"]) * (len(grouped["description2"]) + 1)
    active_ids = {str(row.id) for row in active}
    fingerprint_payload = "|".join(sorted(active_ids)) + "#" + "|".join(blacklisted)
    return {
        "segment_counts": {key: len(rows) for key, rows in grouped.items()},
        "total_combination_count": total,
        "available_combination_count": max(0, total - len(blacklisted)),
        "blacklisted_combination_count": len(blacklisted),
        "fingerprint": hashlib.sha256(fingerprint_payload.encode("utf-8")).hexdigest(),
    }


def select_random_creative_combinations(
    segments: Iterable,
    blacklisted_hashes: Iterable[str],
    *,
    seed: str,
    limit: int = CREATIVE_COUNT_PER_ACCOUNT,
) -> list[CreativeCandidate]:
    active = [row for row in segments if not row.is_blacklisted]
    titles = sorted((row for row in active if row.segment_type == "title"), key=lambda row: str(row.id))
    descriptions1 = sorted((row for row in active if row.segment_type == "description1"), key=lambda row: str(row.id))
    descriptions2 = [None, *sorted((row for row in active if row.segment_type == "description2"), key=lambda row: str(row.id))]
    if not titles or not descriptions1:
        return []
    total = len(titles) * len(descriptions1) * len(descriptions2)
    if total <= 0:
        return []

    blocked = set(blacklisted_hashes)
    rng = random.Random(int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16))
    start = rng.randrange(total)
    step = rng.randrange(1, total + 1)
    while total > 1 and math.gcd(step, total) != 1:
        step = (step % total) + 1

    result: list[CreativeCandidate] = []
    description_block = len(descriptions1) * len(descriptions2)
    for offset in range(total):
        index = (start + offset * step) % total
        title = titles[index // description_block]
        remainder = index % description_block
        description1 = descriptions1[remainder // len(descriptions2)]
        description2 = descriptions2[remainder % len(descriptions2)]
        combination_hash = creative_combination_hash(
            title.id,
            description1.id,
            description2.id if description2 else None,
        )
        if combination_hash in blocked:
            continue
        result.append(CreativeCandidate(
            combination_hash=combination_hash,
            title_id=title.id,
            description1_id=description1.id,
            description2_id=description2.id if description2 else None,
            title=title.content,
            description1=description1.content,
            description2=description2.content if description2 else "",
        ))
        if len(result) == limit:
            break
    return result


def extract_main_reason(creative: dict) -> tuple[str | None, str | None]:
    reasons = creative.get("offlineReasons") or []
    if isinstance(reasons, dict):
        reasons = [reasons]
    for reason in reasons:
        if not isinstance(reason, dict):
            continue
        main_reason = str(reason.get("mainReason")) if reason.get("mainReason") is not None else None
        detail_reason = reason.get("detailReason")
        if main_reason:
            return main_reason, str(detail_reason) if detail_reason is not None else None
    main_reason = creative.get("mainReason")
    detail_reason = creative.get("detailReason")
    return (
        str(main_reason) if main_reason is not None else None,
        str(detail_reason) if detail_reason is not None else None,
    )


def creative_review_action(account_type: str, main_reason: str | None, current_rejections: int = 0) -> dict:
    if main_reason != "3":
        return {"action": "keep", "increment_rejection": False, "blacklist": False}
    if account_type == "二跳账户":
        next_count = current_rejections + 1
        return {
            "action": "record_rejection_delete_and_replenish",
            "increment_rejection": True,
            "blacklist": next_count >= SECOND_HOP_REJECTION_THRESHOLD,
        }
    return {
        "action": "delete_and_replenish_allow_resubmit",
        "increment_rejection": False,
        "blacklist": False,
    }
