from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)


def format_compiled_graph(compiled_graph: Any) -> dict[str, Any]:
    """Serialize LangGraph `get_graph()` for logs/tests (nodes + edges)."""
    g = compiled_graph.get_graph()
    edges_out: list[dict[str, Any]] = []
    for e in g.edges:
        edges_out.append(
            {
                "source": e.source,
                "target": e.target,
                "conditional": bool(getattr(e, "conditional", False)),
            }
        )
    return {"nodes": list(g.nodes), "edges": edges_out}


def compiled_graph_edges_summary(edges: list[dict[str, Any]], max_len: int = 500) -> str:
    """One-line edge list for INFO logs (e.g. __start__->a, a->__end__)."""
    parts: list[str] = []
    for e in edges:
        suffix = "?" if e.get("conditional") else ""
        parts.append(f"{e['source']}->{e['target']}{suffix}")
    s = ", ".join(parts)
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def compiled_graph_mermaid(summary: dict[str, Any]) -> str:
    """Build a readable Mermaid flowchart from graph summary."""
    lines = ["flowchart TD"]
    nodes = [str(n) for n in summary.get("nodes", [])]
    for n in nodes:
        lines.append(f"  {n}[{n}]")
    for e in summary.get("edges", []):
        src = str(e.get("source"))
        tgt = str(e.get("target"))
        if e.get("conditional"):
            lines.append(f"  {src} -->|conditional| {tgt}")
        else:
            lines.append(f"  {src} --> {tgt}")
    return "\n".join(lines)


def compiled_graph_mermaid_one_line(summary: dict[str, Any], max_len: int = 1200) -> str:
    """Single-line Mermaid for log systems that fold multiline text."""
    parts: list[str] = ["flowchart TD"]
    nodes = [str(n) for n in summary.get("nodes", [])]
    for n in nodes:
        parts.append(f"{n}[{n}]")
    for e in summary.get("edges", []):
        src = str(e.get("source"))
        tgt = str(e.get("target"))
        if e.get("conditional"):
            parts.append(f'{src} -->|"conditional"| {tgt}')
        else:
            parts.append(f"{src} --> {tgt}")
    out = "; ".join(parts)
    if len(out) <= max_len:
        return out
    return out[: max_len - 3] + "..."

_SENSITIVE_KEYS = frozenset(
    {
        "phone",
        "mobile",
        "password",
        "token",
        "secret",
        "authorization",
    }
)


def _is_sensitive_property_key(key: str) -> bool:
    lk = key.lower().replace("_", "")
    if lk in _SENSITIVE_KEYS:
        return True
    if "idnumber" in lk:
        return True
    if "id" in lk and "number" in lk:
        return True
    if lk in ("idcard", "creditcard", "bankcard"):
        return True
    return False


def mask_id_number(value: str | None, keep: int = 4) -> str:
    if not value or not str(value).strip():
        return ""
    s = str(value).strip()
    if len(s) <= keep:
        return "*" * len(s)
    return "*" * (len(s) - keep) + s[-keep:]


def _maybe_mask_key(key: str, val: Any) -> Any:
    if _is_sensitive_property_key(key):
        if isinstance(val, str):
            return mask_id_number(val)
        return "<non-string>"
    if isinstance(val, str) and len(val) > 120:
        return val[:117] + "..."
    return val


def sanitize_attrs_for_log(attrs: dict[str, Any] | None) -> dict[str, Any]:
    if not attrs:
        return {}
    out: dict[str, Any] = {}
    for k, v in attrs.items():
        out[k] = _maybe_mask_key(k, v)
    return out


def sanitize_payload_for_log(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    p = dict(payload)
    if "attrs" in p and isinstance(p["attrs"], dict):
        p["attrs"] = sanitize_attrs_for_log(p["attrs"])
    return p


def truncate_json(data: Any, max_len: int = 800) -> str:
    try:
        s = json.dumps(data, ensure_ascii=False, default=str)
    except TypeError:
        s = repr(data)
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def log_interrupt_brief(logger: logging.Logger, intr: Any) -> None:
    if not isinstance(intr, dict):
        logger.info("interrupt: %s", type(intr).__name__)
        return
    logger.info(
        "interrupt kind=%s node_id=%s missing=%s",
        intr.get("kind"),
        intr.get("node_id"),
        intr.get("missing"),
    )
