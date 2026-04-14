from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class OntologyPlatformClient:
    """HTTP client for mock ontology platform flags."""

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def fetch_user_flags(self, id_number: str) -> dict[str, Any]:
        url = f"{self._base}/api/mock-ontology/user/{id_number}"
        log.info("ontology GET %s (id_len=%d)", url, len(id_number))
        try:
            with httpx.Client(timeout=self._timeout) as client:
                r = client.get(url)
                r.raise_for_status()
                data = r.json()
        except Exception:
            log.exception("ontology request failed url=%s", url)
            raise
        log.debug("ontology response keys=%s", list(data.keys()) if isinstance(data, dict) else type(data))
        return data
