"""码表条目格式工具的单元测试：旧格式迁移、JSON 解析与回退阻断口径。

运行：.venv/bin/python -m unittest tests.test_code_table_format -v
"""
from __future__ import annotations

import unittest

from app.services.code_table_format import (
    JSON_FORMAT,
    LEGACY_FORMAT,
    entries_to_json_text,
    entries_to_legacy_text,
    has_special_chars,
    parse_json_entries,
    parse_legacy_text,
)


class LegacyParseTests(unittest.TestCase):
    def test_unambiguous_entries_convert(self):
        result = parse_legacy_text("CN=中国,US=美国,JP=日本")
        self.assertEqual(result.entries, [
            {"code": "CN", "value": "中国"},
            {"code": "US", "value": "美国"},
            {"code": "JP", "value": "日本"},
        ])
        self.assertEqual(result.rejected, [])

    def test_value_with_equals_is_rejected_not_silently_split(self):
        # A=B=C：等号可能属于业务值，无法判明边界 -> 拒收并保留原文
        result = parse_legacy_text("A=B=C")
        self.assertEqual(result.entries, [])
        self.assertEqual(len(result.rejected), 1)
        self.assertEqual(result.rejected[0].raw, "A=B=C")
        self.assertIn("多个等号", result.rejected[0].reason)

    def test_missing_equals_empty_and_duplicate_lines(self):
        result = parse_legacy_text("1=启用,坏行,9=,=空码,1=重复")
        codes = [e["code"] for e in result.entries]
        self.assertEqual(codes, ["1"])  # 只有第一个无歧义好行
        raws = [r.raw for r in result.rejected]
        self.assertIn("坏行", raws)
        self.assertIn("9=", raws)
        self.assertIn("=空码", raws)
        self.assertIn("1=重复", raws)
        # 坏行原文与原因都可单独追溯
        for line in result.rejected:
            self.assertTrue(line.raw)
            self.assertTrue(line.reason)
            self.assertIsInstance(line.index, int)

    def test_blank_chunks_ignored(self):
        result = parse_legacy_text("CN=中国, ,US=美国,")
        self.assertEqual([e["code"] for e in result.entries], ["CN", "US"])
        self.assertEqual(result.rejected, [])

    def test_whitespace_trimmed_like_legacy_behavior(self):
        result = parse_legacy_text(" CN = 中国 , US=美国")
        self.assertEqual(result.entries[0], {"code": "CN", "value": "中国"})


class JsonParseTests(unittest.TestCase):
    def test_array_format_with_special_chars(self):
        text = '[{"code":"A=B","value":"X=Y*2"},{"code":"K,M","value":"带逗号"}]'
        entries, error = parse_json_entries(text)
        self.assertIsNone(error)
        self.assertEqual(entries, [
            {"code": "A=B", "value": "X=Y*2"},
            {"code": "K,M", "value": "带逗号"},
        ])

    def test_object_format(self):
        entries, error = parse_json_entries('{"A=B":"完整值","CN":"中国"}')
        self.assertIsNone(error)
        self.assertEqual(len(entries), 2)
        mapping = {e["code"]: e["value"] for e in entries}
        self.assertEqual(mapping["A=B"], "完整值")

    def test_invalid_json_returns_error(self):
        entries, error = parse_json_entries("[{bad")
        self.assertIsNone(entries)
        self.assertIn("无法解析", error)

    def test_duplicate_code_rejected(self):
        entries, error = parse_json_entries('[{"code":"X","value":"1"},{"code":"X","value":"2"}]')
        self.assertIsNone(entries)
        self.assertIn("重复码", error)


class LegacyRoundTripTests(unittest.TestCase):
    def test_simple_entries_round_trip(self):
        entries = [{"code": "CN", "value": "中国"}, {"code": "US", "value": "美国"}]
        text, incompatible = entries_to_legacy_text(entries)
        self.assertEqual(text, "CN=中国,US=美国")
        self.assertEqual(incompatible, [])
        self.assertFalse(has_special_chars(entries))

    def test_special_chars_block_legacy_conversion_without_dropping(self):
        entries = [
            {"code": "PLAIN", "value": "普通值"},
            {"code": "A=B", "value": "X=Y*2"},
        ]
        text, incompatible = entries_to_legacy_text(entries)
        self.assertIsNone(text)  # 整体阻断，不做半转换
        self.assertEqual(incompatible, [{"code": "A=B", "value": "X=Y*2"}])
        self.assertTrue(has_special_chars(entries))

    def test_json_serialization_keeps_unicode(self):
        text = entries_to_json_text([{"code": "CN", "value": "中国"}])
        self.assertIn("中国", text)
        self.assertIn('"code"', text)
        self.assertIn('"value"', text)
        # 常量口径稳定
        self.assertEqual(JSON_FORMAT, "json_entries")
        self.assertEqual(LEGACY_FORMAT, "legacy_csv")


if __name__ == "__main__":
    unittest.main()
