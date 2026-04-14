"""Pytest configuration: disable ontology file watcher in tests."""

from __future__ import annotations

import os

os.environ.setdefault("DISABLE_ONTOLOGY_WATCHER", "1")
