"""码表条目格式工具：旧版逗号/等号结构与新版 JSON 条目结构的解析、转换与兼容判定。

背景：旧码表用 ``CN=中国,US=美国`` 这种逗号分隔、等号切分的纯文本存码值。
一旦业务值本身带 ``=`` 或 ``,``（例如 ``A=B`` 要作为一个完整码值），
旧结构就无法判明边界。新版改为带版本号的 JSON 条目结构，
本模块负责两套结构之间的解析、迁移与回退判定，规则：

1. 旧格式里能无歧义读出的有效条目继续转换，行为与历史实现保持一致；
2. 无法判明边界的条目不静默丢值，进入拒收清单并保留原文和原因；
3. 新格式条目转回旧结构时，只要码或值含分隔符就整体阻断并给出明确回执。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

LEGACY_CODE_SEP = "="
LEGACY_ITEM_SEP = ","
JSON_FORMAT = "json_entries"
LEGACY_FORMAT = "legacy_csv"


@dataclass
class RejectedLine:
    """迁移拒收条目：坏行可单独排查，原文与原因必须完整保留。"""

    raw: str
    reason: str
    index: int

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "raw": self.raw, "reason": self.reason}


@dataclass
class LegacyParseResult:
    """旧格式解析结果：可转换条目与拒收条目分开，拒收不影响好行发布。"""

    entries: list[dict[str, str]] = field(default_factory=list)
    rejected: list[RejectedLine] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": list(self.entries),
            "rejected": [line.to_dict() for line in self.rejected],
        }


def parse_legacy_text(text: str) -> LegacyParseResult:
    """解析旧版 ``码=值,码=值`` 文本。

    判定口径（与历史 ``split("=")`` 的无歧义情形保持一致）：

    * 空白片段忽略；
    * 片段里没有 ``=``、或 ``=`` 两侧任一为空 → 拒收（无法构成码值对）；
    * 片段里多于一个 ``=`` → 拒收（等号可能属于业务值，无法判明切分边界，
      例如 ``A=B=C``，旧实现会直接抛错丢值，这里改为保留原文与原因）；
    * 片段里含逗号不可能出现（逗号是条目分隔符），值里带逗号的旧文本
      会被切成多段，其中无等号的段按坏行拒收，原文仍可在拒收清单追溯；
    * 码重复 → 拒收（边界本身无歧义但同一码表内不允许一对多，避免覆盖）。
    """
    result = LegacyParseResult()
    seen: set[str] = set()
    for index, chunk in enumerate(str(text or "").split(LEGACY_ITEM_SEP)):
        raw = chunk.strip()
        if not raw:
            continue
        if raw.count(LEGACY_CODE_SEP) == 0:
            result.rejected.append(
                RejectedLine(raw, "缺少等号分隔符，无法判明码与值的边界", index))
            continue
        if raw.count(LEGACY_CODE_SEP) > 1:
            result.rejected.append(
                RejectedLine(raw, "存在多个等号，无法判明切分边界（业务值可能含=）", index))
            continue
        code, value = (part.strip() for part in raw.split(LEGACY_CODE_SEP, 1))
        if not code or not value:
            result.rejected.append(
                RejectedLine(raw, "码或值为空，无法构成有效码值对", index))
            continue
        if code in seen:
            result.rejected.append(
                RejectedLine(raw, f"码 {code} 重复，无法确定唯一标准值", index))
            continue
        seen.add(code)
        result.entries.append({"code": code, "value": value})
    return result


def parse_json_entries(text: str) -> tuple[list[dict[str, str]] | None, str | None]:
    """解析新版 JSON 条目文本。

    接受两种 JSON 形态：

    * 条目数组 ``[{"code": "A=B", "value": "完整业务值"}]``；
    * 码值对象 ``{"A=B": "完整业务值"}``。

    码、值都按字符串处理，允许包含任意逗号、等号与空白，不会被二次切分。
    返回 ``(entries, error)``，解析失败时 entries 为 None 并给出原因。
    """
    try:
        payload = json.loads(str(text or "").strip())
    except (json.JSONDecodeError, TypeError) as exc:
        return None, f"JSON 条目无法解析：{exc}"
    entries: list[dict[str, str]] = []
    if isinstance(payload, list):
        for index, item in enumerate(payload):
            if not isinstance(item, dict):
                return None, f"第 {index + 1} 个条目不是 JSON 对象"
            code = item.get("code")
            value = item.get("value")
            if code is None or value is None:
                return None, f"第 {index + 1} 个条目缺少 code/value 字段"
            entries.append({"code": str(code), "value": str(value)})
    elif isinstance(payload, dict):
        entries = [{"code": str(code), "value": str(value)} for code, value in payload.items()]
    else:
        return None, "JSON 条目必须是数组或码值对象"
    codes = [entry["code"] for entry in entries]
    if len(codes) != len(set(codes)):
        return None, "JSON 条目存在重复码，无法确定唯一标准值"
    if any(not entry["code"] for entry in entries):
        return None, "JSON 条目存在空码"
    return entries, None


def entries_to_legacy_text(entries: list[dict[str, str]]) -> tuple[str | None, list[dict[str, str]]]:
    """把 JSON 条目尝试转回旧结构。

    只要有一个条目的码或值含旧分隔符（``=`` 或 ``,``），旧结构就承载不了，
    整体阻断（不做半转换、不静默丢值），返回不可转换条目清单供回执展示。
    """
    incompatible = [
        entry for entry in entries
        if LEGACY_CODE_SEP in entry["code"]
        or LEGACY_ITEM_SEP in entry["code"]
        or LEGACY_CODE_SEP in entry["value"]
        or LEGACY_ITEM_SEP in entry["value"]
    ]
    if incompatible:
        return None, incompatible
    return LEGACY_ITEM_SEP.join(
        f"{entry['code']}{LEGACY_CODE_SEP}{entry['value']}" for entry in entries
    ), []


def entries_to_json_text(entries: list[dict[str, str]]) -> str:
    """序列化为新版 JSON 条目文本（ensure_ascii=False 保留中文原文）。"""
    return json.dumps(entries, ensure_ascii=False, indent=2)


def entries_to_mapping(entries: list[dict[str, str]]) -> dict[str, str]:
    """条目转码值映射，供标准化归一化使用。"""
    return {entry["code"]: entry["value"] for entry in entries}


def has_special_chars(entries: list[dict[str, str]]) -> bool:
    """判断条目是否含旧结构无法保持的特殊字符。"""
    text, incompatible = entries_to_legacy_text(entries)
    return bool(incompatible)
