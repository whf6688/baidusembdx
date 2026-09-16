from search_console.worker import _campaigns_requiring_pause


def test_elimination_policy_pauses_only_active_campaigns_without_deleting_them():
    rows = [
        {"campaignId": 30, "pause": False},
        {"campaignId": 10, "pause": True},
        {"campaignId": 20, "pause": None},
        {"campaignId": 30, "pause": False},
        {"campaignName": "缺少ID"},
    ]

    assert _campaigns_requiring_pause(rows) == [20, 30]
