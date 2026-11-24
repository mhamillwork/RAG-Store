"""Shared test configuration."""

from __future__ import annotations

import os

os.environ.setdefault("RAG_STORE_ENVIRONMENT", "test")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
