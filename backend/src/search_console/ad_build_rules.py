"""Versioned, system-owned settings used by the search ad build workflow.

These values were validated from the original reference-account snapshot and
are now owned by this application.  Runtime ad builds must never read another
Baidu account to obtain settings.
"""

from copy import deepcopy


AD_BUILD_RULE_VERSION = "weight-loss-system-rules-v1"


_CURRENT_RULES = {
    "version": AD_BUILD_RULE_VERSION,
    "campaign": {
        "pause": False,
        "schedule": [],
        "marketing_target_id": 7,
        "equipment_type": 2,
        "business_point_id": 200205001,
        "campaign_bid_type": 1,
        "campaign_ocpc_bid_type": 1,
        "campaign_ocpc_bid": 0.5,
        "campaign_trans_types": [79],
        "campaign_cv_sources": [1000],
        "trans_asset": 0,
        "trans_asset_id": -1,
    },
    "adgroup": {
        "max_price": 1.0,
        "pause": False,
        "auto_targeting": False,
    },
    "ocpc": {
        "ocpc_bid_type": 1,
        "data_flow_data": [{"dataFlow": 1000, "transType": [79]}],
        "deep_trans_type_mode": 1,
        "trans_asset": 0,
        "trans_asset_id": -1,
        "marketing_target_id": 7,
    },
    "audiences": {
        "definitions": [
            {
                "name": "女25-64限定86",
                "age": [4, 8, 32, 128],
                "custom_age": [],
                "sex": 2,
                "in_people": [],
                "id_pack": [],
                "direct_type": 0,
                "effect_type": 2,
            }
        ],
        "binding": {
            "target_type": 1,
            "price_ratio": 1.0,
        },
    },
}


def current_ad_build_rules() -> dict:
    """Return an isolated snapshot suitable for persisting with one job."""

    return deepcopy(_CURRENT_RULES)


def ad_build_rule_summary() -> dict:
    rules = _CURRENT_RULES
    return {
        "version": AD_BUILD_RULE_VERSION,
        "source": "system_versioned_rules",
        "audience_count": len(rules["audiences"]["definitions"]),
        "campaign_equipment_type": rules["campaign"]["equipment_type"],
        "ocpc_conversion_types": rules["ocpc"]["data_flow_data"][0]["transType"],
    }
