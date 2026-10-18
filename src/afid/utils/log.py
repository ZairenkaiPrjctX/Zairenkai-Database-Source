"""Structured logging: one JSON object per line on stderr when AFID_LOG_FORMAT=json."""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

_RESERVED = set(vars(logging.makeLogRecord({})))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update({k: v for k, v in vars(record).items() if k not in _RESERVED})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _StderrHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Writes to the *current* sys.stderr (which tests and embedding callers may replace)."""

    @property
    def stream(self) -> Any:
        return sys.stderr

    @stream.setter
    def stream(self, value: Any) -> None:
        pass


def setup(verbose: bool = False) -> None:
    handler = _StderrHandler()
    if os.environ.get("AFID_LOG_FORMAT") == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("afid")
    root.handlers[:] = [handler]
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.propagate = False


def get(name: str) -> logging.Logger:
    return logging.getLogger(f"afid.{name}")
