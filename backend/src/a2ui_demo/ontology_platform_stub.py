"""本体平台对接占位（未来实现）。

当前 TBox / ABox 以 ``ontology/tbox``、``ontology/abox`` 下 JSON 为数据源；
编排里 ``logicParameterBindings`` 描述上游 ``attrs`` 与 logic HTTP 路径占位符的映射（见 ``ontology_models``）；
后续可在此模块实现：

- ``pull_tbox_from_platform(tenant_id, tbox_ref) -> dict``
- ``pull_abox_from_platform(tenant_id, abox_ref) -> dict``
- ``push_flow_to_platform(...)`` 等

服务端在启动与热加载时仍从本地 JSON 合并；对接完成后可在 lifespan 或定时任务中
用平台返回结果覆盖/合并本地缓存。
"""

from __future__ import annotations

from typing import Any


def pull_tbox_from_platform_stub(tenant_id: str | None, tbox_ref: str) -> dict[str, Any] | None:
    """预留：从本体平台拉取 TBox schema。当前返回 None 表示未对接，由调用方读本地 JSON。"""
    _ = (tenant_id, tbox_ref)
    return None


def pull_abox_from_platform_stub(tenant_id: str | None, abox_ref: str) -> dict[str, Any] | None:
    """预留：从本体平台拉取 ABox 实例数据。当前返回 None 表示未对接。"""
    _ = (tenant_id, abox_ref)
    return None
