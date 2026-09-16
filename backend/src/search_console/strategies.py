import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import StrategyPolicy, StrategyVersion
from .schemas import KeywordTierRuleConfig


STRATEGY_KEYS = ("budget_reset", "budget_append", "elimination", "keyword_tiers")
DEFAULT_BUDGET_APPEND_ROUND_AMOUNTS = [
    {"round": round_number, "amount": "50.00"}
    for round_number in range(1, 11)
]
DEFAULT_STRATEGY_CONFIGS = {
    "budget_reset": {"target_budget": "50.00", "schedule_times": ["00:00"]},
    "budget_append": {
        "round_amounts": DEFAULT_BUDGET_APPEND_ROUND_AMOUNTS,
        "add_cost_limit": "100.00",
        "utilization_limit": "0.80",
        "schedule_times": [f"{hour:02d}:30" for hour in range(1, 24)],
    },
    "elimination": {
        "spend_without_add_limit": "100.00", "add_cost_limit": "120.00",
        "schedule_times": ["23:20"],
    },
    "keyword_tiers": KeywordTierRuleConfig().model_dump(mode="json"),
}


class StrategyConfigError(ValueError):
    pass


def config_hash(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _money(config: dict, key: str) -> str:
    try:
        value = Decimal(str(config[key])).quantize(Decimal("0.01"))
    except (KeyError, InvalidOperation, TypeError) as exc:
        raise StrategyConfigError(f"{key} 必须是有效金额") from exc
    if value <= 0 or value > Decimal("1000000"):
        raise StrategyConfigError(f"{key} 必须大于 0 且不超过 1000000")
    return str(value)


def _times(config: dict, *, multiple: bool) -> list[str]:
    values = config.get("schedule_times")
    if not isinstance(values, list) or not values:
        raise StrategyConfigError("schedule_times 至少包含一个执行时间")
    normalized = []
    for value in values:
        try:
            parsed = datetime.strptime(str(value), "%H:%M").strftime("%H:%M")
        except ValueError as exc:
            raise StrategyConfigError("执行时间必须使用 HH:MM 格式") from exc
        if parsed not in normalized:
            normalized.append(parsed)
    if not multiple and len(normalized) != 1:
        raise StrategyConfigError("该策略只能设置一个每日执行时间")
    return sorted(normalized)


def normalize_budget_append_round_amounts(config: dict) -> list[dict[str, int | str]]:
    """Return the ten direct append amounts, accepting the legacy flat increment."""
    values = config.get("round_amounts")
    if values is None and "increment" in config:
        legacy_amount = _money(config, "increment")
        return [
            {"round": round_number, "amount": legacy_amount}
            for round_number in range(1, 11)
        ]
    if not isinstance(values, list) or len(values) != 10:
        raise StrategyConfigError("round_amounts 必须完整配置第 1 至第 10 轮金额")

    normalized: list[dict[str, int | str]] = []
    seen_rounds: set[int] = set()
    for item in values:
        if not isinstance(item, dict):
            raise StrategyConfigError("round_amounts 每项必须包含轮次和金额")
        try:
            round_number = int(item["round"])
        except (KeyError, TypeError, ValueError) as exc:
            raise StrategyConfigError("追加轮次必须是 1 至 10 的整数") from exc
        if round_number < 1 or round_number > 10 or round_number in seen_rounds:
            raise StrategyConfigError("追加轮次必须唯一且覆盖第 1 至第 10 轮")
        normalized.append({
            "round": round_number,
            "amount": _money(item, "amount"),
        })
        seen_rounds.add(round_number)
    if seen_rounds != set(range(1, 11)):
        raise StrategyConfigError("追加轮次必须唯一且覆盖第 1 至第 10 轮")
    return sorted(normalized, key=lambda item: int(item["round"]))


def budget_append_amount(config: dict, round_number: int) -> Decimal:
    normalized = normalize_budget_append_round_amounts(config)
    index = min(max(int(round_number), 1), 10) - 1
    return Decimal(str(normalized[index]["amount"]))


def normalize_strategy_config_for_read(config: dict) -> dict:
    """Expose old budget-append versions through the current round-based schema."""
    if "increment" not in config or "round_amounts" in config:
        return config
    normalized = dict(config)
    normalized["round_amounts"] = normalize_budget_append_round_amounts(config)
    normalized.pop("increment", None)
    return normalized


def validate_strategy_config(strategy_key: str, raw: dict) -> dict:
    if strategy_key not in STRATEGY_KEYS:
        raise StrategyConfigError("未知策略")
    if not isinstance(raw, dict):
        raise StrategyConfigError("策略配置必须是对象")
    if strategy_key == "keyword_tiers":
        try:
            return KeywordTierRuleConfig.model_validate(raw).model_dump(mode="json")
        except ValueError as exc:
            raise StrategyConfigError(str(exc)) from exc
    if strategy_key == "budget_reset":
        return {"target_budget": _money(raw, "target_budget"), "schedule_times": _times(raw, multiple=False)}
    if strategy_key == "budget_append":
        try:
            utilization = Decimal(str(raw["utilization_limit"]))
        except (KeyError, InvalidOperation, TypeError) as exc:
            raise StrategyConfigError("utilization_limit 必须是有效比例") from exc
        if utilization <= 0 or utilization > 1:
            raise StrategyConfigError("utilization_limit 必须大于 0 且不超过 1")
        return {
            "round_amounts": normalize_budget_append_round_amounts(raw),
            "add_cost_limit": _money(raw, "add_cost_limit"),
            "utilization_limit": str(utilization.normalize()),
            "schedule_times": _times(raw, multiple=True),
        }
    return {
        "spend_without_add_limit": _money(raw, "spend_without_add_limit"),
        "add_cost_limit": _money(raw, "add_cost_limit"),
        "schedule_times": _times(raw, multiple=False),
    }


def ensure_strategy_policies(db: Session, project_id: uuid.UUID, actor: str = "system-migration") -> list[StrategyPolicy]:
    existing = {row.strategy_key: row for row in db.scalars(select(StrategyPolicy).where(StrategyPolicy.project_id == project_id)).all()}
    changed = False
    for key in STRATEGY_KEYS:
        if key in existing:
            continue
        policy = StrategyPolicy(project_id=project_id, strategy_key=key, revision=1)
        db.add(policy)
        db.flush()
        config = validate_strategy_config(key, DEFAULT_STRATEGY_CONFIGS[key])
        version = StrategyVersion(
            policy_id=policy.id, version_number=1, status="published", config=config,
            config_hash=config_hash(config), created_by=actor, published_by=actor,
            published_at=datetime.now(UTC),
        )
        db.add(version)
        db.flush()
        policy.active_version_id = version.id
        existing[key] = policy
        changed = True
    if changed:
        db.flush()
    return [existing[key] for key in STRATEGY_KEYS]


def active_strategy_version(db: Session, project_id: uuid.UUID, strategy_key: str) -> StrategyVersion:
    policy = next(row for row in ensure_strategy_policies(db, project_id) if row.strategy_key == strategy_key)
    version = db.get(StrategyVersion, policy.active_version_id)
    if version is None:
        raise StrategyConfigError("策略没有生效版本")
    return version


def strategy_payload(db: Session, policy: StrategyPolicy) -> dict:
    active = db.get(StrategyVersion, policy.active_version_id)
    draft = db.scalar(select(StrategyVersion).where(StrategyVersion.policy_id == policy.id, StrategyVersion.status == "draft"))
    return {
        "key": policy.strategy_key, "revision": policy.revision,
        "active": serialize_version(active) if active else None,
        "draft": serialize_version(draft) if draft else None,
    }


def serialize_version(row: StrategyVersion) -> dict:
    return {
        "id": str(row.id), "version": row.version_number, "status": row.status,
        "base_version_id": str(row.base_version_id) if row.base_version_id else None,
        "draft_revision": row.draft_revision,
        "config": normalize_strategy_config_for_read(row.config),
        "config_hash": row.config_hash, "created_by": row.created_by,
        "published_by": row.published_by, "created_at": row.created_at,
        "published_at": row.published_at,
    }


def save_draft(db: Session, policy: StrategyPolicy, *, config: dict, expected_revision: int, actor: str) -> StrategyVersion:
    if policy.revision != expected_revision:
        raise RuntimeError("strategy_revision_conflict")
    normalized = validate_strategy_config(policy.strategy_key, config)
    draft = db.scalar(select(StrategyVersion).where(StrategyVersion.policy_id == policy.id, StrategyVersion.status == "draft"))
    if draft:
        draft.config = normalized
        draft.config_hash = config_hash(normalized)
        draft.draft_revision += 1
        draft.created_by = actor
        draft.created_at = datetime.now(UTC)
    else:
        next_version = int(db.scalar(select(func.max(StrategyVersion.version_number)).where(StrategyVersion.policy_id == policy.id)) or 0) + 1
        draft = StrategyVersion(
            policy_id=policy.id, version_number=next_version, status="draft",
            base_version_id=policy.active_version_id, config=normalized,
            config_hash=config_hash(normalized), created_by=actor,
        )
        db.add(draft)
    policy.revision += 1
    db.flush()
    return draft
