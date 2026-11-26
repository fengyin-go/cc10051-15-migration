"""码表版本化种子数据：演示旧格式迁移、历史版本追溯与特殊字符新条目。

数据独立于通用 SEED_ROWS，由 store 初始化时调用 :func:`seed_code_tables`
写入码表专属表，包含：

* REF-COUNTRY：旧版 ``码=值`` 文本迁移而来的国家码表，已发布 v1，
  另保留一份历史 v1 之前的原始登记，用于旧批次复算演示；
* REF-STATUS：旧格式里混入坏行（多等号、缺等号、空值、重复码），
  演示无歧义好行继续转换、坏行保留原文与原因；
* REF-FORMULA：新版 JSON 条目，含旧结构无法保持的 ``A=B`` 特殊码值，
  处于草稿状态，供“发布后回滚冲突”场景使用。
"""
from __future__ import annotations

import copy
import json
from typing import Any

from app.services.code_table_format import (
    JSON_FORMAT,
    LEGACY_FORMAT,
    has_special_chars,
    parse_legacy_text,
)

# 与 code_table_service 中的表名/模式常量保持一致；这里用字面量解耦，
# 避免 store -> seed -> service -> store 的循环导入。
REGISTRY_TABLE = "code_table_registry"
VERSION_TABLE = "code_table_version"
CLAIM_TABLE = "code_table_claim"
RUN_TABLE = "code_table_run"
SETTING_TABLE = "code_table_setting"
RUNTIME_NEW = "new_runtime"


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()

COUNTRY_CODE = "REF-COUNTRY"
STATUS_CODE = "REF-STATUS"
FORMULA_CODE = "REF-FORMULA"


def seed_code_tables(tables: dict[str, list[dict[str, Any]]]) -> None:
    for name in (REGISTRY_TABLE, VERSION_TABLE, CLAIM_TABLE, RUN_TABLE, SETTING_TABLE):
        tables.setdefault(name, [])
    tables[SETTING_TABLE].append({"id": 1, "runtime_mode": RUNTIME_NEW, "updated_at": _now()})

    # ---- REF-COUNTRY：旧格式迁移的国家码表，含已发布版本与历史版本 ----
    country_legacy = "CN=中国,US=美国,JP=日本,GB=英国"
    country_parsed = parse_legacy_text(country_legacy)
    country_entries = country_parsed.entries
    tables[REGISTRY_TABLE].append({
        "id": 1,
        "数据集编码": COUNTRY_CODE,
        "数据集名称": "国家地区码表",
        "entry_format": LEGACY_FORMAT,
        "raw_text": country_legacy,
        "draft_entries": copy.deepcopy(country_entries),
        "migration_report": {
            "source_format": LEGACY_FORMAT,
            "converted": len(country_entries),
            "rejected": [],
        },
        "status": "已发布",
        "current_version": "v2",
        "created_at": _now(),
    })
    # 历史 v1：旧批次曾经领用的完整版本（编号原样保留，可追溯、可复算）
    tables[VERSION_TABLE].append({
        "id": 1,
        "dataset_code": COUNTRY_CODE,
        "dataset_name": "国家地区码表",
        "version_no": "v1",
        "entry_format": JSON_FORMAT,
        "source_format": LEGACY_FORMAT,
        "entries": [
            {"code": "CN", "value": "中国"},
            {"code": "US", "value": "美国"},
            {"code": "JP", "value": "日本"},
        ],
        "entry_count": 3,
        "legacy_compatible": True,
        "migration_report": {"source_format": LEGACY_FORMAT, "converted": 3, "rejected": []},
        "status": "历史",
        "published_at": _now(),
    })
    # 生效 v2：迁移后的完整发布版次，清洗端当前领到这一版
    tables[VERSION_TABLE].append({
        "id": 2,
        "dataset_code": COUNTRY_CODE,
        "dataset_name": "国家地区码表",
        "version_no": "v2",
        "entry_format": JSON_FORMAT,
        "source_format": LEGACY_FORMAT,
        "entries": copy.deepcopy(country_entries),
        "entry_count": len(country_entries),
        "legacy_compatible": not has_special_chars(country_entries),
        "migration_report": {
            "source_format": LEGACY_FORMAT,
            "converted": len(country_entries),
            "rejected": [],
        },
        "status": "生效中",
        "published_at": _now(),
    })
    # 历史批次 BATCH-20260901-01 已领用 v1 并产生归一化记录，供复算演示
    tables[CLAIM_TABLE].append({
        "id": 1,
        "batch_no": "BATCH-20260901-01",
        "dataset_code": COUNTRY_CODE,
        "version_no": "v1",
        "entry_format": LEGACY_FORMAT,
        "runtime_mode": RUNTIME_NEW,
        "entries_snapshot": [
            {"code": "CN", "value": "中国"},
            {"code": "US", "value": "美国"},
            {"code": "JP", "value": "日本"},
        ],
        "served_payload": "CN=中国,US=美国,JP=日本",
        "claimed_at": _now(),
    })
    tables[RUN_TABLE].append({
        "id": 1,
        "batch_no": "BATCH-20260901-01",
        "dataset_code": COUNTRY_CODE,
        "version_no": "v1",
        "raw_value": "CN",
        "normalized": "中国",
        "mapped": True,
        "ran_at": _now(),
    })

    # ---- REF-STATUS：旧格式含坏行，好行迁移、坏行进拒收报告 ----
    status_legacy = (
        "1=启用,0=停用,A=B=C,9=,坏行没有等号,"
        "2=待审核,1=重复启用码,3=注销, ,=空码"
    )
    status_parsed = parse_legacy_text(status_legacy)
    tables[REGISTRY_TABLE].append({
        "id": 2,
        "数据集编码": STATUS_CODE,
        "数据集名称": "业务状态码表",
        "entry_format": LEGACY_FORMAT,
        "raw_text": status_legacy,
        "draft_entries": copy.deepcopy(status_parsed.entries),
        "migration_report": {
            "source_format": LEGACY_FORMAT,
            "converted": len(status_parsed.entries),
            "rejected": [line.to_dict() for line in status_parsed.rejected],
        },
        "status": "草稿",
        "current_version": None,
        "created_at": _now(),
    })

    # ---- REF-FORMULA：新版 JSON 条目，含旧结构无法保持的 A=B 特殊码值 ----
    formula_entries = [
        {"code": "A=B", "value": "公式型业务值 X=Y*2"},
        {"code": "NORMAL", "value": "普通值"},
        {"code": "LIST,ITEMS", "value": "带逗号的码"},
    ]
    tables[REGISTRY_TABLE].append({
        "id": 3,
        "数据集编码": FORMULA_CODE,
        "数据集名称": "公式参数码表",
        "entry_format": JSON_FORMAT,
        "raw_text": json.dumps(formula_entries, ensure_ascii=False),
        "draft_entries": formula_entries,
        "migration_report": {
            "source_format": JSON_FORMAT,
            "converted": len(formula_entries),
            "rejected": [],
        },
        "status": "草稿",
        "current_version": None,
        "created_at": _now(),
    })
