"""Structured, correlation-aware, secret-redacting logging."""

import logging
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any, TextIO, cast

import structlog

REDACTED = "[REDACTED]"
SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "database_url",
    "password",
    "secret",
    "token",
)


def _redact_value(key: str, value: Any) -> Any:
    if any(part in key.lower() for part in SENSITIVE_KEY_PARTS):
        return REDACTED
    if isinstance(value, Mapping):
        return {
            nested_key: _redact_value(str(nested_key), nested_value)
            for nested_key, nested_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(key, item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(key, item) for item in value)
    return value


def redact_sensitive_fields(
    _logger: Any,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Recursively redact values associated with sensitive field names."""

    return {key: _redact_value(key, value) for key, value in event_dict.items()}


def configure_logging(
    *,
    level: str,
    json_logs: bool,
    stream: TextIO | None = None,
) -> None:
    """Configure stdlib and structlog through one redacting processor chain."""

    output_stream = stream or sys.stdout
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level),
        stream=output_stream,
        force=True,
    )

    renderer: structlog.types.Processor
    if json_logs:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_sensitive_fields,
            renderer,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a typed structured logger."""

    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
