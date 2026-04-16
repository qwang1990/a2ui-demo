from __future__ import annotations

import os
from pathlib import Path


def ontology_dir() -> Path:
    raw = os.environ.get("ONTOLOGY_DIR")
    if raw:
        return Path(raw).resolve()
    return (Path(__file__).resolve().parents[3] / "ontology").resolve()


def log_level() -> str:
    return os.environ.get("LOG_LEVEL", "INFO").upper()


def openrouter_api_key() -> str | None:
    return os.environ.get("OPENROUTER_API_KEY")


def openrouter_model() -> str:
    return os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")


def openrouter_base_url() -> str:
    return os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")


def openrouter_http_referer() -> str | None:
    v = os.environ.get("OPENROUTER_HTTP_REFERER", "").strip()
    return v or None


def openrouter_app_title() -> str | None:
    v = os.environ.get("OPENROUTER_APP_TITLE", "").strip()
    return v or None


def mock_ontology_base_url() -> str:
    return os.environ.get("MOCK_ONTOLOGY_BASE_URL", "http://127.0.0.1:8765")


def llm_form_schema_enabled() -> bool:
    return os.environ.get("ENABLE_LLM_FORM_SCHEMA", "1").lower() in ("1", "true", "yes")


def llm_ui_intent_enabled() -> bool:
    return os.environ.get("ENABLE_LLM_UI_INTENT", "1").lower() in ("1", "true", "yes")


def llm_full_a2ui_enabled() -> bool:
    """When true, user_input LLM may return full v0.8 A2UI messages (see llm_user_input_union)."""
    return os.environ.get("ENABLE_LLM_FULL_A2UI", "0").lower() in ("1", "true", "yes")
