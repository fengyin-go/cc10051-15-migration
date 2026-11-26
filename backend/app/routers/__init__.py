"""业务路由汇总：通用资源路由 + 码表版本化专用路由。

码表路由使用固定前缀 /api/code-tables，与通用资源路由
/api/{module} 路径不重叠，统一在 main.py 健康检查之后注册。
"""
from __future__ import annotations

from app.routers.code_table import router as code_table_router
from app.routers.resource import router as resource_router

ROUTERS = [code_table_router, resource_router]
