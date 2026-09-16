from search_console.ad_build_executor import _repeat_material_units
from search_console.ad_build_settings import (
    default_plan_repeat_count,
    repeat_count_for_plan,
)


def test_default_plan_repeat_counts_keep_existing_behavior():
    assert default_plan_repeat_count("A成本") == 5
    assert default_plan_repeat_count("B机会") == 1
    assert repeat_count_for_plan({}, "A成本") == 5


def test_material_units_are_repeated_once_from_base_units():
    base_units = [
        {
            "campaign_name": "A成本",
            "name": "A成本_01",
            "keywords": ["词一", "词二"],
        },
        {
            "campaign_name": "B机会",
            "name": "B机会_01",
            "keywords": ["词三"],
        },
    ]

    result = _repeat_material_units(
        base_units,
        {"A成本": 2, "B机会": 3},
    )

    assert [item["name"] for item in result] == [
        "A成本_01",
        "A成本_02",
        "B机会_01",
        "B机会_02",
        "B机会_03",
    ]
    assert [item["keywords"] for item in result[:2]] == [
        ["词一", "词二"],
        ["词一", "词二"],
    ]
