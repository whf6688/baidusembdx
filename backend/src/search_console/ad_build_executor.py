import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import unquote_plus, urlparse, urlsplit, urlunsplit

from sqlalchemy import func, select
from sqlalchemy.orm.attributes import flag_modified

from baidu_platform_core import BaiduCallContext

from .account_lifecycle import ELIMINATED, EMPTY, TESTING
from .ad_builds import build_keyword_tracking_url, keyword_uploaded_adgroup_ids
from .ad_build_rules import current_ad_build_rules
from .ad_build_settings import load_plan_repeat_counts, repeat_count_for_plan
from .config import get_settings
from .creative_persistence import (
    ensure_creative_center_combination,
    record_second_hop_creative_rejection,
)
from .creatives import CreativeCandidate
from .keyword_planner import KeywordPlanConfig, TieredKeyword, build_keyword_plan
from .keyword_tiers import normalize_tier_name
from .models import (
    Account,
    AccountType,
    AdBuildJob,
    AuditEvent,
    CampaignCache,
    OcpcProjectCache,
    CreativeCombination,
    CreativeAssignment,
    CreativeSegment,
    KeywordTier,
    MaterialKeyword,
    Operation,
    BackgroundTask,
    TaskStatus,
)


settings = get_settings()
# Default batch size for Baidu write endpoints other than keyword.add.
# Keyword uploads use KEYWORD_WRITE_LIMIT independently because the official
# keyword.add contract and production verification both support 10,000 rows.
WRITE_BATCH_SIZE = 400
KEYWORD_WRITE_LIMIT = 10_000
CREATIVE_DIRECT_REJECTION_CODES = {"90180006493"}
ADGROUP_READBACK_DELAY_SECONDS = 60
ADGROUP_READBACK_TIMEOUT = timedelta(minutes=10)
TIER_CAMPAIGN_NAMES = {
    "A": "A成本",
    "B": "B机会",
    "C": "C成本较高",
    "D": "D消耗不足",
    "E": "E消耗很小",
    "F": "F拓展",
}


class DelayedReadbackPending(RuntimeError):
    """A write was acknowledged; only a later read is allowed from this point."""


class ReadbackVerificationTimeout(RuntimeError):
    """A delayed readback exhausted its safe window without replaying writes."""


@dataclass(frozen=True)
class AdgroupBuildResult:
    unit_ids: dict[str, int]
    pending_names: list[str]


def result_rows(result: dict) -> list[dict]:
    candidate = result.get("data")
    if not isinstance(candidate, list):
        body = result.get("body")
        candidate = body.get("data") if isinstance(body, dict) else []
    return [row for row in candidate if isinstance(row, dict)] if isinstance(candidate, list) else []


def _fingerprint(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def _context(account: Account, operation: Operation, node: str, payload: dict) -> BaiduCallContext:
    generation = int(operation.payload.get("execution_generation") or 1)
    return BaiduCallContext(
        app_code="search",
        baidu_application_code=settings.baidu_application_code,
        manager_login_name=account.manager_login_name,
        target_account_id=account.baidu_account_id,
        target_login_name=account.login_name,
        request_batch=f"ad-build:{operation.id}",
        idempotency_key=(
            f"ad-build:{operation.id}:g{generation}:{node}:{_fingerprint(payload)}"
        ),
    )


def _read_context(account: Account, operation: Operation) -> BaiduCallContext:
    return BaiduCallContext(
        app_code="search",
        baidu_application_code=settings.baidu_application_code,
        manager_login_name=account.manager_login_name,
        target_account_id=account.baidu_account_id,
        target_login_name=account.login_name,
        request_batch=f"ad-build:{operation.id}",
        idempotency_key="",
    )


def _save(db, task: BackgroundTask, state: dict, node: str, progress: int) -> None:
    task.status = TaskStatus.RUNNING
    task.current_node = node
    task.progress = progress
    task.last_error = None
    task.heartbeat_at = datetime.now(UTC)
    task.result = {"workflow_state": state}
    flag_modified(task, "result")
    db.commit()


def _phase_start(state: dict, name: str) -> None:
    timings = state.setdefault("timings", {})
    phase = timings.setdefault(name, {})
    phase.setdefault("started_at", datetime.now(UTC).isoformat())


def _phase_finish(state: dict, name: str) -> None:
    timings = state.setdefault("timings", {})
    phase = timings.setdefault(name, {})
    if phase.get("completed_at"):
        return
    now = datetime.now(UTC)
    started_at = datetime.fromisoformat(phase.setdefault("started_at", now.isoformat()))
    phase["completed_at"] = now.isoformat()
    phase["duration_seconds"] = round((now - started_at).total_seconds(), 3)


def _chunks(values: list, size: int = WRITE_BATCH_SIZE) -> list[list]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def _pack_keyword_unit_batches(units: list[tuple[int, str, list]]) -> list[list[tuple[int, str, list]]]:
    """Fill keyword.add requests to 10,000 rows, splitting units when needed."""

    batches: list[list[tuple[int, str, list]]] = []
    current: list[tuple[int, str, list]] = []
    current_count = 0
    for unit_index, unit_name, keywords in units:
        offset = 0
        while offset < len(keywords):
            remaining_capacity = KEYWORD_WRITE_LIMIT - current_count
            take = min(remaining_capacity, len(keywords) - offset)
            current.append((unit_index, unit_name, keywords[offset:offset + take]))
            current_count += take
            offset += take
            if current_count == KEYWORD_WRITE_LIMIT:
                batches.append(current)
                current = []
                current_count = 0
    if current:
        batches.append(current)
    return batches


def _operation_build_rules(operation: Operation) -> dict:
    rules = operation.payload.get("build_rules")
    return rules if isinstance(rules, dict) else current_ad_build_rules()


def _tier(value: str) -> KeywordTier | None:
    normalized = normalize_tier_name(str(value or "").strip())
    try:
        return KeywordTier(normalized[:1])
    except ValueError:
        return None


def _baidu_text_length(value: str) -> int:
    return sum(1 if ord(character) < 128 else 2 for character in value)


def _repeat_material_units(
    units: list[dict],
    repeat_counts: dict[str, int],
) -> list[dict]:
    expanded: list[dict] = []
    sequence_by_campaign: dict[str, int] = {}
    for unit in units:
        campaign_name = str(unit["campaign_name"])
        repeat_count = repeat_count_for_plan(repeat_counts, campaign_name)
        for _ in range(repeat_count):
            sequence_by_campaign[campaign_name] = sequence_by_campaign.get(campaign_name, 0) + 1
            expanded.append({
                **unit,
                "name": f"{campaign_name}_{sequence_by_campaign[campaign_name]:02d}",
                "repeat_count": repeat_count,
            })
    return expanded


def _refresh_account_plan_metrics(account_plan: dict, units: list[dict]) -> None:
    keyword_instances = sum(len(unit["keywords"]) for unit in units)
    abc_instances = sum(
        len(unit["keywords"])
        for unit in units
        if str(unit["campaign_name"])[:1] in {"A", "B", "C"}
    )
    def_instances = keyword_instances - abc_instances
    account_plan["units"] = units
    account_plan["unit_count"] = len(units)
    account_plan["active_unit_count"] = len(units)
    account_plan["keyword_instances"] = keyword_instances
    account_plan["operation_keyword_instances"] = keyword_instances
    account_plan["abc_keyword_instances"] = abc_instances
    account_plan["def_keyword_instances"] = def_instances
    account_plan["abc_percent"] = round(abc_instances * 100 / keyword_instances, 2) if keyword_instances else 0
    account_plan["def_percent"] = round(def_instances * 100 / keyword_instances, 2) if keyword_instances else 0


def _build_material_plan(db, account: Account, operation: Operation) -> tuple[dict, dict[str, MaterialKeyword]]:
    operation_payload = operation.payload if isinstance(operation.payload, dict) else {}
    keyword_mode = str(operation_payload.get("keyword_mode") or "preferred")
    job = None
    try:
        job_id = operation_payload.get("ad_build_job_id")
        job = db.get(AdBuildJob, uuid.UUID(str(job_id))) if job_id else None
    except (TypeError, ValueError):
        job = None
    selection_config = job.selection_config if job is not None and isinstance(job.selection_config, dict) else {}
    repeat_counts = load_plan_repeat_counts(db, account.project_id)
    frozen_snapshot = selection_config.get("material_snapshot")
    if isinstance(frozen_snapshot, list) and frozen_snapshot:
        rows = [
            SimpleNamespace(
                id=item.get("id"),
                campaign_name=str(item.get("campaign_name") or "未命名计划"),
                keyword_text=str(item.get("keyword_text") or "").strip(),
                keyword_utf8_encoded=str(item.get("keyword_utf8_encoded") or ""),
            )
            for item in frozen_snapshot
            if isinstance(item, dict) and str(item.get("keyword_text") or "").strip()
        ]
    else:
        rows = db.scalars(
            select(MaterialKeyword)
            .where(
                MaterialKeyword.project_id == account.project_id,
                MaterialKeyword.is_blacklisted.is_(False),
            )
            .order_by(MaterialKeyword.campaign_name, MaterialKeyword.keyword_text)
        ).all()

    if keyword_mode == "full":
        by_text: dict[str, MaterialKeyword] = {}
        invalid: list[str] = []
        grouped: dict[str, list[str]] = {}
        for row in rows:
            if _baidu_text_length(row.keyword_text) > 40:
                invalid.append(row.keyword_text)
                continue
            grouped.setdefault(row.campaign_name or "未命名计划", []).append(row.keyword_text)
            by_text[row.keyword_text.casefold()] = row
        if invalid:
            raise ValueError(f"存在 {len(invalid)} 个超过百度40字节限制的关键词")
        base_units: list[dict] = []
        for campaign_name, keywords in grouped.items():
            for start in range(0, len(keywords), 5000):
                chunk = keywords[start:start + 5000]
                base_units.append({
                    "campaign_name": campaign_name,
                    "name": f"{campaign_name}_{start // 5000 + 1:02d}",
                    "purpose": "全量关键词投放",
                    "tiers": [],
                    "keyword_count": len(chunk),
                    "keywords": chunk,
                })
        units = _repeat_material_units(base_units, repeat_counts)
        account_plan = {
            "account_id": account.baidu_account_id,
        }
        _refresh_account_plan_metrics(account_plan, units)
        return {
            "mode": "full",
            "accounts": [account_plan],
            "summary": {
                "account_count": 1,
                "campaign_count": len(grouped),
                "unit_count": len(units),
                "keyword_count": account_plan["operation_keyword_instances"],
            },
        }, by_text
    tiered: list[TieredKeyword] = []
    by_text: dict[str, MaterialKeyword] = {}
    invalid: list[str] = []
    for row in rows:
        tier = _tier(row.campaign_name)
        if tier is None:
            continue
        if _baidu_text_length(row.keyword_text) > 40:
            invalid.append(row.keyword_text)
            continue
        tiered.append(TieredKeyword(text=row.keyword_text, tier=tier))
        by_text[row.keyword_text.casefold()] = row
    if invalid:
        raise ValueError(f"存在 {len(invalid)} 个超过百度40字节限制的关键词")
    plan = build_keyword_plan(
        [account.baidu_account_id],
        "减肥",
        tiered,
        # 账户搭建永远从完整的首批物料开始。调度任务的第几批只是执行时间分组，
        # 不能复用为 DEF 关键词轮换批次；后者由独立的关键词轮换操作负责。
        KeywordPlanConfig(a_unit_count=1, batch_number=1),
    )
    account_plan = plan["accounts"][0]
    structured_units: list[dict] = []
    unit_numbers: dict[str, int] = {}
    supplement_keywords: list[str] = []
    for unit in account_plan["units"]:
        if set(unit["tiers"]).issubset({"D", "E", "F"}):
            supplement_keywords.extend(unit["keywords"])
            continue
        tier = unit["tiers"][0]
        campaign_name = TIER_CAMPAIGN_NAMES[tier]
        unit_numbers[campaign_name] = unit_numbers.get(campaign_name, 0) + 1
        structured_units.append({
            **unit,
            "campaign_name": campaign_name,
            "name": f"{campaign_name}_{unit_numbers[campaign_name]:02d}",
        })

    supplements_by_campaign: dict[str, list[str]] = {
        name: [] for tier, name in TIER_CAMPAIGN_NAMES.items() if tier in {"D", "E", "F"}
    }
    for text in supplement_keywords:
        material = by_text[text.casefold()]
        tier = _tier(material.campaign_name)
        if tier is not None and tier.value in {"D", "E", "F"}:
            supplements_by_campaign[TIER_CAMPAIGN_NAMES[tier.value]].append(text)
    for campaign_name, keywords in supplements_by_campaign.items():
        for start in range(0, len(keywords), 5000):
            unit_numbers[campaign_name] = unit_numbers.get(campaign_name, 0) + 1
            chunk = keywords[start:start + 5000]
            structured_units.append({
                "campaign_name": campaign_name,
                "name": f"{campaign_name}_{unit_numbers[campaign_name]:02d}",
                "purpose": "DEF随机补充测试",
                "tiers": [campaign_name[:1]],
                "keyword_count": len(chunk),
                "keywords": chunk,
            })
    structured_units = _repeat_material_units(structured_units, repeat_counts)
    _refresh_account_plan_metrics(account_plan, structured_units)
    if isinstance(plan.get("summary"), dict):
        plan["summary"].update({
            "unit_count": account_plan["unit_count"],
            "keyword_count": account_plan["operation_keyword_instances"],
        })
    return plan, by_text


def _read_account(client, account: Account, operation: Operation) -> dict:
    rows = result_rows(client.execute_read(
        _read_context(account, operation),
        "account.get",
        {"accountFields": [
            "userId", "regDomain", "budget", "budgetType", "regionTarget", "geoLocationStatus",
            "userStat", "userLevel",
        ]},
    ))
    if not rows:
        raise RuntimeError("百度未返回目标账户信息")
    return rows[0]


def _read_campaigns(client, account: Account, operation: Operation) -> list[dict]:
    return result_rows(client.execute_read(
        _read_context(account, operation),
        "campaign.get",
        {
            "campaignFields": [
                "campaignId", "campaignName", "pause", "schedule", "marketingTargetId",
                "equipmentType", "campaignBidType", "campaignOcpcBidType", "campaignTransTypes",
                "negativeWords", "exactNegativeWords",
            ],
            "campaignIds": [],
            "adType": 0,
        },
    ))


def _store_verified_campaign_cache(db, account: Account, remote_rows: list[dict]) -> None:
    """Persist the final ad-build campaign readback as the account's cache."""
    observed_at = datetime.now(UTC)
    existing = {
        row.baidu_campaign_id: row
        for row in db.scalars(select(CampaignCache).where(
            CampaignCache.project_id == account.project_id,
            CampaignCache.account_id == account.id,
        )).all()
    }
    for row in existing.values():
        row.is_active = False
    for remote in remote_rows:
        if remote.get("campaignId") is None:
            continue
        campaign_id = int(remote["campaignId"])
        row = existing.get(campaign_id)
        if row is None:
            row = CampaignCache(
                project_id=account.project_id,
                account_id=account.id,
                baidu_campaign_id=campaign_id,
            )
            db.add(row)
            existing[campaign_id] = row
        row.campaign_name = str(remote.get("campaignName") or "") or None
        row.pause = bool(remote.get("pause")) if "pause" in remote else row.pause
        row.schedule = remote.get("schedule") if isinstance(remote.get("schedule"), list) else []
        row.is_active = True
        row.last_seen_at = observed_at
        row.updated_at = observed_at
    account.campaign_cache_synced_at = observed_at
    account.campaign_cache_status = "succeeded"


def _read_adgroups(client, account: Account, operation: Operation, campaign_id: int) -> list[dict]:
    return result_rows(client.execute_read(
        _read_context(account, operation),
        "adgroup.get",
        {
            "ids": [campaign_id],
            "idType": 3,
            "getTemp": 0,
            "adgroupFields": [
                "adgroupId", "campaignId", "adgroupName", "maxPrice", "pause", "mobileFinalUrl",
            ],
        },
    ))


def _read_keywords(client, account: Account, operation: Operation, adgroup_id: int) -> list[dict]:
    return result_rows(client.execute_read(
        _read_context(account, operation),
        "keyword.get",
        {
            "wordFields": ["keywordId", "adgroupId", "keyword", "matchType", "phraseType"],
            "ids": [adgroup_id],
            "idType": 5,
            "getTemp": 0,
        },
    ))


def _read_creatives(client, account: Account, operation: Operation, adgroup_ids: list[int]) -> list[dict]:
    rows: list[dict] = []
    for ids in _chunks(adgroup_ids, 1000):
        rows.extend(result_rows(client.execute_read(
            _read_context(account, operation),
            "creative.get",
            {
                "creativeFields": [
                    "creativeId", "adgroupId", "title", "description1", "description2", "status",
                ],
                "ids": ids,
                "idType": 5,
                "getTemp": 0,
            },
        )))
    return rows


def _creative_readback_key(
    adgroup_id: int,
    title: str,
    description1: str,
    description2: str,
) -> tuple[int, str, str]:
    """Match Baidu reads after it merges the two submitted descriptions."""

    return (adgroup_id, title, f"{description1}{description2}")


def _adgroup_mobile_final_url(account: Account) -> str:
    promotion_link = str(account.landing_url_template or "").strip()
    parsed = urlsplit(promotion_link)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("账户推广链接无效，无法生成单元移动最终访问网址")
    preserved_query_parts: list[str] = []
    for part in parsed.query.split("&"):
        if not part:
            continue
        raw_key = part.split("=", 1)[0]
        if unquote_plus(raw_key).strip().lower() == "zhanghuid":
            continue
        preserved_query_parts.append(part)
    preserved_query_parts.append(f"zhanghuid={account.baidu_account_id}")
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            "&".join(preserved_query_parts),
            parsed.fragment,
        )
    )


def _project_negative_keywords(operation: Operation, user_level: int) -> tuple[list[str], list[str]]:
    if operation.payload.get("negative_keyword_source") != "project_postgresql":
        raise ValueError("任务缺少项目数据库否词快照，请重新预检后创建任务")
    snapshot = operation.payload.get("project_negative_keywords")
    if not isinstance(snapshot, dict):
        raise ValueError("任务缺少项目数据库否词快照，请重新预检后创建任务")
    phrase = [str(value).strip() for value in snapshot.get("phrase") or [] if str(value).strip()]
    exact = [str(value).strip() for value in snapshot.get("exact") or [] if str(value).strip()]
    phrase_limit = {1: 500, 2: 400, 3: 200, 4: 200}.get(user_level, 200)
    exact_limit = {1: 900, 2: 700, 3: 400, 4: 200}.get(user_level, 200)
    if len(phrase) > phrase_limit:
        raise ValueError(f"当前账户等级最多允许{phrase_limit}个短语否词，项目数据库现有{len(phrase)}个")
    if len(exact) > exact_limit:
        raise ValueError(f"当前账户等级最多允许{exact_limit}个精确否词，项目数据库现有{len(exact)}个")
    return phrase, exact


def _same_words(actual: object, expected: list[str]) -> bool:
    actual_values = actual if isinstance(actual, list) else []
    return sorted(str(value).strip() for value in actual_values) == sorted(expected)


def _create_campaign(
    client,
    account: Account,
    operation: Operation,
    name: str,
    user_level: int,
) -> int:
    phrase_negative_words, exact_negative_words = _project_negative_keywords(operation, user_level)
    existing = next((row for row in _read_campaigns(client, account, operation) if row.get("campaignName") == name), None)
    if existing and existing.get("campaignId"):
        campaign_id = int(existing["campaignId"])
        if not (
            _same_words(existing.get("negativeWords"), phrase_negative_words)
            and _same_words(existing.get("exactNegativeWords"), exact_negative_words)
        ):
            payload = {"campaignTypes": [{
                "campaignId": campaign_id,
                "negativeWords": phrase_negative_words,
                "exactNegativeWords": exact_negative_words,
            }]}
            client.execute_write(
                _context(account, operation, "campaign-negative-keywords-update", payload),
                "campaign.update",
                payload,
            )
        verified = next((row for row in _read_campaigns(client, account, operation) if int(row.get("campaignId") or 0) == campaign_id), None)
        if not verified or not (
            _same_words(verified.get("negativeWords"), phrase_negative_words)
            and _same_words(verified.get("exactNegativeWords"), exact_negative_words)
        ):
            raise RuntimeError("计划否词写入后回读不一致")
        return campaign_id

    campaign_rules = _operation_build_rules(operation).get("campaign") or {}
    campaign = {
        "campaignName": name,
        "negativeWords": phrase_negative_words,
        "exactNegativeWords": exact_negative_words,
        "pause": bool(campaign_rules.get("pause", False)),
        "marketingTargetId": int(campaign_rules.get("marketing_target_id", 7)),
        "equipmentType": int(campaign_rules.get("equipment_type", 2)),
        "businessPointId": int(campaign_rules.get("business_point_id", 200205001)),
        "campaignBidType": int(campaign_rules.get("campaign_bid_type", 1)),
        "campaignOcpcBidType": int(campaign_rules.get("campaign_ocpc_bid_type", 1)),
        "campaignOcpcBid": float(campaign_rules.get("campaign_ocpc_bid", 0.5)),
        "campaignTransTypes": campaign_rules.get("campaign_trans_types") or [79],
        "campaignCvSources": campaign_rules.get("campaign_cv_sources") or [1000],
        "transAsset": int(campaign_rules.get("trans_asset", 0)),
    }
    schedule = campaign_rules.get("schedule") or []
    if schedule:
        campaign["schedule"] = schedule
    trans_asset_id = campaign_rules.get("trans_asset_id")
    if campaign["transAsset"] == 2 and trans_asset_id not in (None, -1):
        campaign["transAssetId"] = int(trans_asset_id)
    payload = {"campaignTypes": [campaign]}
    result = client.execute_write(
        _context(account, operation, "campaign-add", payload), "campaign.add", payload
    )
    rows = result_rows(result)
    campaign_id = int(rows[0]["campaignId"]) if rows and rows[0].get("campaignId") else 0
    verified = next(
        (
            row
            for row in _read_campaigns(client, account, operation)
            if (campaign_id and int(row.get("campaignId") or 0) == campaign_id)
            or (not campaign_id and row.get("campaignName") == name)
        ),
        None,
    )
    if not verified or not verified.get("campaignId"):
        raise RuntimeError("计划写入后未能回读到计划ID")
    if not (
        _same_words(verified.get("negativeWords"), phrase_negative_words)
        and _same_words(verified.get("exactNegativeWords"), exact_negative_words)
    ):
        raise RuntimeError("计划否词写入后回读不一致")
    return int(verified["campaignId"])


def _create_adgroups(
    client,
    account: Account,
    operation: Operation,
    campaign_id: int,
    units: list[dict],
    max_price: float,
) -> AdgroupBuildResult:
    mobile_final_url = _adgroup_mobile_final_url(account)
    existing_rows = {
        row.get("adgroupName"): row
        for row in _read_adgroups(client, account, operation, campaign_id)
        if row.get("adgroupName") and row.get("adgroupId")
    }
    update_rows = [
        {
            "adgroupId": int(existing_rows[unit["name"]]["adgroupId"]),
            "mobileFinalUrl": mobile_final_url,
        }
        for unit in units
        if unit["name"] in existing_rows
        and str(existing_rows[unit["name"]].get("mobileFinalUrl") or "") != mobile_final_url
    ]
    if update_rows:
        payload = {"adgroupTypes": update_rows}
        client.execute_write(
            _context(account, operation, "adgroup-mobile-url-update", payload),
            "adgroup.update",
            payload,
        )
    missing = [
        {
            "campaignId": campaign_id,
            "adgroupName": unit["name"],
            "maxPrice": max_price,
            "pause": False,
            "adgroupAutoTargetingStatus": False,
            "mobileFinalUrl": mobile_final_url,
        }
        for unit in units
        if unit["name"] not in existing_rows
    ]
    if missing:
        payload = {"adgroupTypes": missing}
        add_result = client.execute_write(
            _context(account, operation, "adgroup-add", payload), "adgroup.add", payload
        )
        existing_rows.update({
            row.get("adgroupName"): row
            for row in result_rows(add_result)
            if row.get("adgroupName") and row.get("adgroupId")
        })
    remote_rows: dict[str, dict] = {}
    for readback_attempt in range(4):
        remote_rows = {
            row.get("adgroupName"): row
            for row in _read_adgroups(client, account, operation, campaign_id)
            if row.get("adgroupName") and row.get("adgroupId")
        }
        if all(unit["name"] in remote_rows for unit in units):
            existing_rows.update(remote_rows)
            break
        if readback_attempt < 3:
            time.sleep(4)
    # The add response is an authoritative acknowledgement for checkpointing.
    # A newly-created unit can remain invisible to adgroup.get for longer than
    # the short inline readback window. Never replay adgroup.add in that case;
    # persist every acknowledged ID and let a later read-only verification run
    # resolve the remaining names.
    delayed = [unit["name"] for unit in units if unit["name"] not in remote_rows]
    wrong_urls = [
        unit["name"] for unit in units
        if unit["name"] in remote_rows
        and str(remote_rows[unit["name"]].get("mobileFinalUrl") or "") != mobile_final_url
    ]
    if wrong_urls:
        raise RuntimeError(f"单元移动最终访问网址回读不一致：{', '.join(wrong_urls[:3])}")
    return AdgroupBuildResult(
        unit_ids={
            unit["name"]: int(existing_rows[unit["name"]]["adgroupId"])
            for unit in units
            if unit["name"] in existing_rows and existing_rows[unit["name"]].get("adgroupId")
        },
        pending_names=delayed,
    )


def _verify_pending_adgroups(
    client,
    account: Account,
    operation: Operation,
    pending: dict,
) -> tuple[dict[str, int], list[dict]]:
    expected = pending.get("expected") if isinstance(pending.get("expected"), list) else []
    mobile_final_url = _adgroup_mobile_final_url(account)
    resolved: dict[str, int] = {}
    missing: list[dict] = []
    by_campaign: dict[int, list[str]] = {}
    for item in expected:
        if not isinstance(item, dict):
            continue
        campaign_id = int(item.get("campaign_id") or 0)
        name = str(item.get("name") or "")
        if campaign_id and name:
            by_campaign.setdefault(campaign_id, []).append(name)
    for campaign_id, names in by_campaign.items():
        remote = {
            str(row.get("adgroupName") or ""): row
            for row in _read_adgroups(client, account, operation, campaign_id)
            if row.get("adgroupName") and row.get("adgroupId")
        }
        for name in names:
            row = remote.get(name)
            if row is None:
                missing.append({"campaign_id": campaign_id, "name": name})
                continue
            if str(row.get("mobileFinalUrl") or "") != mobile_final_url:
                raise RuntimeError(f"单元移动最终访问网址回读不一致：{name}")
            resolved[name] = int(row["adgroupId"])
    return resolved, missing


def _create_ocpc_project(
    client,
    account: Account,
    operation: Operation,
    campaign_ids: list[int],
    state: dict,
) -> int:
    query_payload = {
        "targetPackageTypeFields": [
            "targetPackageId", "targetPackageName", "ocpcBid", "ocpcBidType", "scope",
            "dataFlowData", "packageStatus", "transAsset", "transAssetId",
        ],
        "ids": [account.baidu_account_id],
        "level": 1,
    }
    existing = result_rows(client.execute_read(
        _read_context(account, operation), "ocpc.get", query_payload
    ))
    found = next((row for row in existing if row.get("targetPackageName") == state["ocpc_name"]), None)
    if found and found.get("targetPackageId"):
        return int(found["targetPackageId"])

    rules = _operation_build_rules(operation).get("ocpc") or {}
    target = {
        "targetPackageName": state["ocpc_name"],
        "ocpcBidType": int(rules.get("ocpc_bid_type") or 1),
        "ocpcBid": float(Decimal(str(operation.payload["project_target_bid"]))),
        "scope": [{"levelId": campaign_id, "level": 2} for campaign_id in campaign_ids],
        "dataFlowData": rules.get("data_flow_data") or [{"dataFlow": 1000, "transType": [79]}],
        "deepTransTypeMode": int(rules.get("deep_trans_type_mode") or 1),
        "transAsset": int(rules.get("trans_asset") or 0),
        "marketingTargetId": int(rules.get("marketing_target_id") or 7),
    }
    if target["transAsset"] == 2 and rules.get("trans_asset_id") not in (None, -1):
        target["transAssetId"] = int(rules["trans_asset_id"])
    payload = {"targetPackageType": [target]}
    result = client.execute_write(
        _context(account, operation, "ocpc-add", payload), "ocpc.add", payload
    )
    rows = result_rows(result)
    if rows and rows[0].get("targetPackageId"):
        return int(rows[0]["targetPackageId"])
    existing = result_rows(client.execute_read(
        _read_context(account, operation), "ocpc.get", query_payload
    ))
    found = next((row for row in existing if row.get("targetPackageName") == state["ocpc_name"]), None)
    if not found or not found.get("targetPackageId"):
        raise RuntimeError("oCPC项目写入后未能回读到项目ID")
    return int(found["targetPackageId"])


def _upload_keywords(
    db,
    task: BackgroundTask,
    client,
    account: Account,
    operation: Operation,
    state: dict,
    units: list[dict],
    unit_ids: dict[str, int],
    materials: dict[str, MaterialKeyword],
    campaign_ids: dict[str, int],
) -> list[dict]:
    results: list[dict] = state.setdefault("keyword_upload_results", [])
    rejection_state = state.setdefault("keyword_rejections", {})
    completed_units = {row["unit_name"] for row in results if row.get("complete")}
    pending_units: list[tuple[int, str, list[dict]]] = []
    runtime: dict[str, dict] = {}
    for unit_index, unit in enumerate(units, start=1):
        if unit["name"] in completed_units:
            continue
        adgroup_id = unit_ids[unit["name"]]
        campaign_id = campaign_ids[unit["campaign_name"]]
        existing = {
            str(row.get("keyword") or "").casefold()
            for row in _read_keywords(client, account, operation, adgroup_id)
        }
        rejected_rows = rejection_state.get(unit["name"])
        if not isinstance(rejected_rows, list):
            rejected_rows = []
        rejected_words = {
            str(row.get("keyword") or "").casefold()
            for row in rejected_rows
            if isinstance(row, dict)
        }
        pending: list[dict] = []
        for text in unit["keywords"]:
            if text.casefold() in existing or text.casefold() in rejected_words:
                continue
            material = materials[text.casefold()]
            keyword = {
                "campaignId": campaign_id,
                "adgroupId": adgroup_id,
                "keyword": text,
                "matchType": 2,
                "phraseType": 1,
                "pause": False,
            }
            tracking_url = build_keyword_tracking_url(account, material.keyword_utf8_encoded)
            if tracking_url:
                keyword["pcDestinationUrl"] = tracking_url
                keyword["mobileDestinationUrl"] = tracking_url
            pending.append(keyword)
        runtime[unit["name"]] = {
            "unit_index": unit_index,
            "unit": unit,
            "adgroup_id": adgroup_id,
            "rejected_rows": rejected_rows,
            "rejected_words": rejected_words,
            "existing_words": existing,
            "acknowledged_words": set(),
        }
        if pending:
            pending_units.append((unit_index, unit["name"], pending))

    batches = _pack_keyword_unit_batches(pending_units)
    state["keyword_batch_plan"] = [
        {
            "batch_number": batch_number,
            "keyword_count": sum(len(entry[2]) for entry in batch),
            "units": [
                {"unit_name": entry[1], "keyword_count": len(entry[2])}
                for entry in batch
            ],
        }
        for batch_number, batch in enumerate(batches, start=1)
    ]
    _save(db, task, state, "keyword_batches_planned", 48)
    deferred_for_activation = False
    for batch_index, unit_batch in enumerate(batches, start=1):
        keyword_batch = [keyword for entry in unit_batch for keyword in entry[2]]
        payload = {"keywordTypes": keyword_batch}
        writes: list[tuple[list[dict], dict, str]] = []
        try:
            write_result = client.execute_write(
                _context(account, operation, f"keyword-batch-{batch_index}", payload),
                "keyword.add",
                payload,
            )
            writes.append((keyword_batch, write_result, str(batch_index)))
        except RuntimeError as exc:
            if "901676" not in str(exc):
                raise
            remaining_count = sum(
                len(entry[2])
                for remaining_batch in batches[batch_index - 1:]
                for entry in remaining_batch
            )
            state["keyword_upload_deferred"] = {
                "reason_code": "901676",
                "reason": "baidu_unactivated_account_keyword_limit",
                "failed_batch_number": batch_index,
                "failed_batch_keyword_count": len(keyword_batch),
                "remaining_keyword_count": remaining_count,
                "deferred_at": datetime.now(UTC).isoformat(),
            }
            state.pop("keyword_batch_fallbacks", None)
            deferred_for_activation = True
            _save(db, task, state, "keyword_deferred_for_account_activation", 78)
            break
        adgroup_to_unit = {
            runtime[unit_name]["adgroup_id"]: unit_name for _, unit_name, _ in unit_batch
        }
        for submitted_rows, submitted_result, request_part in writes:
            failures = submitted_result.get("header", {}).get("failures") or []
            failed_indices: set[int] = set()
            for failure in failures:
                position = str(failure.get("position") or "")
                match = re.search(r"keywordTypes\[(\d+)\]", position)
                if not match:
                    raise RuntimeError("百度关键词部分失败无法定位到具体词")
                failed_index = int(match.group(1))
                failed_indices.add(failed_index)
                if not 0 <= failed_index < len(submitted_rows):
                    raise RuntimeError("百度关键词部分失败位置超出本批范围")
                failed_row = submitted_rows[failed_index]
                unit_name = adgroup_to_unit.get(int(failed_row["adgroupId"]))
                if unit_name is None:
                    raise RuntimeError("百度关键词部分失败无法归属到具体单元")
                failed_keyword = failed_row["keyword"]
                unit_runtime = runtime[unit_name]
                unit_runtime["rejected_words"].add(failed_keyword.casefold())
                unit_runtime["rejected_rows"].append({
                    "keyword": failed_keyword,
                    "code": str(failure.get("code") or ""),
                    "message": str(failure.get("message") or ""),
                    "position": position,
                    "request_batch": request_part,
                })
            for submitted_index, submitted_row in enumerate(submitted_rows):
                if submitted_index in failed_indices:
                    continue
                unit_name = adgroup_to_unit.get(int(submitted_row["adgroupId"]))
                if unit_name is not None:
                    runtime[unit_name]["acknowledged_words"].add(
                        str(submitted_row["keyword"]).casefold()
                    )
        for _, unit_name, _ in unit_batch:
            rejection_state[unit_name] = runtime[unit_name]["rejected_rows"]
        state["keyword_rejections"] = rejection_state
        state["keyword_batches_completed"] = int(state.get("keyword_batches_completed") or 0) + 1
        progress = min(78, 48 + round(batch_index / max(1, len(batches)) * 30))
        _save(db, task, state, f"keywords_batch_{batch_index}", progress)

    if deferred_for_activation:
        result_by_unit = {row["unit_name"]: row for row in results}
        for unit_name, unit_runtime in runtime.items():
            unit = unit_runtime["unit"]
            planned_words = {str(value).casefold() for value in unit["keywords"]}
            uploaded_words = (
                unit_runtime["existing_words"] | unit_runtime["acknowledged_words"]
            ) & planned_words
            rejected_words = unit_runtime["rejected_words"] & planned_words
            result_by_unit[unit_name] = {
                "unit_name": unit_name,
                "adgroup_id": unit_runtime["adgroup_id"],
                "planned_keyword_count": len(planned_words),
                "uploaded_keyword_count": len(uploaded_words),
                "acknowledged_keyword_count": len(unit_runtime["acknowledged_words"]),
                "distinct_keyword_count": len(uploaded_words),
                "duplicate_keyword_count": 0,
                "rejected_keyword_count": len(rejected_words),
                "verification_mode": "pre_write_readback_and_api_acknowledged",
                "post_write_readback_skipped": True,
                "complete": len(uploaded_words | rejected_words) >= len(planned_words),
            }
        results = list(result_by_unit.values())
        state["keyword_upload_results"] = results
        state["keyword_completion_mode"] = "deferred_until_account_activation"
        _save(db, task, state, "keyword_activation_bootstrap_ready", 80)
        return results

    state.pop("keyword_upload_deferred", None)
    state["keyword_completion_mode"] = "api_acknowledged_without_post_write_readback"
    for unit_name, unit_runtime in runtime.items():
        unit_index = unit_runtime["unit_index"]
        unit = unit_runtime["unit"]
        adgroup_id = unit_runtime["adgroup_id"]
        rejected_words = unit_runtime["rejected_words"]
        acknowledged_count = len(unit["keywords"]) - len(rejected_words)
        results.append({
            "unit_name": unit["name"],
            "adgroup_id": adgroup_id,
            "planned_keyword_count": len(unit["keywords"]),
            "uploaded_keyword_count": acknowledged_count,
            "acknowledged_keyword_count": acknowledged_count,
            "distinct_keyword_count": None,
            "duplicate_keyword_count": None,
            "rejected_keyword_count": len(rejected_words),
            "verification_mode": "api_acknowledged",
            "post_write_readback_skipped": True,
            "complete": True,
        })
        state["keyword_upload_results"] = results
        _save(db, task, state, f"keywords_acknowledged_{unit_index}", min(80, 50 + unit_index * 3))
    return results


def _create_audiences(
    client,
    account: Account,
    operation: Operation,
    campaign_ids: list[int],
) -> list[int]:
    audience_rules = _operation_build_rules(operation).get("audiences") or {}
    definitions = audience_rules.get("definitions") or []
    if not definitions:
        return []
    query_payload = {
        "crowdFields": [
            "crowdId", "crowdName", "age", "customAge", "sex", "inPeople", "idPack",
            "crowdDirectType", "effectType",
        ],
        "crowdDirectType": [0, 3, 4, 10],
        "limit": [0, 1000],
        "desc": True,
    }
    existing = result_rows(client.execute_read(
        _read_context(account, operation), "crowd.get", query_payload
    ))
    by_name = {row.get("crowdName"): int(row["crowdId"]) for row in existing if row.get("crowdId")}
    missing: list[dict] = []
    for definition in definitions:
        if definition.get("name") in by_name:
            continue
        row = {
            "crowdName": definition["name"],
            "age": definition.get("age") or [0],
            "sex": int(definition.get("sex") or 0),
            "inPeople": definition.get("in_people") or [],
            "crowdDirectType": int(definition.get("direct_type") or 0),
            "effectType": int(definition.get("effect_type") or 0),
        }
        if definition.get("custom_age"):
            row["customAge"] = definition["custom_age"]
            row.pop("age", None)
        if definition.get("id_pack"):
            row["idPack"] = definition["id_pack"]
        missing.append(row)
    if missing:
        payload = {"crowdTypes": missing}
        client.execute_write(
            _context(account, operation, "crowd-add", payload), "crowd.add", payload
        )
        existing = result_rows(client.execute_read(
            _read_context(account, operation), "crowd.get", query_payload
        ))
        by_name = {row.get("crowdName"): int(row["crowdId"]) for row in existing if row.get("crowdId")}
    crowd_ids = [by_name[definition["name"]] for definition in definitions if definition.get("name") in by_name]
    if len(crowd_ids) != len(definitions):
        raise RuntimeError("人群写入后未能完整回读")

    binding = audience_rules.get("binding") or {}
    ratio = float(binding.get("price_ratio") or 1.0)
    existing_bindings = result_rows(client.execute_read(
        _read_context(account, operation),
        "crowd.bind.get",
        {
            "crowdBindFields": ["bindId", "targetType", "targetId", "crowdPriceRatio", "crowdId"],
            "idType": 3,
            "ids": campaign_ids,
        },
    ))
    bound_pairs = {
        (int(row.get("targetId") or row.get("campaignId") or 0), int(row["crowdId"]))
        for row in existing_bindings
        if row.get("crowdId")
    }
    missing_bindings = [
        {
            "targetType": int(binding.get("target_type") or 1),
            "targetId": campaign_id,
            "crowdPriceRatio": ratio,
            "crowdId": crowd_id,
        }
        for campaign_id in campaign_ids
        for crowd_id in crowd_ids
        if (campaign_id, crowd_id) not in bound_pairs
    ]
    if missing_bindings:
        payload = {"crowdBindTypes": missing_bindings}
        client.execute_write(
            _context(account, operation, "crowd-bind-add", payload), "crowd.bind.add", payload
        )
    return crowd_ids


def _create_creatives(
    db,
    client,
    account: Account,
    operation: Operation,
    adgroup_campaign_ids: dict[int, int],
    target_adgroup_ids: list[int],
    reg_domain: str,
    replacement_round: int = 0,
) -> list[int]:
    assignments = operation.payload.get("creative_combinations") or []
    if not assignments:
        raise ValueError("任务没有固化创意组合")
    if not target_adgroup_ids:
        raise ValueError("没有成功上传关键词的单元，禁止新建创意")
    destination_url = str(account.landing_url_template or "").strip()
    if not destination_url or not urlparse(destination_url).netloc:
        raise ValueError("账户推广链接无效")
    existing = _read_creatives(client, account, operation, target_adgroup_ids)
    existing_by_key = {
        _creative_readback_key(
            int(row.get("adgroupId") or 0),
            str(row.get("title") or ""),
            str(row.get("description1") or ""),
            str(row.get("description2") or ""),
        ): int(row["creativeId"])
        for row in existing
        if row.get("creativeId")
    }
    rows: list[dict] = []
    assignment_targets: dict[str, list[tuple[int, tuple]]] = {
        str(assignment["assignment_id"]): [] for assignment in assignments
    }
    assignment_by_key: dict[tuple[int, str, str], str] = {}
    for adgroup_id in target_adgroup_ids:
        for assignment in assignments:
            key = _creative_readback_key(
                adgroup_id,
                str(assignment.get("title") or ""),
                str(assignment.get("description1") or ""),
                str(assignment.get("description2") or ""),
            )
            assignment_id = str(assignment["assignment_id"])
            assignment_targets[assignment_id].append((adgroup_id, key))
            assignment_by_key[key] = assignment_id
            if key in existing_by_key:
                continue
            rows.append({
                "campaignId": adgroup_campaign_ids[adgroup_id],
                "adgroupId": adgroup_id,
                "title": str(assignment.get("title") or ""),
                "description1": str(assignment.get("description1") or ""),
                "description2": str(assignment.get("description2") or ""),
                "mobileDestinationUrl": destination_url,
                "mobileDisplayUrl": reg_domain,
                "pcDestinationUrl": destination_url,
                "pcDisplayUrl": reg_domain,
                "pause": False,
            })
    for batch_index, creative_batch in enumerate(_chunks(rows), start=1):
        payload = {"creativeTypes": creative_batch}
        try:
            client.execute_write(
                _context(account, operation, f"creative-add-{batch_index}", payload),
                "creative.add",
                payload,
            )
        except RuntimeError as exc:
            error_code = next(
                (code for code in CREATIVE_DIRECT_REJECTION_CODES if code in str(exc)),
                "",
            )
            if error_code not in CREATIVE_DIRECT_REJECTION_CODES:
                raise
            rejected_assignment_ids = sorted({
                assignment_by_key[_creative_readback_key(
                    int(row["adgroupId"]),
                    str(row.get("title") or ""),
                    str(row.get("description1") or ""),
                    str(row.get("description2") or ""),
                )]
                for row in creative_batch
            })
            if replacement_round >= 5:
                raise RuntimeError("创意审核通过组合自动补位已达到5轮") from exc
            _replace_creative_assignments(
                db,
                operation,
                rejected_assignment_ids,
                reason=(
                    f"百度新增创意直接拒绝（{error_code}），"
                    "原组合已累计拒绝并改用审核通过组合"
                ),
            )
            return _create_creatives(
                db,
                client,
                account,
                operation,
                adgroup_campaign_ids,
                target_adgroup_ids,
                reg_domain,
                replacement_round + 1,
            )
    existing_by_key: dict[tuple, int] = {}
    for readback_attempt in range(4):
        existing = _read_creatives(client, account, operation, target_adgroup_ids)
        existing_by_key = {
            _creative_readback_key(
                int(row.get("adgroupId") or 0),
                str(row.get("title") or ""),
                str(row.get("description1") or ""),
                str(row.get("description2") or ""),
            ): int(row["creativeId"])
            for row in existing
            if row.get("creativeId")
        }
        if all(
            key in existing_by_key
            for targets in assignment_targets.values()
            for _, key in targets
        ):
            break
        if readback_attempt < 3:
            time.sleep(4)

    missing_by_assignment = {
        assignment_id: [
            (adgroup_id, key)
            for adgroup_id, key in targets
            if key not in existing_by_key
        ]
        for assignment_id, targets in assignment_targets.items()
    }
    missing_by_assignment = {
        assignment_id: missing
        for assignment_id, missing in missing_by_assignment.items()
        if missing
    }
    if missing_by_assignment:
        partially_written = {
            assignment_id: missing
            for assignment_id, missing in missing_by_assignment.items()
            if len(missing) != len(target_adgroup_ids)
        }
        if partially_written:
            raise RuntimeError("同一创意在不同单元的写入结果不一致，已停止自动替换")
        if replacement_round >= 5:
            raise RuntimeError("创意自动补足已达到5轮，仍未能完整回读")
        _replace_creative_assignments(
            db,
            operation,
            list(missing_by_assignment),
            reason="百度新增接口逐项拒绝，已从创意中心自动补位",
        )
        return _create_creatives(
            db,
            client,
            account,
            operation,
            adgroup_campaign_ids,
            target_adgroup_ids,
            reg_domain,
            replacement_round + 1,
        )
    creative_ids: list[int] = []
    for assignment_id, targets in assignment_targets.items():
        target_rows = []
        for adgroup_id, key in targets:
            creative_id = existing_by_key.get(key)
            if not creative_id:
                raise RuntimeError("创意写入后未能完整回读")
            creative_ids.append(creative_id)
            target_rows.append({
                "campaign_id": adgroup_campaign_ids[adgroup_id],
                "adgroup_id": adgroup_id,
                "creative_id": creative_id,
            })
        row = db.get(CreativeAssignment, uuid.UUID(assignment_id))
        if row is not None:
            row.baidu_creative_id = target_rows[0]["creative_id"]
            row.status = "submitted"
            row.submitted_at = datetime.now(UTC)
            row.creative_payload = {
                "destination_url": destination_url,
                "distribution": "50_creatives_per_keyword_adgroup",
                "targets": target_rows,
            }
    db.commit()
    return creative_ids


def _replace_creative_assignments(
    db,
    operation: Operation,
    rejected_assignment_ids: list[str],
    *,
    reason: str,
) -> list[str]:
    """Replace add-time rejected combinations while preserving the 50 account slots."""

    creative_payload = list(operation.payload.get("creative_combinations") or [])
    rejected_ids = {str(value) for value in rejected_assignment_ids}
    rejected_payloads = [
        row for row in creative_payload if str(row.get("assignment_id")) in rejected_ids
    ]
    if len(rejected_payloads) != len(rejected_ids):
        raise RuntimeError("创意补位时未找到全部被拒绝的组合")
    assignments = {
        str(row.id): row
        for row in db.scalars(
            select(CreativeAssignment).where(
                CreativeAssignment.id.in_([uuid.UUID(value) for value in rejected_ids])
            )
        ).all()
    }
    if len(assignments) != len(rejected_ids):
        raise RuntimeError("创意补位时未找到全部投放槽位")

    project_id = next(iter(assignments.values())).project_id
    segments = db.scalars(
        select(CreativeSegment).where(CreativeSegment.project_id == project_id)
    ).all()
    combinations = db.scalars(
        select(CreativeCombination).where(CreativeCombination.project_id == project_id)
    ).all()
    combination_map = {row.combination_hash: row for row in combinations}
    active_hashes = {
        str(row.get("combination_hash") or "") for row in creative_payload
    }
    approved_counts = dict(db.execute(
        select(
            CreativeAssignment.combination_id,
            func.count(CreativeAssignment.id),
        )
        .where(
            CreativeAssignment.project_id == project_id,
            CreativeAssignment.status == "approved",
            CreativeAssignment.baidu_creative_id.is_not(None),
        )
        .group_by(CreativeAssignment.combination_id)
    ).all())
    candidates = _approved_creative_candidates(
        combinations,
        segments,
        approved_counts,
        active_hashes,
    )
    if len(candidates) < len(rejected_ids):
        raise RuntimeError("创意中心没有足够的审核通过且未使用组合用于补位")

    replacements: dict[str, dict] = {}
    new_assignment_ids: list[str] = []
    for rejected_payload, candidate in zip(rejected_payloads, candidates):
        assignment_id = str(rejected_payload["assignment_id"])
        old_assignment = assignments[assignment_id]
        old_assignment.status = "rejected_at_add"
        old_assignment.main_reason = "add_rejected"
        old_assignment.detail_reason = reason
        old_assignment.rejection_recorded = True
        old_combination = db.get(CreativeCombination, old_assignment.combination_id)
        old_account = db.get(Account, old_assignment.account_id)
        if (
            old_combination is not None
            and old_account is not None
            and old_account.account_type == AccountType.SECOND_HOP
        ):
            record_second_hop_creative_rejection(db, old_combination)

        combination = ensure_creative_center_combination(
            db, project_id, candidate, combination_map
        )
        replacement = CreativeAssignment(
            id=uuid.uuid4(),
            project_id=old_assignment.project_id,
            job_id=old_assignment.job_id,
            account_id=old_assignment.account_id,
            combination_id=combination.id,
            slot_number=old_assignment.slot_number,
            generation=old_assignment.generation + 1,
            status="replacement_pending_submit",
        )
        db.add(replacement)
        replacement_payload = {
            "assignment_id": str(replacement.id),
            "combination_id": str(combination.id),
            "combination_hash": candidate.combination_hash,
            "slot_number": old_assignment.slot_number,
            "title": candidate.title,
            "description1": candidate.description1,
            "description2": candidate.description2,
        }
        replacements[assignment_id] = replacement_payload
        new_assignment_ids.append(str(replacement.id))
        active_hashes.add(candidate.combination_hash)

    updated_payload = dict(operation.payload)
    updated_payload["creative_combinations"] = [
        replacements.get(str(row.get("assignment_id")), row)
        for row in creative_payload
    ]
    operation.payload = updated_payload
    flag_modified(operation, "payload")
    db.commit()
    return new_assignment_ids


def _approved_creative_candidates(
    combinations: list[CreativeCombination],
    segments: list[CreativeSegment],
    approved_counts: dict[uuid.UUID, int],
    active_hashes: set[str],
) -> list[CreativeCandidate]:
    """Return only Baidu-approved combinations, most proven first."""

    segment_map = {row.id: row for row in segments}
    candidates: list[tuple[int, CreativeCandidate]] = []
    for combination in combinations:
        approved_count = int(approved_counts.get(combination.id) or 0)
        if (
            approved_count <= 0
            or combination.is_blacklisted
            or combination.combination_hash in active_hashes
        ):
            continue
        title = segment_map.get(combination.title_segment_id)
        description1 = segment_map.get(combination.description1_segment_id)
        description2 = (
            segment_map.get(combination.description2_segment_id)
            if combination.description2_segment_id
            else None
        )
        if title is None or description1 is None:
            continue
        candidates.append((approved_count, CreativeCandidate(
            combination_hash=combination.combination_hash,
            title_id=title.id,
            description1_id=description1.id,
            description2_id=description2.id if description2 else None,
            title=title.content,
            description1=description1.content,
            description2=description2.content if description2 else "",
        )))
    candidates.sort(key=lambda row: (-row[0], row[1].combination_hash))
    return [candidate for _, candidate in candidates]


def execute_ad_build_workflow(db, task: BackgroundTask, operation: Operation, client) -> dict:
    if operation.operation_type != "search_ad_build_workflow":
        raise ValueError("不是搜索广告搭建任务")
    if operation.payload.get("workflow_version") != "weight-loss-account-flow-v5":
        raise ValueError("旧版广告搭建任务已失效，请重新预检后执行")
    account = db.scalar(select(Account).where(Account.baidu_account_id == operation.target_account_id))
    if account is None:
        raise ValueError("目标账户不存在")
    if task.project_id is not None and account.project_id != task.project_id:
        raise ValueError("任务项目与目标账户不一致")
    if account.login_name != operation.payload.get("target_login_name"):
        raise ValueError("目标账户上下文不一致")

    prior = task.result if isinstance(task.result, dict) else {}
    state = prior.get("workflow_state") if isinstance(prior.get("workflow_state"), dict) else {}
    state.setdefault("ocpc_name", "减肥项目")
    state.setdefault("started_at", datetime.now(UTC).isoformat())
    _phase_start(state, "total")

    _phase_start(state, "material_preflight")
    _save(db, task, state, "material_preflight", 5)
    plan, materials = _build_material_plan(db, account, operation)
    account_plan = plan["accounts"][0]
    units = account_plan["units"]
    campaign_names = list(dict.fromkeys(unit["campaign_name"] for unit in units))
    state["keyword_plan_summary"] = {
        "unit_count": account_plan["unit_count"],
        "keyword_instances": account_plan["keyword_instances"],
        "abc_percent": account_plan["abc_percent"],
        "def_percent": account_plan["def_percent"],
        "batch": plan["batch"],
    }
    _phase_finish(state, "material_preflight")
    _save(db, task, state, "permission_and_material_preflight", 10)

    _phase_start(state, "account_settings")
    account_info = _read_account(client, account, operation)
    reg_domain = str(account_info.get("regDomain") or "").strip()
    if not reg_domain:
        raise ValueError("百度账户未返回注册域名，无法创建创意")
    if state.get("keyword_upload_deferred") and int(account_info.get("userLevel") or 4) == 4:
        remaining = int(state["keyword_upload_deferred"].get("remaining_keyword_count") or 0)
        raise RuntimeError(
            "BAIDU_ACCOUNT_ACTIVATION_REQUIRED: 百度账户仍为未生效客户"
            f"（userLevel=4），剩余 {remaining} 条关键词将在账户生效后断点续传"
        )
    region_target = operation.payload.get("region_target") or []
    if not region_target:
        raise ValueError("任务没有设置账户推广地域")
    account_payload = {
        "accountInfo": {
            "budget": 50.0,
            "budgetType": 1,
            "regionTarget": region_target,
            "geoLocationStatus": int(operation.payload.get("geo_location_status", 1)),
        }
    }
    if not state.get("account_updated"):
        client.execute_write(
            _context(account, operation, "account-update", account_payload),
            "account.update",
            account_payload,
        )
        account_info = _read_account(client, account, operation)
        if float(account_info.get("budget") or 0) != 50.0:
            raise RuntimeError("账户预算写入后回读不一致")
        if sorted(account_info.get("regionTarget") or []) != sorted(region_target):
            raise RuntimeError("账户推广地域写入后回读不一致")
        state["account_updated"] = True
        state["account_region_count"] = len(region_target)
        _save(db, task, state, "account_settings_verified", 20)
    _phase_finish(state, "account_settings")

    _phase_start(state, "campaigns")
    campaign_ids = state.get("campaign_ids") if isinstance(state.get("campaign_ids"), dict) else {}
    if set(campaign_ids) != set(campaign_names):
        campaign_ids = {
            campaign_name: _create_campaign(
                client,
                account,
                operation,
                campaign_name,
                int(account_info.get("userLevel") or 4),
            )
            for campaign_name in campaign_names
        }
        state["campaign_ids"] = campaign_ids
        _save(db, task, state, "campaign_verified", 35)
    _phase_finish(state, "campaigns")

    _phase_start(state, "adgroups")
    unit_ids = state.get("unit_ids") if isinstance(state.get("unit_ids"), dict) else {}
    pending_adgroups = (
        state.get("adgroup_readback_pending")
        if isinstance(state.get("adgroup_readback_pending"), dict)
        else None
    )
    if pending_adgroups:
        resolved_ids, still_missing = _verify_pending_adgroups(
            client, account, operation, pending_adgroups
        )
        unit_ids.update(resolved_ids)
        state["unit_ids"] = unit_ids
        if still_missing:
            now = datetime.now(UTC)
            first_wait_at = datetime.fromisoformat(str(pending_adgroups["first_wait_at"]))
            if now - first_wait_at >= ADGROUP_READBACK_TIMEOUT:
                names = [str(item.get("name") or "") for item in still_missing]
                raise ReadbackVerificationTimeout(
                    "单元写入已确认，但百度延迟回读超过10分钟，需要人工核对："
                    + "、".join(names[:3])
                )
            pending_adgroups["expected"] = still_missing
            pending_adgroups["attempts"] = int(pending_adgroups.get("attempts") or 0) + 1
            pending_adgroups["next_check_at"] = (
                now + timedelta(seconds=ADGROUP_READBACK_DELAY_SECONDS)
            ).isoformat()
            state["adgroup_readback_pending"] = pending_adgroups
            _save(db, task, state, "adgroup_readback_wait", 44)
            raise DelayedReadbackPending(
                f"百度单元数据尚未全部可见，{ADGROUP_READBACK_DELAY_SECONDS}秒后仅回读验证，"
                "不会重复创建单元"
            )
        state.pop("adgroup_readback_pending", None)
        _save(db, task, state, "adgroups_verified", 45)
    if len(unit_ids) != len(units):
        max_price = float(_operation_build_rules(operation).get("adgroup", {}).get("max_price") or 1.0)
        unit_ids = dict(unit_ids)
        pending_expected: list[dict] = []
        for campaign_name in campaign_names:
            campaign_units = [unit for unit in units if unit["campaign_name"] == campaign_name]
            build_result = _create_adgroups(
                client,
                account,
                operation,
                int(campaign_ids[campaign_name]),
                campaign_units,
                max_price,
            )
            unit_ids.update(build_result.unit_ids)
            pending_expected.extend(
                {"campaign_id": int(campaign_ids[campaign_name]), "name": name}
                for name in build_result.pending_names
            )
        state["unit_ids"] = unit_ids
        if pending_expected:
            now = datetime.now(UTC)
            state["adgroup_readback_pending"] = {
                "expected": pending_expected,
                "first_wait_at": now.isoformat(),
                "next_check_at": (
                    now + timedelta(seconds=ADGROUP_READBACK_DELAY_SECONDS)
                ).isoformat(),
                "attempts": 0,
                "write_replay_forbidden": True,
            }
            _save(db, task, state, "adgroup_readback_wait", 44)
            raise DelayedReadbackPending(
                f"百度已确认单元写入，{ADGROUP_READBACK_DELAY_SECONDS}秒后仅回读验证，"
                "不会重复创建单元"
            )
        if len(unit_ids) != len(units):
            unresolved = [unit["name"] for unit in units if unit["name"] not in unit_ids]
            raise RuntimeError(f"单元写入后未获得ID：{', '.join(unresolved[:3])}")
        _save(db, task, state, "adgroups_verified", 45)
    _phase_finish(state, "adgroups")

    _phase_start(state, "ocpc")
    if not state.get("ocpc_project_id"):
        state["ocpc_project_id"] = _create_ocpc_project(
            client,
            account,
            operation,
            [int(campaign_ids[name]) for name in campaign_names],
            state,
        )
        _save(db, task, state, "ocpc_project_verified", 48)
    _phase_finish(state, "ocpc")

    _phase_start(state, "keywords")
    upload_results = _upload_keywords(
        db,
        task,
        client,
        account,
        operation,
        state,
        units,
        unit_ids,
        materials,
        {name: int(value) for name, value in campaign_ids.items()},
    )
    target_adgroup_ids = keyword_uploaded_adgroup_ids(upload_results)
    state["keyword_adgroup_ids"] = target_adgroup_ids
    state["keyword_count"] = sum(int(row["uploaded_keyword_count"]) for row in upload_results)
    _phase_finish(state, "keywords")
    _save(db, task, state, "keywords_acknowledged", 82)

    _phase_start(state, "audiences")
    if not state.get("audience_ids"):
        state["audience_ids"] = _create_audiences(
            client,
            account,
            operation,
            [int(campaign_ids[name]) for name in campaign_names],
        )
        _save(db, task, state, "audiences_verified", 88)
    _phase_finish(state, "audiences")

    _phase_start(state, "creatives")
    adgroup_campaign_ids = {
        unit_ids[unit["name"]]: int(campaign_ids[unit["campaign_name"]])
        for unit in units
    }
    state["creative_ids"] = _create_creatives(
        db,
        client,
        account,
        operation,
        adgroup_campaign_ids,
        target_adgroup_ids,
        reg_domain,
    )
    _save(db, task, state, "creatives_verified", 96)
    _phase_finish(state, "creatives")

    deferred = state.get("keyword_upload_deferred")
    if isinstance(deferred, dict):
        deferred["bootstrap_adgroup_count"] = len(target_adgroup_ids)
        deferred["bootstrap_creative_count"] = len(state["creative_ids"])
        state["keyword_upload_deferred"] = deferred
        _save(db, task, state, "awaiting_baidu_account_activation", 96)
        raise RuntimeError(
            "BAIDU_ACCOUNT_ACTIVATION_REQUIRED: 已为现有关键词单元补齐创意；"
            f"账户生效后续传剩余 {int(deferred.get('remaining_keyword_count') or 0)} 条关键词"
        )

    _phase_start(state, "final_readback")
    final_campaigns = _read_campaigns(client, account, operation)
    remote_campaign_ids = {int(row.get("campaignId") or 0) for row in final_campaigns}
    if not set(int(value) for value in campaign_ids.values()).issubset(remote_campaign_ids):
        raise RuntimeError("最终回读未找到本次计划")
    final_adgroup_ids: set[int] = set()
    for campaign_id in campaign_ids.values():
        final_adgroup_ids.update(
            int(row.get("adgroupId") or 0)
            for row in _read_adgroups(client, account, operation, int(campaign_id))
        )
    if len(final_adgroup_ids & set(unit_ids.values())) != len(unit_ids):
        raise RuntimeError("最终回读的单元数量不完整")
    state["readback"] = {
        "campaign_count": len(campaign_ids),
        "adgroup_count": len(unit_ids),
        "keyword_count": state["keyword_count"],
        "creative_count": len(state["creative_ids"]),
        "audience_count": len(state["audience_ids"]),
    }
    _phase_finish(state, "final_readback")
    _phase_finish(state, "total")
    state["completed_at"] = datetime.now(UTC).isoformat()
    _store_verified_campaign_cache(db, account, final_campaigns)
    account.lifecycle_stage = TESTING
    account.lifecycle_evaluated_at = datetime.now(UTC)
    account.active_keyword_count = state["keyword_count"]
    _save(db, task, state, "complete", 100)
    return state


def execute_ad_build_cleanup(db, task: BackgroundTask, operation: Operation, client) -> dict:
    """Delete one tracked ad-build result by its exact remote object ids."""

    if operation.operation_type not in {"search_ad_build_cleanup", "account_retirement"}:
        raise ValueError("不是搜索广告清理任务")
    retirement_only = operation.operation_type == "account_retirement"
    account = db.scalar(select(Account).where(Account.baidu_account_id == operation.target_account_id))
    if account is None:
        raise ValueError("目标账户不存在")
    if task.project_id is not None and account.project_id != task.project_id:
        raise ValueError("任务项目与目标账户不一致")
    if account.login_name != operation.payload.get("target_login_name"):
        raise ValueError("目标账户上下文不一致")

    prior = task.result if isinstance(task.result, dict) else {}
    state = prior.get("workflow_state") if isinstance(prior.get("workflow_state"), dict) else {}
    state.setdefault("started_at", datetime.now(UTC).isoformat())
    _phase_start(state, "total")

    campaign_source = operation.payload.get("campaign_ids") or {}
    campaign_ids = sorted({
        int(value) for value in (
            campaign_source.values() if isinstance(campaign_source, dict) else campaign_source
        )
    })
    unit_source = operation.payload.get("unit_ids") or {}
    unit_ids = sorted({
        int(value) for value in (
            unit_source.values() if isinstance(unit_source, dict) else unit_source
        )
    })
    audience_ids = sorted({int(value) for value in operation.payload.get("audience_ids") or []})
    ocpc_project_ids = sorted({
        int(value) for value in operation.payload.get("ocpc_project_ids") or []
        if int(value) > 0
    })
    if not ocpc_project_ids and operation.payload.get("ocpc_project_id"):
        ocpc_project_ids = [int(operation.payload["ocpc_project_id"])]
    if not campaign_ids:
        raise ValueError("清理任务缺少计划的精确对象编号")

    state["target_counts"] = {
        "campaigns": len(campaign_ids),
        "adgroups": len(unit_ids),
        "audiences": len(audience_ids),
        "ocpc_projects": len(ocpc_project_ids),
    }
    _save(db, task, state, "cleanup_inventory_verified", 10)

    _phase_start(state, "audience_bindings")
    binding_query = {
        "crowdBindFields": ["bindId", "targetType", "targetId", "campaignId", "crowdId"],
        "idType": 3,
        "ids": campaign_ids,
    }
    if retirement_only:
        binding_ids = []
    elif "audience_bindings_deleted" in state:
        binding_ids = [int(value) for value in state["audience_bindings_deleted"]]
    else:
        existing_campaign_ids = sorted({
            int(row.get("campaignId") or 0)
            for row in _read_campaigns(client, account, operation)
            if int(row.get("campaignId") or 0) in campaign_ids
        })
        if existing_campaign_ids:
            binding_query["ids"] = existing_campaign_ids
            binding_rows = result_rows(client.execute_read(
                _read_context(account, operation), "crowd.bind.get", binding_query
            ))
            binding_ids = sorted({
                int(row["bindId"])
                for row in binding_rows
                if row.get("bindId")
                and int(row.get("targetId") or row.get("campaignId") or 0) in campaign_ids
                and (not audience_ids or int(row.get("crowdId") or 0) in audience_ids)
            })
        else:
            binding_ids = []
    if binding_ids and "audience_bindings_deleted" not in state:
        for batch_number, ids in enumerate(_chunks(binding_ids, 10000), start=1):
            payload = {"bindIds": ids}
            client.execute_write(
                _context(account, operation, f"crowd-bind-delete-{batch_number}", payload),
                "crowd.bind.delete",
                payload,
            )
        state["audience_bindings_deleted"] = binding_ids
    _phase_finish(state, "audience_bindings")
    _save(db, task, state, "audience_bindings_deleted", 25)

    _phase_start(state, "ocpc")
    ocpc_query = {
        "targetPackageTypeFields": ["targetPackageId", "targetPackageName", "scope", "packageStatus"],
        "ids": [account.baidu_account_id],
        "level": 1,
    }
    current_ocpc = result_rows(client.execute_read(
        _read_context(account, operation), "ocpc.get", ocpc_query
    )) if ocpc_project_ids else []
    existing_ocpc_ids = sorted({
        int(row.get("targetPackageId") or 0)
        for row in current_ocpc
        if int(row.get("targetPackageId") or 0) in ocpc_project_ids
    })
    for batch_number, ids in enumerate(_chunks(existing_ocpc_ids, 100), start=1):
        payload = {"targetPackageIds": ids}
        client.execute_write(
            _context(account, operation, f"ocpc-delete-{batch_number}", payload), "ocpc.delete", payload
        )
    state["ocpc_deleted"] = existing_ocpc_ids
    _phase_finish(state, "ocpc")
    _save(db, task, state, "ocpc_deleted", 40)

    _phase_start(state, "campaigns")
    remote_campaign_ids = {
        int(row.get("campaignId") or 0) for row in _read_campaigns(client, account, operation)
    }
    existing_campaign_ids = [value for value in campaign_ids if value in remote_campaign_ids]
    for batch_number, ids in enumerate(_chunks(existing_campaign_ids, 100), start=1):
        payload = {"campaignIds": ids}
        client.execute_write(
            _context(account, operation, f"campaign-delete-{batch_number}", payload),
            "campaign.delete",
            payload,
        )
    state["campaigns_deleted"] = existing_campaign_ids
    _phase_finish(state, "campaigns")
    _save(db, task, state, "campaigns_deleted", 65)

    crowd_query = {
        "crowdFields": ["crowdId", "crowdName", "crowdDirectType"],
        "crowdDirectType": [0, 3, 4, 10],
        "limit": [0, 1000],
        "desc": True,
    }
    _phase_start(state, "audiences")
    if audience_ids:
        current_crowds = result_rows(client.execute_read(
            _read_context(account, operation), "crowd.get", crowd_query
        ))
        existing_crowd_ids = sorted({
            int(row.get("crowdId") or 0)
            for row in current_crowds
            if int(row.get("crowdId") or 0) in audience_ids
        })
        for batch_number, ids in enumerate(_chunks(existing_crowd_ids, 1000), start=1):
            payload = {"crowdIds": ids}
            client.execute_write(
                _context(account, operation, f"crowd-delete-{batch_number}", payload),
                "crowd.delete",
                payload,
            )
        state["audiences_deleted"] = existing_crowd_ids
    _phase_finish(state, "audiences")
    _save(db, task, state, "audiences_deleted", 75)

    _phase_start(state, "final_readback")
    last_verification: dict = {}
    for attempt in range(4):
        remaining_campaigns = sorted({
            int(row.get("campaignId") or 0)
            for row in _read_campaigns(client, account, operation)
            if int(row.get("campaignId") or 0) in campaign_ids
        })
        # Campaign deletion cascades to its units, keywords, and creatives. Baidu
        # returns business error 90111 when querying children through an already
        # deleted parent, so a confirmed-absent campaign is the authoritative
        # readback for all of those descendants.
        remaining_adgroups: set[int] = set()
        remaining_keywords = 0
        remaining_creatives = 0
        for campaign_id in remaining_campaigns:
            campaign_adgroups = _read_adgroups(client, account, operation, campaign_id)
            remaining_adgroups.update(
                int(row.get("adgroupId") or 0)
                for row in campaign_adgroups
                if int(row.get("adgroupId") or 0) in unit_ids
            )
        if remaining_adgroups:
            remaining_keywords = sum(
                len(_read_keywords(client, account, operation, unit_id))
                for unit_id in remaining_adgroups
            )
            remaining_creatives = len(_read_creatives(
                client, account, operation, sorted(remaining_adgroups)
            ))
        remaining_ocpc = [
            int(row.get("targetPackageId") or 0)
            for row in result_rows(client.execute_read(
                _read_context(account, operation), "ocpc.get", ocpc_query
            ))
            if int(row.get("targetPackageId") or 0) in ocpc_project_ids
        ] if ocpc_project_ids else []
        remaining_crowds = [
            int(row.get("crowdId") or 0)
            for row in result_rows(client.execute_read(
                _read_context(account, operation), "crowd.get", crowd_query
            ))
            if int(row.get("crowdId") or 0) in audience_ids
        ] if audience_ids else []
        remaining_bindings = [
            int(row.get("bindId") or 0)
            for row in result_rows(client.execute_read(
                _read_context(account, operation), "crowd.bind.get", binding_query
            ))
            if int(row.get("bindId") or 0) in binding_ids
        ] if binding_ids and remaining_campaigns else []
        last_verification = {
            "remaining_campaign_ids": remaining_campaigns,
            "remaining_adgroup_ids": sorted(remaining_adgroups),
            "remaining_keyword_count": remaining_keywords,
            "remaining_creative_count": remaining_creatives,
            "remaining_ocpc_ids": remaining_ocpc,
            "remaining_audience_ids": remaining_crowds,
            "remaining_binding_ids": remaining_bindings,
        }
        if not any(last_verification.values()):
            break
        if attempt < 3:
            time.sleep(4)
    if any(last_verification.values()):
        raise RuntimeError(f"删除后仍有测试对象残留：{last_verification}")

    state["readback"] = last_verification
    _phase_finish(state, "final_readback")
    _phase_finish(state, "total")
    state["completed_at"] = datetime.now(UTC).isoformat()
    if retirement_only:
        account.lifecycle_stage = ELIMINATED
        account.eliminated_at = datetime.now(UTC)
        account.elimination_reason = "人工淘汰：删除 oCPC 项目和计划"
        db.add(AuditEvent(
            project_id=account.project_id,
            actor=operation.confirmed_by or operation.requested_by,
            action="account.retired",
            target_type="account",
            target_id=str(account.baidu_account_id),
            summary="删除账户 oCPC 项目和计划并标记为已淘汰",
            details={"ocpc_project_ids": existing_ocpc_ids, "campaign_ids": existing_campaign_ids, "task_id": str(task.id)},
        ))
        for cache_row in db.scalars(select(OcpcProjectCache).where(
            OcpcProjectCache.account_id == account.id,
            OcpcProjectCache.is_active.is_(True),
        )).all():
            cache_row.is_active = False
        account.ocpc_cache_status = "succeeded"
        account.ocpc_cache_synced_at = datetime.now(UTC)
    else:
        account.lifecycle_stage = EMPTY
    account.lifecycle_override = None
    account.active_keyword_count = 0
    for cache_row in db.scalars(select(CampaignCache).where(
        CampaignCache.account_id == account.id,
        CampaignCache.is_active.is_(True),
    )).all():
        cache_row.is_active = False
    account.campaign_cache_status = "succeeded" if retirement_only else "stale"
    account.campaign_cache_synced_at = datetime.now(UTC) if retirement_only else None
    _save(db, task, state, "complete", 100)
    return state
