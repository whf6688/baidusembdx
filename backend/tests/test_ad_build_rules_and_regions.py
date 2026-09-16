from types import SimpleNamespace

from search_console.ad_build_executor import _operation_build_rules
from search_console.ad_build_rules import AD_BUILD_RULE_VERSION, current_ad_build_rules
from search_console.regions import (
    MIGRATED_DEFAULT_REGION_TARGET,
    baidu_region_catalog,
    baidu_region_ids,
    default_ad_build_region_preference,
)
from search_console.schemas import AdBuildPreviewRequest


def test_system_build_rules_are_versioned_and_return_isolated_snapshots():
    first = current_ad_build_rules()
    second = current_ad_build_rules()

    assert first["version"] == AD_BUILD_RULE_VERSION
    assert first["campaign"]["marketing_target_id"] == 7
    assert first["ocpc"]["data_flow_data"] == [{"dataFlow": 1000, "transType": [79]}]
    assert first["audiences"]["definitions"]

    first["campaign"]["marketing_target_id"] = -1
    assert second["campaign"]["marketing_target_id"] == 7


def test_executor_uses_frozen_operation_rules_and_system_fallback():
    frozen = {"version": "frozen-v1", "campaign": {"marketing_target_id": 9}}
    assert _operation_build_rules(SimpleNamespace(payload={"build_rules": frozen})) is frozen
    assert _operation_build_rules(SimpleNamespace(payload={}))["version"] == AD_BUILD_RULE_VERSION


def test_region_catalog_contains_only_country_province_and_city_ids():
    catalog = baidu_region_catalog()
    assert catalog["version"] == "baidu-province-city-codes-14.3-v1"
    assert catalog["country"] == {"id": 9999999, "name": "中国"}
    assert all(node["level"] == "province" for node in catalog["regions"])
    assert all(
        child["level"] == "city" and "children" not in child
        for node in catalog["regions"]
        for child in node.get("children", [])
    )
    assert set(MIGRATED_DEFAULT_REGION_TARGET).issubset(baidu_region_ids())


def test_migrated_region_default_is_used_by_new_preview_requests():
    request = AdBuildPreviewRequest(
        project_id="e0bdd938-3e3a-47bd-ab92-7e319b3d9291",
        selection_mode="random",
        quantity=1,
    )
    preference = default_ad_build_region_preference()

    assert request.region_target == MIGRATED_DEFAULT_REGION_TARGET
    assert preference["region_target"] == MIGRATED_DEFAULT_REGION_TARGET
    assert preference["geo_location_status"] == 1
