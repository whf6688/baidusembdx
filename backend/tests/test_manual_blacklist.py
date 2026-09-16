from search_console.schemas import ManualKeywordBlacklistCreate


def test_manual_blacklist_normalizes_empty_and_duplicate_keywords():
    payload = ManualKeywordBlacklistCreate(
        keywords=["  快速减肥  ", "", "快速减肥", "减肥药"],
        reason="  人工排除  ",
    )

    assert payload.keywords == ["快速减肥", "减肥药"]
    assert payload.reason == "人工排除"
