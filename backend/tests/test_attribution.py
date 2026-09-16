from search_console.attribution import AttributionCandidate, attribute_uniquely, extract_tracking_keys


def test_extracts_baidu_tracking_keys():
    assert extract_tracking_keys("https://a.test/?userid=12&keywordid=99") == ("12", "99")


def test_ambiguous_url_is_not_guessed():
    candidates = [
        AttributionCandidate(1, None, None, "https://a.test/landing"),
        AttributionCandidate(2, None, None, "https://a.test/landing"),
    ]
    assert attribute_uniquely("https://a.test/landing", candidates) is None


def test_exact_keys_win():
    candidate = AttributionCandidate(1, "12", "99", "https://a.test/landing")
    assert attribute_uniquely("https://a.test/landing?userid=12&keywordid=99", [candidate]) == candidate

