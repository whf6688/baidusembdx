from decimal import Decimal
import unittest

from search_console.account_lifecycle import (
    elimination_reason,
    resolve_lifecycle,
    subject_accounts_are_all_eliminated,
)


class AccountLifecycleTest(unittest.TestCase):
    def test_refund_due_requires_every_subject_account_to_be_eliminated(self):
        cases = [
            (["已淘汰"], True),
            (["已淘汰", "已淘汰"], True),
            ([], False),
            (["已淘汰", "测试期"], False),
            (["已淘汰", "应退款"], False),
            (["已淘汰", None], False),
        ]
        for stages, expected in cases:
            with self.subTest(stages=stages):
                self.assertIs(subject_accounts_are_all_eliminated(stages), expected)

    def test_manual_returned_status_overrides_automatic_result(self):
        self.assertEqual(resolve_lifecycle("测试期", "退户"), "退户")

    def test_cleared_override_restores_automatic_result(self):
        self.assertEqual(resolve_lifecycle("应退款", None), "应退款")

    def test_invalid_override_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_lifecycle("空账户", "未知状态")

    def test_automatic_elimination_rules_are_strict(self):
        cases = [
            ("100.00", 0, None),
            ("100.01", 0, "累计消费大于100元且无加粉"),
            ("120.00", 1, None),
            ("120.01", 1, "累计加粉成本大于120元"),
            ("240.00", 2, None),
            ("240.01", 2, "累计加粉成本大于120元"),
        ]
        for spend, adds, expected in cases:
            with self.subTest(spend=spend, adds=adds):
                self.assertEqual(elimination_reason(Decimal(spend), adds), expected)
