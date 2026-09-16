from types import SimpleNamespace

from search_console.ad_build_executor import _build_material_plan


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDb:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self, _statement):
        return _ScalarRows(self._rows)

    def get(self, *_args):
        return None


def test_scheduled_execution_batch_two_still_builds_initial_abc_and_def_plan():
    materials = [
        SimpleNamespace(campaign_name="A成本", keyword_text="A关键词"),
        SimpleNamespace(campaign_name="B机会", keyword_text="B关键词"),
        SimpleNamespace(campaign_name="C成本较高", keyword_text="C关键词"),
        SimpleNamespace(campaign_name="D消耗不足", keyword_text="D关键词"),
        SimpleNamespace(campaign_name="E消耗很小", keyword_text="E关键词"),
        SimpleNamespace(campaign_name="F拓展", keyword_text="F关键词"),
    ]
    account = SimpleNamespace(project_id="project-id", baidu_account_id=87216801)
    operation = SimpleNamespace(
        payload={
            # 回归场景：过去该字段会把定时第 2 批误识别成 DEF 第 2 轮。
            "batch_number": 2,
            "execution_batch_number": 2,
            "keyword_batch_number": 1,
        }
    )

    plan, _ = _build_material_plan(_FakeDb(materials), account, operation)

    account_plan = plan["accounts"][0]
    campaign_names = {unit["campaign_name"] for unit in account_plan["units"]}
    assert plan["batch"]["number"] == 1
    assert plan["batch"]["mode"] == "initial"
    assert {"A成本", "B机会", "C成本较高"}.issubset(campaign_names)
    assert {"D消耗不足", "E消耗很小", "F拓展"}.issubset(campaign_names)


def test_ad_build_ignores_keyword_rotation_value_even_if_injected():
    materials = [
        SimpleNamespace(campaign_name="A成本", keyword_text="A关键词"),
        SimpleNamespace(campaign_name="B机会", keyword_text="B关键词"),
        SimpleNamespace(campaign_name="C成本较高", keyword_text="C关键词"),
        SimpleNamespace(campaign_name="D消耗不足", keyword_text="D关键词"),
    ]
    account = SimpleNamespace(project_id="project-id", baidu_account_id=87216801)
    operation = SimpleNamespace(payload={"keyword_batch_number": 3})

    plan, _ = _build_material_plan(_FakeDb(materials), account, operation)

    assert plan["batch"]["number"] == 1
    assert plan["batch"]["mode"] == "initial"


def test_full_mode_uses_every_keyword_once_and_splits_units_at_5000():
    materials = [
        SimpleNamespace(campaign_name="原始计划甲", keyword_text=f"关键词{i:04d}")
        for i in range(5001)
    ] + [SimpleNamespace(campaign_name="原始计划乙", keyword_text="另一个关键词")]
    account = SimpleNamespace(project_id="project-id", baidu_account_id=87216801)
    operation = SimpleNamespace(payload={"keyword_mode": "full"})

    plan, _ = _build_material_plan(_FakeDb(materials), account, operation)

    account_plan = plan["accounts"][0]
    assert plan["mode"] == "full"
    assert account_plan["unit_count"] == 3
    assert account_plan["operation_keyword_instances"] == 5002
    assert [unit["campaign_name"] for unit in account_plan["units"]] == ["原始计划甲", "原始计划甲", "原始计划乙"]
    assert [len(unit["keywords"]) for unit in account_plan["units"]] == [5000, 1, 1]
    assert len({keyword for unit in account_plan["units"] for keyword in unit["keywords"]}) == 5002
