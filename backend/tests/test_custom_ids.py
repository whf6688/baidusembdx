import pytest
from pydantic import ValidationError

from search_console.schemas import HduofenCustomIdBatchCreate, HduofenCustomIdCreate


def test_custom_id_create_strips_fields():
    payload = HduofenCustomIdCreate(account="  baidu-账户01  ", custom_id="  yyl042401  ")

    assert payload.account == "baidu-账户01"
    assert payload.custom_id == "yyl042401"


@pytest.mark.parametrize("custom_id", ["has space", "bad?id", "bad&id", "bad#id", "bad=id"])
def test_custom_id_create_rejects_url_separators(custom_id: str):
    with pytest.raises(ValidationError):
        HduofenCustomIdCreate(account="baidu-账户01", custom_id=custom_id)


def test_custom_id_batch_accepts_multiple_mappings():
    payload = HduofenCustomIdBatchCreate(mappings=[
        {"account": "baidu-账户01", "custom_id": "yyl042401"},
        {"account": "83215446", "custom_id": "yyl042402"},
    ])

    assert len(payload.mappings) == 2
