"""Structured logging. Document contents and credentials are not logged."""

from __future__ import annotations

import logging
import os
import sys

import structlog

_REDACTED_KEYS = {
    "password",
    "secret",
    "token",
    "authorization",
    "api_key",
    "apikey",
    "embedding",
    "content",
    "plain_text",
    "markdown",
    "jwt",
}


def _redact(_logger, _method, event_dict):
    for key in list(event_dict):
        if key.lower() in _REDACTED_KEYS or key.lower().endswith("_secret") or key.lower().endswith("_password"):
            event_dict[key] = "[redacted]"
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=getattr(logging, level.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    return structlog.get_logger(name)


def install_offline_environment() -> None:
    """Stop model and tokenizer libraries from reaching the network.

    huggingface_hub is present because the pinned tokenizers release depends on it.
    These variables are set before those libraries are used so offline mode is the default.
    """

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
