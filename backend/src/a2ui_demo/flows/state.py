from __future__ import annotations

from typing import Any, TypedDict


class FlowState(TypedDict, total=False):
    """LangGraph state for AIP logic execution."""

    flow_id: str
    attrs: dict[str, Any]
    outcome: str | None
    terminal_message: str | None
    terminal_node_id: str | None
    current_node_id: str | None
    step_hint: str | None
    _branch: str
