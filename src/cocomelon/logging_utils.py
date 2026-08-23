from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

SECRET_KEYS = {
    "secret_key",
    "private_key",
    "agent_private_key",
    "authorization",
    "password",
}


def redact_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, item in value.items():
        if key.lower() in SECRET_KEYS:
            output[key] = "[REDACTED]"
        elif isinstance(item, Mapping):
            output[key] = redact_mapping(item)
        else:
            output[key] = item
    return output


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
