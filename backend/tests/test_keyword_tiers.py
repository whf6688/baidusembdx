from decimal import Decimal

from search_console.keyword_tiers import classify_keyword
from search_console.schemas import KeywordTierRuleConfig


RULES = KeywordTierRuleConfig()


def classify(spend, copies=0, adds=0, has_performance=True):
    return classify_keyword(
        has_performance=has_performance,
        spend=Decimal(str(spend)),
        copies=copies,
        adds=adds,
        rules=RULES,
    )


def test_unmeasured_keyword_stays_in_f_expansion():
    assert classify(0, has_performance=False) == "F拓展"


def test_excel_cost_rules_are_reproduced():
    assert classify(220, adds=2) == "A成本"
    assert classify(250, adds=2) == "B机会"
    assert classify(400, adds=3) == "C成本较高"
    assert classify(500, adds=2) == "成本高"


def test_spend_bands_do_not_split_d_or_e_by_copy_count():
    assert classify(70, copies=0) == "空耗"
    assert classify(69.99999999999999, copies=1) == "空耗"
    assert classify(10, copies=0) == "D消耗不足"
    assert classify(10, copies=1) == "D消耗不足"
    assert classify(0, copies=0) == "F拓展"
    assert classify(0, copies=1) == "F拓展"
    assert classify(0.01, copies=0) == "E消耗很小"
    assert classify(9.99, copies=1) == "E消耗很小"
