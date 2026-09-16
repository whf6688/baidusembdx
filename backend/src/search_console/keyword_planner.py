from collections import defaultdict
from dataclasses import dataclass, field
import hashlib
from typing import Iterable

from .models import KeywordTier


class KeywordPlanError(ValueError):
    pass


@dataclass(frozen=True)
class TieredKeyword:
    text: str
    tier: KeywordTier


@dataclass(frozen=True)
class KeywordPlanConfig:
    a_unit_count: int = 5
    unit_capacity: int = 5000
    batch_number: int = 1

    def validate(self) -> None:
        if self.a_unit_count < 1:
            raise KeywordPlanError("A 类单元数必须大于 0")
        if not 1 <= self.unit_capacity <= 5000:
            raise KeywordPlanError("单元关键词上限必须在 1 到 5000 之间")
        if self.batch_number < 1:
            raise KeywordPlanError("批次必须大于 0")


@dataclass
class PlannedUnit:
    name: str
    purpose: str
    tiers: list[str]
    keywords: list[str] = field(default_factory=list)


def _deduplicate(keywords: Iterable[TieredKeyword]) -> dict[KeywordTier, list[str]]:
    grouped: dict[KeywordTier, list[str]] = defaultdict(list)
    seen: set[tuple[KeywordTier, str]] = set()
    text_tiers: dict[str, KeywordTier] = {}
    for keyword in keywords:
        text = keyword.text.strip()
        if not text:
            continue
        normalized = text.casefold()
        previous_tier = text_tiers.get(normalized)
        if previous_tier is not None and previous_tier != keyword.tier:
            raise KeywordPlanError(
                f"关键词“{text}”同时属于 {previous_tier.value} 和 {keyword.tier.value}，请只保留一个等级"
            )
        text_tiers[normalized] = keyword.tier
        key = (keyword.tier, normalized)
        if key not in seen:
            grouped[keyword.tier].append(text)
            seen.add(key)
    return grouped


def _base_units(campaign_name: str, grouped: dict[KeywordTier, list[str]], config: KeywordPlanConfig) -> list[PlannedUnit]:
    a_keywords = grouped[KeywordTier.A]
    b_keywords = grouped[KeywordTier.B]
    c_keywords = grouped[KeywordTier.C]
    for tier, values in (("A", a_keywords), ("B", b_keywords), ("C", c_keywords)):
        if len(values) > config.unit_capacity:
            raise KeywordPlanError(f"{tier} 类关键词有 {len(values)} 个，超过单个单元 {config.unit_capacity} 个的限制")
    units = [PlannedUnit(name=f"{campaign_name}_A_{index:02d}", purpose="A成本最大化", tiers=["A"], keywords=list(a_keywords)) for index in range(1, config.a_unit_count + 1)]
    units.append(PlannedUnit(name=f"{campaign_name}_B_机会_01", purpose="B机会测试", tiers=["B"], keywords=list(b_keywords)))
    units.append(PlannedUnit(name=f"{campaign_name}_C_成本较高_01", purpose="C成本测试", tiers=["C"], keywords=list(c_keywords)))
    return units


def _supplement_batches(
    grouped: dict[KeywordTier, list[str]],
    batch_capacity: int,
    seed_material: str,
) -> list[list[tuple[str, str]]]:
    """Randomize equal-weight DEF words deterministically, then partition them."""

    tiers = (KeywordTier.D, KeywordTier.E, KeywordTier.F)
    groups = [(tier.value, text) for tier in tiers for text in grouped[tier]]
    groups.sort(key=lambda group: hashlib.sha256(
        f"{seed_material}|keyword|{group[0]}|{group[1].casefold()}".encode("utf-8")
    ).digest())
    return [
        groups[start:start + batch_capacity]
        for start in range(0, len(groups), batch_capacity)
    ] or [[]]


def _def_capacity(abc_instances: int) -> int:
    """Keep DEF at or below 40% after integer rounding."""

    # DEF / (ABC + DEF) = 40%, so DEF = ABC * 2/3.
    return max(1, abc_instances * 2 // 3)


def build_keyword_plan(
    account_ids: list[int],
    campaign_name: str,
    keywords: Iterable[TieredKeyword],
    config: KeywordPlanConfig | None = None,
) -> dict:
    config = config or KeywordPlanConfig()
    config.validate()
    accounts = sorted(set(account_ids))
    if not accounts:
        raise KeywordPlanError("至少需要一个目标账户")
    if not campaign_name.strip():
        raise KeywordPlanError("计划名称不能为空")
    grouped = _deduplicate(keywords)
    missing_base = [tier.value for tier in (KeywordTier.A, KeywordTier.B, KeywordTier.C) if not grouped[tier]]
    if missing_base:
        raise KeywordPlanError(f"缺少基础分级关键词：{', '.join(missing_base)}")
    base_units = _base_units(campaign_name, grouped, config)
    assignments: dict[int, list[PlannedUnit]] = {
        account_id: _base_units(campaign_name, grouped, config)
        if config.batch_number == 1
        else []
        for account_id in accounts
    }

    abc_instances = (
        len(grouped[KeywordTier.A]) * config.a_unit_count
        + len(grouped[KeywordTier.B])
        + len(grouped[KeywordTier.C])
    )
    def_target_per_account = _def_capacity(abc_instances)
    batch_capacity = def_target_per_account * len(accounts)
    seed_material = "|".join([
        campaign_name.strip().casefold(),
        ",".join(map(str, accounts)),
    ])
    supplement_batches = _supplement_batches(
        grouped, batch_capacity, seed_material
    )
    total_batches = len(supplement_batches)
    if config.batch_number > total_batches:
        raise KeywordPlanError(f"批次超出范围：当前共 {total_batches} 批")
    selected_groups = supplement_batches[config.batch_number - 1]

    # 每个账户生成有限DEF槽位并稳定随机排序；每个词只占一个随机槽位。
    supplements: dict[int, list[tuple[str, str]]] = defaultdict(list)
    account_slots: list[tuple[int, int]] = []
    for slot in range(def_target_per_account):
        randomized_accounts = sorted(accounts, key=lambda account_id: hashlib.sha256(
            f"{seed_material}|batch:{config.batch_number}|round:{slot}|account:{account_id}".encode("utf-8")
        ).digest())
        account_slots.extend((account_id, slot) for account_id in randomized_accounts)
    for (tier, text), (account_id, _) in zip(selected_groups, account_slots):
        supplements[account_id].append((tier, text))

    for account_id in accounts:
        values = supplements[account_id]
        for chunk_index, start in enumerate(range(0, len(values), config.unit_capacity), start=1):
            chunk = values[start:start + config.unit_capacity]
            tiers = list(dict.fromkeys(tier for tier, _ in chunk))
            assignments[account_id].append(PlannedUnit(
                name=f"{campaign_name}_DEF_补充_{chunk_index:02d}",
                purpose="DEF随机补充测试",
                tiers=tiers,
                keywords=[text for _, text in chunk],
            ))

    account_plans = []
    for account_id, units in assignments.items():
        def_instances = len(supplements[account_id])
        total_instances = abc_instances + def_instances
        operation_instances = sum(len(unit.keywords) for unit in units)
        account_plans.append({
            "account_id": account_id,
            "unit_count": len(units),
            "active_unit_count": len(base_units) + sum(1 for unit in units if "DEF" in unit.name),
            "keyword_instances": total_instances,
            "operation_keyword_instances": operation_instances,
            "abc_keyword_instances": abc_instances,
            "def_keyword_instances": def_instances,
            "abc_percent": round(abc_instances / total_instances * 100, 2),
            "def_percent": round(def_instances / total_instances * 100, 2),
            "units": [{"name": unit.name, "purpose": unit.purpose, "tiers": unit.tiers, "keyword_count": len(unit.keywords), "keywords": unit.keywords} for unit in units],
        })
    batch_selected_counts = {
        tier.value: sum(1 for selected_tier, _ in selected_groups if selected_tier == tier.value)
        for tier in (KeywordTier.D, KeywordTier.E, KeywordTier.F)
    }
    remaining_groups = [
        group
        for batch in supplement_batches[config.batch_number:]
        for group in batch
    ]
    total_def_keywords = sum(len(grouped[tier]) for tier in (KeywordTier.D, KeywordTier.E, KeywordTier.F))
    total_def_instances = total_def_keywords
    return {
        "strategy": "每账户ABC不少于60%、DEF不超过40%，DEF等权稳定随机分批",
        "config": {"a_unit_count": config.a_unit_count, "unit_capacity": config.unit_capacity, "batch_number": config.batch_number},
        "source_counts": {tier.value: len(grouped[tier]) for tier in KeywordTier},
        "account_count": len(accounts),
        "batch": {
            "number": config.batch_number,
            "total": total_batches,
            "mode": "initial" if config.batch_number == 1 else "replace_def",
            "has_more": config.batch_number < total_batches,
            "next_number": config.batch_number + 1 if config.batch_number < total_batches else None,
            "abc_target_percent": 60,
            "def_target_percent": 40,
            "allocation_mode": "stable_random",
            "abc_instances_per_account": abc_instances,
            "def_target_per_account": def_target_per_account,
            "capacity": batch_capacity,
            "selected": len(selected_groups),
            "selected_keywords": len(selected_groups),
            "selected_counts": batch_selected_counts,
            "selected_instance_counts": batch_selected_counts,
            "remaining": len(remaining_groups),
            "remaining_keywords": len(remaining_groups),
            "total_def_keywords": total_def_keywords,
            "total_def_instances": total_def_instances,
            "candidate_shortage": len(selected_groups) < batch_capacity,
        },
        "accounts": account_plans,
    }
