from search_console.config import Settings
from search_console.oauth import (
    fetch_all_authorized_accounts,
    merge_authorized_accounts,
    normalize_mcc_service_accounts,
    oauth_signature,
    verify_callback_signature,
)


def test_oauth_signature_matches_baidu_aes_cbc_format() -> None:
    params = {
        "appId": "app123",
        "authCode": "code456",
        "state": "state789",
        "timestamp": "1611216626171",
        "userId": "1234",
    }
    expected = (
        "E96D35180111A0316D7B1A7502B4DEDEC3937E49BA618FE8FF3C432FB3D57E9A"
        "3389A2ABF35C3F304E5DD9BC4953C8D19609CE814E22E858E7D3D3D638A11E639"
        "9824BA03DD9ABEF95BD4F906AF763E0643C8FF9DDB8AE49D5721BEF6E6407E8D60"
        "09D054480371414BC11DD381CFE469E1163BC2EC369D3A80F1A1C0E76C492C03241"
        "A28895B2735EBF9E89DA631FA4"
    )
    assert oauth_signature("0123456789abcdef0123456789abcdef", params) == expected
    assert verify_callback_signature(
        "0123456789abcdef0123456789abcdef", params, expected.lower()
    )


def test_platform_database_is_always_project_database() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://search@postgres/search",
        platform_database_url="postgresql+psycopg://ecom@forbidden/ecom",
    )
    assert settings.effective_platform_database_url == settings.database_url


def test_fetch_all_authorized_accounts_follows_baidu_cursor(monkeypatch) -> None:
    calls: list[int] = []
    pages = [
        {
            "masterName": "manager-a",
            "userAcctType": 2,
            "hasNext": True,
            "subUserList": [{"ucId": 11, "ucName": "account-11"}],
        },
        {
            "hasNext": False,
            "subUserList": [
                {"ucId": 11, "ucName": "account-11-new"},
                {"ucId": 18, "ucName": "account-18"},
            ],
        },
    ]

    def fake_post(_: str, payload: dict) -> dict:
        calls.append(payload["lastPageMaxUcId"])
        return pages[len(calls) - 1]

    monkeypatch.setattr("search_console.oauth.post_oauth_json", fake_post)
    result = fetch_all_authorized_accounts(
        Settings(), open_id="open", access_token="token", user_id=9
    )

    assert calls == [1, 11]
    assert result["masterName"] == "manager-a"
    assert result["subUserList"] == [
        {"ucId": 11, "ucName": "account-11-new"},
        {"ucId": 18, "ucName": "account-18"},
    ]


def test_dedicated_mcc_list_fills_account_missing_from_oauth_user_info() -> None:
    mcc_accounts = normalize_mcc_service_accounts(
        {
            "data": [
                {"userid": 11, "username": "account-11"},
                {"userid": 87216403, "username": "baidu-QX芭瀚Fx03"},
            ]
        }
    )
    merged = merge_authorized_accounts(
        [{"ucId": 11, "ucName": "account-11-old"}],
        mcc_accounts,
    )

    assert merged == [
        {"ucId": 11, "ucName": "account-11"},
        {"ucId": 87216403, "ucName": "baidu-QX芭瀚Fx03"},
    ]
