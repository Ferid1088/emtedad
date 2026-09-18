"""Structured logging redaction tests."""

import json
from io import StringIO
from typing import Any

from app.ops.logging import REDACTED, configure_logging, get_logger


def test_structured_logs_recursively_redact_sensitive_fields() -> None:
    stream = StringIO()
    sentinel = "never-log-this-value"
    configure_logging(level="INFO", json_logs=True, stream=stream)

    get_logger(__name__).info(
        "security.redaction_test",
        password=sentinel,
        database_url=f"postgresql://user:{sentinel}@database/app",
        nested={"api_token": sentinel, "safe": "visible"},
        safe_value="visible",
    )

    rendered = stream.getvalue()
    assert sentinel not in rendered
    event: dict[str, Any] = json.loads(rendered)
    assert event["password"] == REDACTED
    assert event["database_url"] == REDACTED
    assert event["nested"] == {"api_token": REDACTED, "safe": "visible"}
    assert event["safe_value"] == "visible"
