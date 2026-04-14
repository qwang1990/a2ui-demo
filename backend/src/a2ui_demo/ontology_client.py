from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)


def interpolate_request_path(path_template: str, attrs: dict[str, Any]) -> tuple[str | None, list[str]]:
    """
    Replace `{attrApiName}` with URL-encoded values from attrs (camelCase keys).
    Returns (resolved path starting with /, missing attribute names if any).
    """
    keys = re.findall(r"\{([\w]+)\}", path_template)
    seen: list[str] = []
    for k in keys:
        if k not in seen:
            seen.append(k)
    missing = [k for k in seen if k not in attrs or not str(attrs.get(k, "")).strip()]
    if missing:
        return None, missing
    out = path_template
    for k in keys:
        out = out.replace("{" + k + "}", quote(str(attrs[k]), safe=""))
    if not out.startswith("/"):
        out = "/" + out
    return out, []


class OntologyPlatformClient:
    """HTTP client for mock ontology / external logic endpoints."""

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def get_json(self, path: str) -> dict[str, Any]:
        """GET {base}{path}; path must start with /."""
        p = path if path.startswith("/") else f"/{path}"
        url = f"{self._base}{p}"
        log.info("ontology GET %s", url)
        try:
            with httpx.Client(timeout=self._timeout) as client:
                r = client.get(url)
                r.raise_for_status()
                data = r.json()
        except Exception:
            log.exception("ontology request failed url=%s", url)
            raise
        log.debug("ontology response keys=%s", list(data.keys()) if isinstance(data, dict) else type(data))
        return data if isinstance(data, dict) else {}

    def fetch_user_flags(self, id_number: str) -> dict[str, Any]:
        """Backward-compatible helper for single-path user mock."""
        return self.get_json(f"/api/mock-ontology/user/{quote(str(id_number), safe='')}")
