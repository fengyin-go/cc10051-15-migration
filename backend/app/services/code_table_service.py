"""码表版本化领域服务：带版本号的 JSON 条目格式、发布快照、部署回滚与清洗领用。

领域规则与题面约束的对应关系：

* 登记支持新版 JSON 条目与旧版逗号/等号文本；旧文本经
  :mod:`code_table_format` 解析，无歧义好行进草稿，坏行进迁移报告
  （保留原文与原因，可单独排查），绝不静默丢值。
* 发布按数据集生成不可变的完整版本快照，版次按数据集独立递增；
  历史版本用原编号保留，旧批次凭领用记录始终能复算。
* 清洗端只能按码表编号领用服务端当前发布版次，领用时把整版快照
  复制进批次记录，发布交接/回滚期间不存在新旧条目拼装。
* 运行时模式模拟新版部署与旧版回滚：旧版应用无法承载含特殊字符
  （码或值含 ``=``/``,``）的 JSON 版本时，领用得到明确阻断回执，
  而不是丢值后的错误结果。
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from app.services.code_table_format import (
    JSON_FORMAT,
    LEGACY_FORMAT,
    entries_to_json_text,
    entries_to_legacy_text,
    entries_to_mapping,
    has_special_chars,
    parse_json_entries,
    parse_legacy_text,
)
from app.store import store

RUNTIME_NEW = "new_runtime"       # 新版部署：JSON 条目格式生效
RUNTIME_LEGACY = "legacy_runtime"  # 旧版应用回滚

REGISTRY_TABLE = "code_table_registry"
VERSION_TABLE = "code_table_version"
CLAIM_TABLE = "code_table_claim"
RUN_TABLE = "code_table_run"
SETTING_TABLE = "code_table_setting"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_id(table: str) -> int:
    return max((int(row.get("id", 0)) for row in store.rows(table)), default=0) + 1


class CodeTableService:
    """码表登记、版本发布、部署回滚与清洗领用的统一领域服务（进程内单例）。"""

    # ---- 运行时模式：模拟部署切换 / 旧版回滚 ----

    def get_runtime_mode(self) -> str:
        rows = store.rows(SETTING_TABLE)
        if not rows:
            rows.append({"id": 1, "runtime_mode": RUNTIME_NEW})
        return str(rows[0].get("runtime_mode", RUNTIME_NEW))

    def switch_runtime(self, mode: str, reason: str = "") -> dict[str, Any]:
        if mode not in (RUNTIME_NEW, RUNTIME_LEGACY):
            return {"ok": False, "message": f"未知运行时模式：{mode}"}
        rows = store.rows(SETTING_TABLE)
        if not rows:
            rows.append({"id": 1, "runtime_mode": mode})
        previous = self.get_runtime_mode()
        rows[0]["runtime_mode"] = mode
        rows[0]["updated_at"] = _now()
        return {
            "ok": True,
            "previous_mode": previous,
            "runtime_mode": mode,
            "reason": reason,
            "message": (
                "已回切旧版应用，仅可领用旧结构兼容版本"
                if mode == RUNTIME_LEGACY
                else "新版部署已生效，JSON 条目格式可正常领用"
            ),
        }

    # ---- 登记与迁移 ----

    def register_dataset(
        self,
        dataset_code: str,
        dataset_name: str,
        entry_format: str,
        entry_text: str,
    ) -> dict[str, Any]:
        """登记码表草稿。

        校验按“实际可发布版本”口径工作：JSON 草稿必须能解析成条目；
        旧版草稿允许带坏行登记，好行/坏行分别入草稿与迁移报告，
        发布时再按有效条目判定可发布性。
        """
        dataset_code = str(dataset_code or "").strip()
        dataset_name = str(dataset_name or "").strip()
        if not dataset_code or not dataset_name:
            return {"ok": False, "message": "数据集编码与名称不能为空"}
        if entry_format not in (JSON_FORMAT, LEGACY_FORMAT):
            return {"ok": False, "message": f"不支持的条目格式：{entry_format}"}
        if not str(entry_text or "").strip():
            return {"ok": False, "message": "码值条目不能为空"}

        if self._find_registry(dataset_code) is not None:
            return {"ok": False, "message": f"数据集 {dataset_code} 已登记，请在原草稿上修订或发布新版本"}

        if entry_format == JSON_FORMAT:
            entries, error = parse_json_entries(entry_text)
            if entries is None:
                return {"ok": False, "message": error or "JSON 条目无法解析"}
            migration_report = {
                "source_format": JSON_FORMAT,
                "converted": len(entries),
                "rejected": [],
            }
        else:
            parsed = parse_legacy_text(entry_text)
            entries = parsed.entries
            migration_report = {
                "source_format": LEGACY_FORMAT,
                "converted": len(entries),
                "rejected": [line.to_dict() for line in parsed.rejected],
            }

        row = {
            "id": _next_id(REGISTRY_TABLE),
            "数据集编码": dataset_code,
            "数据集名称": dataset_name,
            "entry_format": entry_format,
            "raw_text": str(entry_text),
            "draft_entries": entries,
            "migration_report": migration_report,
            "status": "草稿",
            "current_version": None,
            "created_at": _now(),
        }
        store.rows(REGISTRY_TABLE).append(row)
        return {
            "ok": True,
            "message": "码表草稿已登记",
            "dataset": self._registry_view(row),
        }

    def list_datasets(self) -> list[dict[str, Any]]:
        return [self._registry_view(row) for row in store.rows(REGISTRY_TABLE)]

    def list_versions(self, dataset_code: str) -> list[dict[str, Any]]:
        return [
            self._version_view(row)
            for row in store.rows(VERSION_TABLE)
            if row.get("dataset_code") == dataset_code
        ]

    def get_version(self, dataset_code: str, version_no: str) -> dict[str, Any] | None:
        for row in store.rows(VERSION_TABLE):
            if row.get("dataset_code") == dataset_code and row.get("version_no") == version_no:
                return self._version_view(row)
        return None

    # ---- 发布：不可变完整版本快照 ----

    def publish_dataset(self, dataset_code: str) -> dict[str, Any]:
        registry = self._find_registry(dataset_code)
        if registry is None:
            return {"ok": False, "message": f"数据集 {dataset_code} 未登记"}
        entries = copy.deepcopy(registry.get("draft_entries", []))
        if not entries:
            return {
                "ok": False,
                "blocked": True,
                "message": "没有可发布的有效条目（全部为迁移拒收坏行），发布已阻断",
                "migration_report": registry.get("migration_report", {}),
            }

        prior = [
            row for row in store.rows(VERSION_TABLE)
            if row.get("dataset_code") == dataset_code
        ]
        version_no = f"v{len(prior) + 1}"
        for row in prior:  # 历史版本原样保留，仅移交“生效中”指针
            row["status"] = "历史"
        snapshot = {
            "id": _next_id(VERSION_TABLE),
            "dataset_code": dataset_code,
            "dataset_name": registry.get("数据集名称", ""),
            "version_no": version_no,
            "entry_format": JSON_FORMAT,  # 发布统一为带版本号的 JSON 条目结构
            "source_format": registry.get("entry_format"),
            "entries": entries,            # 完整快照：发布交接期间只整版领用
            "entry_count": len(entries),
            "legacy_compatible": not has_special_chars(entries),
            "migration_report": copy.deepcopy(registry.get("migration_report", {})),
            "status": "生效中",
            "published_at": _now(),
        }
        store.rows(VERSION_TABLE).append(snapshot)
        registry["status"] = "已发布"
        registry["current_version"] = version_no
        return {
            "ok": True,
            "message": f"数据集 {dataset_code} 已发布 {version_no}",
            "version": self._version_view(snapshot),
        }

    def rollback_version(self, dataset_code: str, target_version: str, reason: str = "") -> dict[str, Any]:
        """把数据集的生效指针回滚到历史版本；版本不删除、编号不复用。"""
        target = None
        for row in store.rows(VERSION_TABLE):
            if row.get("dataset_code") != dataset_code:
                continue
            if row.get("version_no") == target_version:
                target = row
            else:
                row["status"] = "历史"
        if target is None:
            return {"ok": False, "message": f"数据集 {dataset_code} 不存在版本 {target_version}"}
        target["status"] = "生效中"
        registry = self._find_registry(dataset_code)
        if registry is not None:
            registry["current_version"] = target_version
        return {
            "ok": True,
            "message": f"数据集 {dataset_code} 已回滚到 {target_version}，历史版本均可追溯",
            "current_version": target_version,
            "reason": reason,
        }

    # ---- 清洗领用：同一完整码表版本，不拼装新旧条目 ----

    def claim_for_cleanse(self, dataset_code: str, batch_no: str) -> dict[str, Any]:
        """清洗批次按码表编号领用当前发布版次的完整快照。"""
        batch_no = str(batch_no or "").strip()
        if not batch_no:
            return {"ok": False, "message": "清洗批次号不能为空"}
        snapshot = self._active_version(dataset_code)
        if snapshot is None:
            return {
                "ok": False,
                "blocked": True,
                "reason": "no_published_version",
                "message": f"数据集 {dataset_code} 尚无已发布版本，清洗批次无可领用码表",
            }

        runtime_mode = self.get_runtime_mode()
        existing = self._find_claim(batch_no)
        if existing is not None:
            # 批次与版次一一锁定：重复领用返回同一条完整快照，
            # 绝不因发布交接而拼装或替换成其他版次的条目。
            if existing["dataset_code"] != dataset_code:
                return {
                    "ok": False,
                    "blocked": True,
                    "reason": "batch_bound_to_other_dataset",
                    "message": (
                        f"批次 {batch_no} 已锁定码表 {existing['dataset_code']}，"
                        f"不能改领 {dataset_code}"
                    ),
                }
            return {
                "ok": True,
                "message": f"批次 {batch_no} 已锁定 {dataset_code} 版次 "
                           f"{existing['version_no']}，返回原完整快照",
                "batch_no": batch_no,
                "dataset_code": dataset_code,
                "version_no": existing["version_no"],
                "entry_format": existing["entry_format"],
                "runtime_mode": existing["runtime_mode"],
                "entries": copy.deepcopy(existing["entries_snapshot"]),
                "payload": existing["served_payload"],
                "reused": True,
            }
        entries = copy.deepcopy(snapshot["entries"])
        if runtime_mode == RUNTIME_LEGACY:
            legacy_text, incompatible = entries_to_legacy_text(entries)
            if incompatible:
                # 旧版应用承载不了特殊字符版本：明确阻断，禁止静默丢值
                return {
                    "ok": False,
                    "blocked": True,
                    "reason": "legacy_incompatible_special_chars",
                    "runtime_mode": runtime_mode,
                    "dataset_code": dataset_code,
                    "blocked_version": snapshot["version_no"],
                    "incompatible_entries": incompatible,
                    "message": (
                        f"旧版应用已回切，版本 {snapshot['version_no']} 含旧结构无法保持的"
                        "特殊字符（码或值含 = / ,），领用阻断；请重新切回新版部署或回滚码表版本"
                    ),
                }
            served_format = LEGACY_FORMAT
            served_payload = legacy_text
        else:
            served_format = JSON_FORMAT
            served_payload = entries_to_json_text(entries)

        claim = {
            "id": _next_id(CLAIM_TABLE),
            "batch_no": batch_no,
            "dataset_code": dataset_code,
            "version_no": snapshot["version_no"],
            "entry_format": served_format,
            "runtime_mode": runtime_mode,
            # 整版快照复制进批次记录：之后发布/回滚都不改变本批次看到的码表
            "entries_snapshot": copy.deepcopy(entries),
            "served_payload": served_payload,
            "claimed_at": _now(),
        }
        store.rows(CLAIM_TABLE).append(claim)
        return {
            "ok": True,
            "message": f"批次 {batch_no} 已领用 {dataset_code} 的完整发布版次 {snapshot['version_no']}",
            "batch_no": batch_no,
            "dataset_code": dataset_code,
            "version_no": snapshot["version_no"],
            "entry_format": served_format,
            "runtime_mode": runtime_mode,
            "entries": copy.deepcopy(entries),
            "payload": served_payload,
        }

    def normalize(self, batch_no: str, raw_value: str) -> dict[str, Any]:
        """按批次已领用的码表版本做归一化，结果随批次留痕，供复算与追溯。"""
        claim = self._find_claim(batch_no)
        if claim is None:
            return {"ok": False, "blocked": True, "message": f"批次 {batch_no} 尚未领用码表，无法归一化"}
        mapping = entries_to_mapping(claim["entries_snapshot"])
        key = str(raw_value).strip()
        mapped = key in mapping
        normalized = mapping.get(key, key.upper())
        record = {
            "id": _next_id(RUN_TABLE),
            "batch_no": batch_no,
            "dataset_code": claim["dataset_code"],
            "version_no": claim["version_no"],
            "raw_value": raw_value,
            "normalized": normalized,
            "mapped": mapped,
            "ran_at": _now(),
        }
        store.rows(RUN_TABLE).append(record)
        return {
            "ok": True,
            "batch_no": batch_no,
            "dataset_code": claim["dataset_code"],
            "version_no": claim["version_no"],
            "raw": raw_value,
            "normalized": normalized,
            "mapped": mapped,
        }

    def recompute_batch(self, batch_no: str) -> dict[str, Any]:
        """凭批次领用记录中的版本快照复算历史结果，应与原结果逐条一致。"""
        claim = self._find_claim(batch_no)
        if claim is None:
            return {"ok": False, "message": f"批次 {batch_no} 无领用记录，无法复算"}
        mapping = entries_to_mapping(claim["entries_snapshot"])
        reruns = []
        for record in store.rows(RUN_TABLE):
            if record.get("batch_no") != batch_no:
                continue
            key = str(record["raw_value"]).strip()
            reruns.append({
                "raw": record["raw_value"],
                "original": record["normalized"],
                "recomputed": mapping.get(key, key.upper()),
                "version_no": claim["version_no"],
                "consistent": record["normalized"] == mapping.get(key, key.upper()),
            })
        return {
            "ok": True,
            "batch_no": batch_no,
            "dataset_code": claim["dataset_code"],
            "version_no": claim["version_no"],
            "entry_format": claim["entry_format"],
            "reruns": reruns,
            "all_consistent": all(item["consistent"] for item in reruns),
        }

    def list_claims(self) -> list[dict[str, Any]]:
        return [self._claim_view(row) for row in store.rows(CLAIM_TABLE)]

    def list_runs(self, batch_no: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(RUN_TABLE)
        if batch_no:
            rows = [row for row in rows if row.get("batch_no") == batch_no]
        return [dict(row) for row in rows]

    def version_rejections(self, dataset_code: str, version_no: str) -> dict[str, Any]:
        """查清某版迁移时的拒收条目（坏行单独排查入口）。"""
        version = self.get_version(dataset_code, version_no)
        if version is None:
            return {"ok": False, "message": f"版本 {dataset_code}@{version_no} 不存在"}
        report = version.get("migration_report", {})
        return {
            "ok": True,
            "dataset_code": dataset_code,
            "version_no": version_no,
            "source_format": report.get("source_format"),
            "converted": report.get("converted", 0),
            "rejected": report.get("rejected", []),
        }

    # ---- 兼容原有规则引用：ref_data_mgr 旧入口复用版本化数据 ----

    def active_mapping(self, dataset_code: str) -> dict[str, str] | None:
        """供原有清洗规则引用：返回当前生效版本的码值映射。"""
        snapshot = self._active_version(dataset_code)
        if snapshot is None:
            return None
        return entries_to_mapping(snapshot["entries"])

    def active_version_no(self, dataset_code: str) -> str | None:
        snapshot = self._active_version(dataset_code)
        return snapshot["version_no"] if snapshot else None

    # ---- 内部辅助 ----

    def _active_version(self, dataset_code: str) -> dict[str, Any] | None:
        for row in store.rows(VERSION_TABLE):
            if row.get("dataset_code") == dataset_code and row.get("status") == "生效中":
                return row
        return None

    def _find_registry(self, dataset_code: str) -> dict[str, Any] | None:
        for row in store.rows(REGISTRY_TABLE):
            if row.get("数据集编码") == dataset_code:
                return row
        return None

    def _find_claim(self, batch_no: str) -> dict[str, Any] | None:
        for row in store.rows(CLAIM_TABLE):
            if row.get("batch_no") == batch_no:
                return row
        return None

    @staticmethod
    def _registry_view(row: dict[str, Any]) -> dict[str, Any]:
        report = row.get("migration_report", {})
        return {
            "id": row.get("id"),
            "数据集编码": row.get("数据集编码"),
            "数据集名称": row.get("数据集名称"),
            "entry_format": row.get("entry_format"),
            "status": row.get("status"),
            "current_version": row.get("current_version"),
            "entry_count": len(row.get("draft_entries", [])),
            "rejected_count": len(report.get("rejected", [])),
            "migration_report": report,
            "created_at": row.get("created_at"),
        }

    @staticmethod
    def _version_view(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "dataset_code": row.get("dataset_code"),
            "dataset_name": row.get("dataset_name"),
            "version_no": row.get("version_no"),
            "entry_format": row.get("entry_format"),
            "source_format": row.get("source_format"),
            "entry_count": row.get("entry_count"),
            "legacy_compatible": row.get("legacy_compatible"),
            "status": row.get("status"),
            "entries": copy.deepcopy(row.get("entries", [])),
            "migration_report": copy.deepcopy(row.get("migration_report", {})),
            "published_at": row.get("published_at"),
        }

    @staticmethod
    def _claim_view(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "batch_no": row.get("batch_no"),
            "dataset_code": row.get("dataset_code"),
            "version_no": row.get("version_no"),
            "entry_format": row.get("entry_format"),
            "runtime_mode": row.get("runtime_mode"),
            "entry_count": len(row.get("entries_snapshot", [])),
            "claimed_at": row.get("claimed_at"),
        }


code_table_service = CodeTableService()
