from types import SimpleNamespace

import pytest

from search_console.ad_build_executor import _project_negative_keywords
from search_console.negative_keywords import (
    normalized_negative_keyword,
    reference_template_negative_keywords,
)


def test_reference_template_negative_keywords_splits_and_deduplicates():
    snapshot = reference_template_negative_keywords({
        "campaign": {
            "negative_words": [" 减肥药 ", "減肥", "减肥药"],
            "exact_negative_words": ["免费", "ＦＲＥＥ", "FREE"],
        }
    })

    assert snapshot == {
        "phrase": ["减肥药", "減肥"],
        "exact": ["免费", "FREE"],
    }
    assert normalized_negative_keyword(" ＦＲＥＥ ") == "free"


def test_ad_build_negative_keywords_only_accept_project_postgresql_snapshot():
    legacy_operation = SimpleNamespace(payload={
        "reference_template": {
            "campaign": {"negative_words": ["旧模板否词"]}
        }
    })

    with pytest.raises(ValueError, match="项目数据库否词快照"):
        _project_negative_keywords(legacy_operation, 1)

    operation = SimpleNamespace(payload={
        "negative_keyword_source": "project_postgresql",
        "project_negative_keywords": {
            "phrase": ["短语一"],
            "exact": ["精确一"],
        },
    })
    assert _project_negative_keywords(operation, 1) == (["短语一"], ["精确一"])


def test_negative_keyword_limits_follow_baidu_user_level():
    operation = SimpleNamespace(payload={
        "negative_keyword_source": "project_postgresql",
        "project_negative_keywords": {
            "phrase": [f"短语{index}" for index in range(201)],
            "exact": [],
        },
    })

    with pytest.raises(ValueError, match="最多允许200个短语否词"):
        _project_negative_keywords(operation, 4)
    assert len(_project_negative_keywords(operation, 1)[0]) == 201