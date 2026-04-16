"""ABox (Assertion Box) instance store — mock JSON files under ``ontology/abox/``.

TBox defines the schema; ABox holds instance rows keyed by object type ``apiName``.
Later this layer can swap to an ontology platform API without changing call sites.

Query API:
  abox_query(object_type, filter_attrs) → list[dict]
      Match any instance whose values equal filter_attrs on the given keys.
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_BUILTIN: dict[str, list[dict[str, Any]]] = {
    "ApplicantUser": [
        {
            "fullName": "张三",
            "idNumber": "110101199001011234",
            "userId": "U1001",
            "phone": "13900001001",
            "age": 30,
            "address": "北京市东城区XX路1号",
            "has_ms_credit_card": False,
            "is_sams_member": False,
        },
        {
            "fullName": "李四",
            "idNumber": "11010119900101SAMS_MEMBER234",
            "userId": "U1002",
            "phone": "13900001002",
            "age": 25,
            "address": "上海市浦东新区YY路2号",
            "has_ms_credit_card": False,
            "is_sams_member": True,
        },
        {
            "fullName": "王五",
            "idNumber": "11010119900101HAS_MS234",
            "userId": "U1003",
            "phone": "13900001003",
            "age": 35,
            "address": "深圳市南山区ZZ路3号",
            "has_ms_credit_card": True,
            "is_sams_member": False,
        },
        {
            "fullName": "赵六",
            "idNumber": "SAMS_MEMBER_HAS_MS",
            "userId": "U1004",
            "phone": "13900001004",
            "age": 28,
            "address": "广州市天河区AA路4号",
            "has_ms_credit_card": True,
            "is_sams_member": True,
        },
        {
            "fullName": "钱七",
            "idNumber": "440101199503073456",
            "userId": "U1005",
            "phone": "13900001005",
            "age": 31,
            "address": "杭州市西湖区BB路5号",
            "has_ms_credit_card": False,
            "is_sams_member": False,
        },
    ],
}


def reload_abox_from_dir(ontology_dir: Path) -> None:
    """Load every ``ontology/abox/*.json`` (object type → list of instance dicts)."""
    global _ABOX
    abox_dir = ontology_dir / "abox"
    if not abox_dir.is_dir():
        _ABOX = copy.deepcopy(_BUILTIN)
        log.info("abox dir missing; using built-in ApplicantUser seeds")
        return
    merged: dict[str, list[dict[str, Any]]] = {}
    for p in sorted(abox_dir.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            log.warning("skip abox file %s: %s", p, e)
            continue
        if not isinstance(data, dict):
            continue
        for ot, rows in data.items():
            if str(ot).startswith("$") or ot == "schemaVersion":
                continue
            if not isinstance(rows, list):
                continue
            bucket = merged.setdefault(str(ot), [])
            for row in rows:
                if isinstance(row, dict):
                    bucket.append(copy.deepcopy(row))
    if merged:
        _ABOX = merged
        log.info("abox loaded from %s types=%s", abox_dir, list(merged.keys()))
    else:
        _ABOX = copy.deepcopy(_BUILTIN)
        log.info("abox dir empty; using built-in ApplicantUser seeds")


def abox_list(object_type: str) -> list[dict[str, Any]]:
    return copy.deepcopy(_ABOX.get(object_type, []))


def abox_query(
    object_type: str,
    filter_attrs: dict[str, Any],
    return_keys: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Query ABox instances matching *all* filter_attrs (equality).

    Returns list of matching instances.  When *return_keys* is given only
    those keys are kept in the output dicts, plus ``found=True``.
    """
    instances = _ABOX.get(object_type, [])
    matches: list[dict[str, Any]] = []
    for inst in instances:
        if all(_match_value(inst.get(k), v) for k, v in filter_attrs.items() if v is not None and v != ""):
            matches.append(copy.deepcopy(inst))
    if return_keys:
        filtered: list[dict[str, Any]] = []
        for m in matches:
            filtered.append({k: m[k] for k in return_keys if k in m})
        return filtered
    return matches


def _match_value(stored: Any, query: Any) -> bool:
    if stored is None:
        return False
    return str(stored).strip().lower() == str(query).strip().lower()


# Initial in-process store until first reload (import side effects without ontology path)
_ABOX = copy.deepcopy(_BUILTIN)
