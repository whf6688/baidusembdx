from search_console.reference_templates import analyze_reference_snapshot, field_consensus


def test_field_consensus_keeps_actual_value_and_variants():
    result = field_consensus([{"region": [1, 2]}, {"region": [1, 2]}], "region", [])
    assert result["value"] == [1, 2]
    assert result["consistent"] is True
    assert result["variant_count"] == 1


def test_field_consensus_can_ignore_list_order():
    result = field_consensus(
        [{"negativeWords": ["b", "a"]}, {"negativeWords": ["a", "b"]}],
        "negativeWords",
        [],
        unordered_list=True,
    )
    assert result["value"] == ["a", "b"]
    assert result["consistent"] is True


def test_reference_snapshot_builds_hierarchy_and_template():
    template, counts, analysis = analyze_reference_snapshot(
        {"regionTarget": [1], "geoLocationStatus": 1},
        [{
            "campaignId": 10, "regionTarget": [2, 3], "geoLocationStatus": 1,
            "negativeWords": ["a"], "exactNegativeWords": ["b"], "equipmentType": 2,
        }],
        [{"adgroupId": 20, "campaignId": 10, "adgroupName": "A成本01", "maxPrice": 1.0}],
        [{"keywordId": 30, "adgroupId": 20, "matchType": 2, "phraseType": 1}],
        [{"creativeId": 40, "adgroupId": 20}],
        [{"targetPackageId": 50, "scope": [{"levelId": 10}]}],
        [{"crowdId": 60}],
        [{"bindId": 70}],
    )
    assert template["account_region"]["region_target"] == [2, 3]
    assert template["campaign"]["negative_words"] == ["a"]
    assert template["adgroup"]["max_price"] == 1.0
    assert template["hierarchy_schema"]["edges"][-1] == {
        "parent": "adgroup", "child": "creative", "relation": "one_to_many",
    }
    assert counts["persisted_baidu_objects"] == 0
    assert counts["settings_source_campaigns"] == 1
    assert analysis["status"] == "matched"


def test_reference_snapshot_reports_template_mismatches():
    _, _, analysis = analyze_reference_snapshot(
        {},
        [
            {"campaignId": 1, "regionTarget": [1], "negativeWords": [], "exactNegativeWords": [], "equipmentType": 1},
            {"campaignId": 2, "regionTarget": [2], "negativeWords": ["x"], "exactNegativeWords": [], "equipmentType": 2},
        ],
        [{"adgroupId": 3, "campaignId": 1, "maxPrice": 0.8}, {"adgroupId": 5, "campaignId": 2, "maxPrice": 1.0}],
        [{"keywordId": 4, "adgroupId": 3, "matchType": 1, "phraseType": 1}],
        [], [], [], [],
    )
    codes = {issue["code"] for issue in analysis["issues"]}
    assert "template_variants" in codes
    assert "non_mobile_campaign" in codes
    assert any("单元出价" in issue["title"] for issue in analysis["issues"])
    assert "no_ocpc_project" in codes
