"""码表版本化全链路 E2E：通过 HTTP 接口复现“登记→发布→回滚→领用冲突”叙事。

前置：后端已在 127.0.0.1:8021 启动（./run.sh）。
运行：.venv/bin/python -m unittest tests.test_code_table_e2e -v
"""
from __future__ import annotations

import json
import unittest
import urllib.error
import urllib.request
from uuid import uuid4

BASE = "http://127.0.0.1:8021/api/code-tables"


def call(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as exc:  # pragma: no cover - 仅在服务未启动时触发
        raise AssertionError(f"后端未启动或接口不可达：{exc}") from exc


class CodeTableE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.suffix = uuid4().hex[:8]
        cls.special_code = f"REF-E2E-SP-{cls.suffix}"
        cls.legacy_code = f"REF-E2E-LG-{cls.suffix}"
        # 保证从新版运行时开始
        call("POST", "/runtime/switch", {"mode": "new_runtime", "reason": "e2e 初始化"})

    def test_01_seed_history_recompute_cn(self):
        """历史有效码表用原编号追溯，旧批次复算仍得到 CN -> 中国。"""
        result = call("POST", "/recompute/BATCH-20260901-01")
        self.assertTrue(result["ok"])
        self.assertEqual(result["version_no"], "v1")
        self.assertTrue(result["all_consistent"])
        self.assertEqual(result["reruns"][0]["raw"], "CN")
        self.assertEqual(result["reruns"][0]["recomputed"], "中国")

    def test_02_legacy_migration_good_and_bad_lines(self):
        """旧格式无歧义好行继续转换，坏行保留原文与原因。"""
        legacy = "1=启用,0=停用,A=B=C,坏行,2=待审核"
        result = call("POST", "/register", {
            "dataset_code": self.legacy_code,
            "dataset_name": "E2E迁移码表",
            "entry_format": "legacy_csv",
            "entry_text": legacy,
        })
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["dataset"]["entry_count"], 3)
        raws = {r["raw"] for r in result["dataset"]["migration_report"]["rejected"]}
        self.assertIn("A=B=C", raws)
        self.assertIn("坏行", raws)
        published = call("POST", "/publish", {"dataset_code": self.legacy_code})
        self.assertTrue(published["ok"])
        self.assertEqual(published["version"]["version_no"], "v1")
        rejections = call("GET", f"/versions/{self.legacy_code}/v1/rejections")
        self.assertEqual(rejections["converted"], 3)
        self.assertEqual(len(rejections["rejected"]), 2)

    def test_03_special_json_publish_claim_normalize(self):
        """含 A=B 的新 JSON 码表发布后，新版运行时可领取并完整归一化。"""
        entries = [
            {"code": "PLAIN", "value": "普通值"},
            {"code": "A=B", "value": "X=Y*2"},
        ]
        reg = call("POST", "/register", {
            "dataset_code": self.special_code,
            "dataset_name": "E2E特殊字符码表",
            "entry_format": "json_entries",
            "entry_text": json.dumps(entries, ensure_ascii=False),
        })
        self.assertTrue(reg["ok"])
        pub = call("POST", "/publish", {"dataset_code": self.special_code})
        self.assertTrue(pub["ok"])
        self.assertFalse(pub["version"]["legacy_compatible"])

        batch = f"BATCH-E2E-{self.suffix}"
        claim = call("POST", "/claim", {
            "dataset_code": self.special_code, "batch_no": batch})
        self.assertTrue(claim["ok"])
        self.assertEqual(claim["entry_format"], "json_entries")
        norm = call("POST", "/normalize", {"batch_no": batch, "raw_value": "A=B"})
        self.assertTrue(norm["ok"])
        self.assertEqual(norm["normalized"], "X=Y*2")  # 完整结果，未被等号切分

    def test_04_rollback_runtime_blocks_special_claim(self):
        """旧版应用回滚后，特殊字符版本领取被明确阻断，不静默丢值。"""
        switched = call("POST", "/runtime/switch", {
            "mode": "legacy_runtime", "reason": "E2E 模拟回滚"})
        self.assertEqual(switched["runtime_mode"], "legacy_runtime")
        blocked = call("POST", "/claim", {
            "dataset_code": self.special_code,
            "batch_no": f"BATCH-E2E-BLOCK-{self.suffix}",
        })
        self.assertFalse(blocked["ok"])
        self.assertTrue(blocked["blocked"])
        self.assertEqual(blocked["reason"], "legacy_incompatible_special_chars")
        self.assertEqual(blocked["blocked_version"], "v1")
        self.assertTrue(blocked["incompatible_entries"])

    def test_05_legacy_runtime_serves_compatible_version_as_legacy(self):
        """旧版运行时领取普通码表可降级旧结构，历史批次归一化口径不变。"""
        batch = f"BATCH-E2E-LEGACY-{self.suffix}"
        claim = call("POST", "/claim", {
            "dataset_code": "REF-COUNTRY", "batch_no": batch})
        self.assertTrue(claim["ok"], claim)
        self.assertEqual(claim["entry_format"], "legacy_csv")
        self.assertIn("CN=中国", claim["payload"])
        norm = call("POST", "/normalize", {"batch_no": batch, "raw_value": "CN"})
        self.assertEqual(norm["normalized"], "中国")

    def test_06_batch_locked_to_one_complete_version(self):
        """同一批次锁定同一完整版本，重复领取不拼装、不改版。"""
        batch = f"BATCH-E2E-LOCK-{self.suffix}"
        first = call("POST", "/claim", {
            "dataset_code": "REF-COUNTRY", "batch_no": batch})
        second = call("POST", "/claim", {
            "dataset_code": "REF-COUNTRY", "batch_no": batch})
        self.assertTrue(second["reused"])
        self.assertEqual(first["version_no"], second["version_no"])
        other = call("POST", "/claim", {
            "dataset_code": self.legacy_code, "batch_no": batch})
        self.assertTrue(other["blocked"])
        self.assertEqual(other["reason"], "batch_bound_to_other_dataset")

    def test_07_restore_new_runtime_and_version_rollback(self):
        """回切新版部署；码表版本回滚后新批次领到历史完整版次。"""
        call("POST", "/runtime/switch", {"mode": "new_runtime", "reason": "E2E 回切"})
        versions = call("GET", "/versions/REF-COUNTRY")
        active = [v for v in versions["items"] if v["status"] == "生效中"][0]
        historical = [v for v in versions["items"] if v["status"] != "生效中"][0]
        rb = call("POST", "/rollback", {
            "dataset_code": "REF-COUNTRY",
            "target_version": historical["version_no"],
            "reason": "E2E 版本回滚",
        })
        self.assertTrue(rb["ok"])
        batch = f"BATCH-E2E-RB-{self.suffix}"
        claim = call("POST", "/claim", {
            "dataset_code": "REF-COUNTRY", "batch_no": batch})
        self.assertEqual(claim["version_no"], historical["version_no"])
        self.assertNotEqual(claim["version_no"], active["version_no"])
        # 复位生效指针，避免影响其他测试的默认口径
        call("POST", "/rollback", {
            "dataset_code": "REF-COUNTRY",
            "target_version": active["version_no"],
            "reason": "E2E 复位",
        })


if __name__ == "__main__":
    unittest.main()
