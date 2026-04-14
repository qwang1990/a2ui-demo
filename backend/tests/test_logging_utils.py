from __future__ import annotations

from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from a2ui_demo.logging_utils import (
    compiled_graph_edges_summary,
    compiled_graph_mermaid,
    compiled_graph_mermaid_one_line,
    format_compiled_graph,
    mask_id_number,
    sanitize_attrs_for_log,
)


def test_mask_id_number() -> None:
    assert mask_id_number("110101199001011234") == "**************1234"
    assert mask_id_number("ab") == "**"


def test_sanitize_attrs_masks_id_number() -> None:
    s = sanitize_attrs_for_log({"fullName": "张三", "idNumber": "110101199001011234", "phone": "13800138000"})
    assert s["fullName"] == "张三"
    assert "1234" in s["idNumber"] and s["idNumber"].startswith("*")
    assert "*" in str(s["phone"])


class _MiniState(TypedDict, total=False):
    x: int


def test_format_compiled_graph_nodes_and_edges() -> None:
    builder = StateGraph(_MiniState)
    builder.add_node("step_a", lambda s: {"x": 1})
    builder.add_edge(START, "step_a")
    builder.add_edge("step_a", END)
    compiled = builder.compile(checkpointer=MemorySaver())
    summary = format_compiled_graph(compiled)
    assert "__start__" in summary["nodes"]
    assert "step_a" in summary["nodes"]
    assert "__end__" in summary["nodes"]
    assert isinstance(summary["edges"], list)
    assert any(e["source"] == "__start__" and e["target"] == "step_a" for e in summary["edges"])
    assert any(e["source"] == "step_a" and e["target"] == "__end__" for e in summary["edges"])


def test_compiled_graph_edges_summary_truncates() -> None:
    edges = [{"source": "a", "target": "b", "conditional": False} for _ in range(200)]
    s = compiled_graph_edges_summary(edges, max_len=80)
    assert len(s) <= 80
    assert s.endswith("...")


def test_compiled_graph_mermaid_contains_nodes_and_edges() -> None:
    summary = {
        "nodes": ["__start__", "collect_basic", "__end__"],
        "edges": [
            {"source": "__start__", "target": "collect_basic", "conditional": False},
            {"source": "collect_basic", "target": "__end__", "conditional": False},
        ],
    }
    m = compiled_graph_mermaid(summary)
    assert "flowchart TD" in m
    assert "__start__ --> collect_basic" in m
    assert "collect_basic --> __end__" in m


def test_compiled_graph_mermaid_one_line_single_row() -> None:
    summary = {
        "nodes": ["__start__", "n1", "__end__"],
        "edges": [
            {"source": "__start__", "target": "n1", "conditional": False},
            {"source": "n1", "target": "__end__", "conditional": True},
        ],
    }
    m = compiled_graph_mermaid_one_line(summary)
    assert "\n" not in m
    assert "flowchart TD;" in m
    assert '__start__ --> n1' in m
    assert 'n1 -->|"conditional"| __end__' in m
