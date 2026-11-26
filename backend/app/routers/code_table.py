"""码表版本化接口：登记/迁移/发布/回滚/清洗领用/复算/拒收排查。

路径统一挂在 ``/api/code-tables`` 下，与通用资源路由
``/api/{module}`` 并存；固定前缀先注册，不会被动态路径抢占。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.code_table_service import RUNTIME_LEGACY, RUNTIME_NEW, code_table_service

router = APIRouter(prefix="/api/code-tables", tags=["码表版本化"])


class RegisterPayload(BaseModel):
    dataset_code: str
    dataset_name: str
    entry_format: str = Field(description="json_entries 或 legacy_csv")
    entry_text: str


class PublishPayload(BaseModel):
    dataset_code: str


class RollbackPayload(BaseModel):
    dataset_code: str
    target_version: str
    reason: str = ""


class RuntimePayload(BaseModel):
    mode: str = Field(description="new_runtime 或 legacy_runtime")
    reason: str = ""


class ClaimPayload(BaseModel):
    dataset_code: str
    batch_no: str


class NormalizePayload(BaseModel):
    batch_no: str
    raw_value: str


@router.get("/runtime")
def get_runtime() -> dict[str, Any]:
    return {"ok": True, "runtime_mode": code_table_service.get_runtime_mode()}


@router.post("/runtime/switch")
def switch_runtime(payload: RuntimePayload) -> dict[str, Any]:
    return code_table_service.switch_runtime(payload.mode, payload.reason)


@router.get("/datasets")
def list_datasets() -> dict[str, Any]:
    return {"ok": True, "items": code_table_service.list_datasets()}


@router.post("/register")
def register_dataset(payload: RegisterPayload) -> dict[str, Any]:
    return code_table_service.register_dataset(
        payload.dataset_code, payload.dataset_name,
        payload.entry_format, payload.entry_text,
    )


@router.post("/publish")
def publish_dataset(payload: PublishPayload) -> dict[str, Any]:
    return code_table_service.publish_dataset(payload.dataset_code)


@router.post("/rollback")
def rollback_version(payload: RollbackPayload) -> dict[str, Any]:
    return code_table_service.rollback_version(
        payload.dataset_code, payload.target_version, payload.reason)


@router.get("/versions/{dataset_code}")
def list_versions(dataset_code: str) -> dict[str, Any]:
    return {"ok": True, "items": code_table_service.list_versions(dataset_code)}


@router.get("/versions/{dataset_code}/{version_no}")
def get_version(dataset_code: str, version_no: str) -> dict[str, Any]:
    version = code_table_service.get_version(dataset_code, version_no)
    if version is None:
        return {"ok": False, "message": f"版本 {dataset_code}@{version_no} 不存在"}
    return {"ok": True, "version": version}


@router.get("/versions/{dataset_code}/{version_no}/rejections")
def version_rejections(dataset_code: str, version_no: str) -> dict[str, Any]:
    return code_table_service.version_rejections(dataset_code, version_no)


@router.post("/claim")
def claim_for_cleanse(payload: ClaimPayload) -> dict[str, Any]:
    return code_table_service.claim_for_cleanse(payload.dataset_code, payload.batch_no)


@router.post("/normalize")
def normalize(payload: NormalizePayload) -> dict[str, Any]:
    return code_table_service.normalize(payload.batch_no, payload.raw_value)


@router.post("/recompute/{batch_no}")
def recompute_batch(batch_no: str) -> dict[str, Any]:
    return code_table_service.recompute_batch(batch_no)


@router.get("/claims")
def list_claims() -> dict[str, Any]:
    return {"ok": True, "items": code_table_service.list_claims()}


@router.get("/runs")
def list_runs(batch_no: str | None = None) -> dict[str, Any]:
    return {"ok": True, "items": code_table_service.list_runs(batch_no)}
