from collections import Counter

import pytest

from search_console.keyword_planner import KeywordPlanConfig, KeywordPlanError, TieredKeyword, build_keyword_plan
from search_console.models import KeywordTier


def keyword(text, tier):
    return TieredKeyword(text=text, tier=KeywordTier(tier))


def sample_keywords():
    return [
        keyword("A词1", "A"), keyword("A词2", "A"),
        keyword("B词1", "B"), keyword("C词1", "C"),
        keyword("D词1", "D"), keyword("D词2", "D"),
        keyword("E词1", "E"), keyword("F词1", "F"),
    ]


def test_a_is_replicated_to_five_identical_units_in_every_account():
    plan = build_keyword_plan([101, 102, 103], "减肥", sample_keywords())
    for account in plan["accounts"]:
        a_units = [unit for unit in account["units"] if unit["tiers"] == ["A"]]
        assert len(a_units) == 5
        assert all(unit["keywords"] == ["A词1", "A词2"] for unit in a_units)
        assert len({tuple(unit["keywords"]) for unit in a_units}) == 1
        assert all(len(unit["keywords"]) == len(set(unit["keywords"])) for unit in a_units)
        assert len({unit["name"] for unit in a_units}) == 5


def test_b_and_c_each_have_one_unit_in_every_account():
    plan = build_keyword_plan([101, 102], "减肥", sample_keywords())
    for account in plan["accounts"]:
        assert len([unit for unit in account["units"] if unit["tiers"] == ["B"]]) == 1
        assert len([unit for unit in account["units"] if unit["tiers"] == ["C"]]) == 1


def test_def_tiers_are_equal_weight_and_each_word_has_one_assignment():
    words = [keyword("A词", "A"), keyword("B词1", "B"), keyword("B词2", "B"), keyword("C词1", "C"), keyword("C词2", "C")]
    words += [keyword(f"D词{i}", "D") for i in range(1, 4)]
    words += [keyword(f"E词{i}", "E") for i in range(1, 3)]
    words += [keyword("F词1", "F")]
    plan = build_keyword_plan([101], "减肥", words)
    assert plan["batch"]["def_target_per_account"] == 6
    assert plan["batch"]["allocation_mode"] == "stable_random"
    assert plan["batch"]["selected_counts"] == {"D": 3, "E": 2, "F": 1}


def test_each_account_is_near_sixty_forty_when_enough_def_words_exist():
    words = [keyword("A词", "A"), keyword("B词", "B"), keyword("C词", "C")]
    words += [keyword(f"D词{i}", "D") for i in range(1, 9)]
    words += [keyword(f"E词{i}", "E") for i in range(1, 6)]
    words += [keyword(f"F词{i}", "F") for i in range(1, 3)]
    plan = build_keyword_plan([101, 102, 103], "减肥", words)
    for account in plan["accounts"]:
        assert account["abc_keyword_instances"] == 7
        assert account["def_keyword_instances"] == 4
        assert account["abc_percent"] == 63.64
        assert account["def_percent"] == 36.36


def test_def_words_are_partitioned_across_batches_without_repeating():
    words = [keyword("A词", "A"), keyword("B词", "B"), keyword("C词", "C")]
    words += [keyword(f"D词{i}", "D") for i in range(1, 13)]
    words += [keyword(f"E词{i}", "E") for i in range(1, 8)]
    words += [keyword(f"F词{i}", "F") for i in range(1, 5)]
    first = build_keyword_plan([101, 102], "减肥", words)
    seen = Counter()
    batches = []
    for batch_number in range(1, first["batch"]["total"] + 1):
        plan = build_keyword_plan(
            [101, 102], "减肥", words, KeywordPlanConfig(batch_number=batch_number)
        )
        batches.append(plan)
        def_loads = []
        for account in plan["accounts"]:
            supplemental = [
                text
                for unit in account["units"]
                if "DEF" in unit["name"]
                for text in unit["keywords"]
            ]
            assert len(supplemental) == len(set(supplemental))
            seen.update(supplemental)
            def_loads.append(account["def_keyword_instances"])
            if batch_number > 1:
                assert all("_A_" not in unit["name"] for unit in account["units"])
                assert all("_B_" not in unit["name"] for unit in account["units"])
                assert all("_C_" not in unit["name"] for unit in account["units"])
        assert max(def_loads) <= plan["batch"]["def_target_per_account"]
    assert sum(batch["batch"]["selected"] for batch in batches) == 23
    assert batches[-1]["batch"]["remaining"] == 0
    assert len(seen) == 23
    assert set(seen.values()) == {1}


def test_batch_out_of_range_is_blocked():
    with pytest.raises(KeywordPlanError, match="当前共 1 批"):
        build_keyword_plan(
            [101], "减肥", sample_keywords(), KeywordPlanConfig(batch_number=2)
        )


def test_missing_abc_blocks_plan():
    with pytest.raises(KeywordPlanError, match="缺少基础分级关键词"):
        build_keyword_plan([101], "减肥", [keyword("D词", "D")])


def test_random_distribution_is_stable_for_same_input():
    words = [keyword("A词", "A"), keyword("B词", "B"), keyword("C词", "C")]
    words += [keyword(f"D词{i}", "D") for i in range(1, 20)]
    words += [keyword(f"E词{i}", "E") for i in range(1, 20)]
    words += [keyword(f"F词{i}", "F") for i in range(1, 20)]
    first = build_keyword_plan([101, 102, 103, 104], "减肥", words)
    repeated = build_keyword_plan([101, 102, 103, 104], "减肥", words)
    changed_campaign = build_keyword_plan([101, 102, 103, 104], "减肥二", words)
    assert first == repeated
    assert first["accounts"] != changed_campaign["accounts"]


def test_def_input_order_does_not_change_random_distribution():
    base = [keyword("A词", "A"), keyword("B词", "B"), keyword("C词", "C")]
    supplements = [keyword(f"{tier}词{i}", tier) for tier in "DEF" for i in range(1, 8)]
    first = build_keyword_plan([101, 102, 103], "减肥", base + supplements)
    reordered = build_keyword_plan([101, 102, 103], "减肥", base + list(reversed(supplements)))
    assert first == reordered


def test_partial_random_batch_is_balanced_across_accounts():
    words = [keyword("A词", "A"), keyword("B词", "B"), keyword("C词", "C")]
    words += [keyword(f"D词{i}", "D") for i in range(1, 6)]
    plan = build_keyword_plan([101, 102, 103, 104], "减肥", words)
    loads = [account["def_keyword_instances"] for account in plan["accounts"]]
    assert max(loads) - min(loads) <= 1
    assert sum(loads) == 5


def test_same_keyword_cannot_belong_to_two_tiers():
    words = [keyword("A词", "A"), keyword("B词", "B"), keyword("C词", "C"), keyword("重复词", "D"), keyword("重复词", "E")]
    with pytest.raises(KeywordPlanError, match="同时属于 D 和 E"):
        build_keyword_plan([101], "减肥", words)


def test_account_order_does_not_change_distribution():
    first = build_keyword_plan([103, 101, 102], "减肥", sample_keywords())
    second = build_keyword_plan([102, 103, 101], "减肥", sample_keywords())
    assert first["accounts"] == second["accounts"]


def test_base_tier_over_capacity_is_blocked():
    words = [keyword("A1", "A"), keyword("A2", "A"), keyword("B1", "B"), keyword("C1", "C")]
    with pytest.raises(KeywordPlanError, match="超过单个单元"):
        build_keyword_plan([101], "减肥", words, KeywordPlanConfig(unit_capacity=1))
