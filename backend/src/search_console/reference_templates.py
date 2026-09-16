import json
from collections import Counter
from typing import Any


REFERENCE_ACCOUNT_ID = 86459649


def chunks(values: list[int], size: int) -> list[list[int]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def field_consensus(rows: list[dict], field: str, default: Any, *, unordered_list: bool = False) -> dict:
    values = [row.get(field, default) for row in rows]
    if unordered_list:
        values = [sorted(value, key=lambda item: _canonical(item)) if isinstance(value, list) else value for value in values]
    if not values:
        return {"value": default, "consistent": False, "variant_count": 0, "variants": []}
    counts = Counter(_canonical(value) for value in values)
    selected, selected_count = counts.most_common(1)[0]
    return {
        "value": json.loads(selected),
        "consistent": len(counts) == 1,
        "variant_count": len(counts),
        "selected_count": selected_count,
        "variants": [{"value": json.loads(value), "count": count} for value, count in counts.most_common()],
    }


def _ocpc_template(projects: list[dict]) -> list[dict]:
    return [{
        "name": row.get("targetPackageName"),
        "ocpc_bid": row.get("ocpcBid"),
        "ocpc_bid_type": row.get("ocpcBidType"),
        "data_flow_data": row.get("dataFlowData") or [],
        "deep_cpa": row.get("ocpcDeepCpa"),
        "deep_type_status": row.get("deepTypeStat"),
        "deep_trans_type_mode": row.get("deepTransTypeMode"),
        "trans_asset": row.get("transAsset"),
        "trans_asset_id": row.get("transAssetId"),
        "asset_type": row.get("assetType") or [],
        "package_status": row.get("packageStatus"),
        "equipment_type": row.get("equipmentType"),
        "scope_mode": "all_campaigns",
        "source_scope_count": len(row.get("scope") or []),
    } for row in projects]


def _audience_template(crowds: list[dict], bindings: list[dict]) -> dict:
    definitions = [{
        "name": row.get("crowdName"),
        "age": sorted(row.get("age") or []),
        "custom_age": sorted(row.get("customAge") or []),
        "sex": row.get("sex"),
        "in_people": sorted(row.get("inPeople") or []),
        "id_pack": sorted(row.get("idPack") or []),
        "direct_type": row.get("crowdDirectType"),
        "effect_type": row.get("effectType"),
        "conversion_level": row.get("conversionLevel"),
        "recent_days": row.get("recentDays"),
        "device_property": row.get("deviceProperty"),
    } for row in crowds]
    return {
        "definitions": definitions,
        "binding": {
            "target_type": field_consensus(bindings, "targetType", None),
            "price_ratio": field_consensus(bindings, "crowdPriceRatio", None),
            "region_target": field_consensus(bindings, "regionTarget", [], unordered_list=True),
        },
    }


def analyze_reference_snapshot(
    account_info: dict,
    campaigns: list[dict],
    adgroups: list[dict],
    keywords: list[dict],
    creatives: list[dict],
    projects: list[dict],
    crowds: list[dict],
    bindings: list[dict],
) -> tuple[dict, dict, dict]:
    """Distill reusable settings only; Baidu object rows are never returned for persistence."""
    del account_info, keywords, creatives
    region = field_consensus(campaigns, "regionTarget", [], unordered_list=True)
    geo_location = field_consensus(campaigns, "geoLocationStatus", 1)
    phrase_negative = field_consensus(campaigns, "negativeWords", [], unordered_list=True)
    exact_negative = field_consensus(campaigns, "exactNegativeWords", [], unordered_list=True)
    unit_bid = field_consensus(adgroups, "maxPrice", None)
    campaign_defaults = {
        field: field_consensus(campaigns, field, default, unordered_list=unordered)
        for field, default, unordered in (
            ("pause", False, False),
            ("schedule", [], False),
            ("equipmentType", 2, False),
            ("marketingTargetId", 7, False),
            ("businessPointId", None, False),
            ("businessPointName", None, False),
            ("campaignBidType", None, False),
            ("campaignBid", None, False),
            ("campaignOcpcBidType", None, False),
            ("campaignOcpcBid", None, False),
            ("campaignCvSources", [], True),
            ("campaignTransTypes", [], True),
            ("transAsset", None, False),
            ("transAssetId", None, False),
        )
    }
    template_data = {
        "hierarchy_schema": {
            "root": "ocpc_project",
            "edges": [
                {"parent": "ocpc_project", "child": "campaign", "relation": "one_to_many"},
                {"parent": "campaign", "child": "adgroup", "relation": "one_to_many"},
                {"parent": "adgroup", "child": "keyword", "relation": "one_to_many"},
                {"parent": "adgroup", "child": "creative", "relation": "one_to_many"},
            ],
            "note": "仅保存层级定义，不保存参考账户的项目、计划、单元、关键词或创意对象",
        },
        "account_region": {
            "source": "campaign_consensus",
            "region_target": region["value"],
            "geo_location_status": geo_location["value"],
            "consistency": {"region": region, "geo_location": geo_location},
        },
        "campaign": {
            "negative_words": phrase_negative["value"],
            "exact_negative_words": exact_negative["value"],
            "defaults": campaign_defaults,
            "consistency": {"negative_words": phrase_negative, "exact_negative_words": exact_negative},
        },
        "adgroup": {"max_price": unit_bid["value"], "consistency": {"max_price": unit_bid}},
        "ocpc_projects": _ocpc_template(projects),
        "audiences": _audience_template(crowds, bindings),
    }

    issues: list[dict] = []
    for label, value in (
        ("计划推广地域", region),
        ("推广地域地理位置选项", geo_location),
        ("短语否定词", phrase_negative),
        ("精确否定词", exact_negative),
        ("单元出价", unit_bid),
    ):
        if not value["consistent"]:
            issues.append({
                "severity": "warning",
                "code": "template_variants",
                "title": f"{label}存在多个版本",
                "detail": f"{value['variant_count']} 个变体，不能无条件当作单一模板",
            })
    if not campaigns:
        issues.append({"severity": "error", "code": "no_campaigns", "title": "参考账户没有可读取计划", "detail": "无法生成设置模板"})
    non_mobile = [row.get("campaignId") for row in campaigns if row.get("equipmentType") != 2]
    if non_mobile:
        issues.append({"severity": "warning", "code": "non_mobile_campaign", "title": "存在非移动设备计划", "detail": f"{len(non_mobile)} 个计划不是移动设备"})
    if not projects:
        issues.append({"severity": "warning", "code": "no_ocpc_project", "title": "未读取到oCPC项目设置", "detail": "oCPC模板为空"})
    if not crowds and not bindings:
        issues.append({"severity": "warning", "code": "no_audience", "title": "未读取到人群设置", "detail": "人群模板为空"})

    source_summary = {
        "settings_source_projects": len(projects),
        "settings_source_campaigns": len(campaigns),
        "settings_source_adgroups": len(adgroups),
        "settings_source_audiences": len(crowds),
        "settings_source_audience_bindings": len(bindings),
        "persisted_baidu_objects": 0,
    }
    analysis = {
        "status": "needs_review" if issues else "matched",
        "issue_count": len(issues),
        "issues": issues,
        "checks": {
            "campaign_region_consistent": region["consistent"],
            "negative_words_consistent": phrase_negative["consistent"],
            "exact_negative_words_consistent": exact_negative["consistent"],
            "all_campaigns_mobile": not non_mobile,
            "adgroup_bid_consistent": unit_bid["consistent"],
            "adgroup_bid_value": unit_bid["value"],
            "persisted_baidu_objects": 0,
        },
    }
    return template_data, source_summary, analysis
