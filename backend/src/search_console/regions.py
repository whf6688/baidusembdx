"""System-owned Baidu region catalog and migrated project defaults."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


AD_BUILD_REGION_PREFERENCE_KEY = "ad_build_region"
REGION_CATALOG_VERSION = "baidu-province-city-codes-14.3-v1"

# Migrated from the last active 86459649 reference snapshot.  It is now the
# initial project default and can be replaced through the region settings UI.
MIGRATED_DEFAULT_REGION_TARGET = [
    10000, 11000, 12000, 13305, 13306, 13307, 13325, 13326, 13327, 13329,
    13330, 13331, 13332, 14308, 14309, 14310, 14311, 14312, 14313, 14314,
    14315, 14316, 14317, 14318, 14319, 14320, 14321, 14323, 14324, 14476,
    15000, 16000, 17000, 18000, 19053, 19054, 19056, 19057, 19058, 19059,
    19060, 19061, 19062, 19063, 19064, 19065, 2000, 20000, 21000, 22000,
    23000, 24000, 25197, 25199, 25200, 25202, 25203, 25204, 25207, 25208,
    25218, 25219, 25220, 25222, 25223, 26205, 26206, 26209, 26210, 26211,
    26212, 26213, 26214, 26216, 26217, 27000, 28000, 29000, 3000, 30000,
    31000, 32000, 33000, 4082, 4083, 4085, 4086, 4088, 4089, 4090, 4091,
    4092, 4093, 4094, 4109, 4110, 4111, 4112, 4113, 4114, 4115, 4116,
    4117, 5000, 8000, 9000,
]


def default_ad_build_region_preference() -> dict:
    return {
        "region_target": list(MIGRATED_DEFAULT_REGION_TARGET),
        "geo_location_status": 1,
        "revision": 1,
        "catalog_version": REGION_CATALOG_VERSION,
    }


@lru_cache(maxsize=1)
def baidu_region_catalog() -> dict:
    path = Path(__file__).with_name("data") / "baidu_regions.json"
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def baidu_region_ids() -> frozenset[int]:
    catalog = baidu_region_catalog()
    values = {int(catalog["country"]["id"])}

    def collect(nodes: list[dict]) -> None:
        for node in nodes:
            values.add(int(node["id"]))
            collect(node.get("children") or [])

    collect(catalog["regions"])
    return frozenset(values)
