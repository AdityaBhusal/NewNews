"""Structured (JSON) logging with correlation IDs."""

from __future__ import annotations

import json
import logging
import sys
import time

from app.core.context import get_correlation_id

# Keys forwarded from LogRecord extras into the JSON payload.
_EXTRAS = (
    "event",
    "stage",
    "item_id",
    "job_id",
    "client_id",
    "correlation_id",
    "duration_ms",
    "latency_ms",
    "status",
    "attempts",
    "worker",
    "method",
    "path",
    "code",
    "error",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", None) or get_correlation_id(),
        }
        for key in _EXTRAS:
            if key == "correlation_id":
                continue
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    logging.getLogger("uvicorn.access").setLevel("WARNING")
    logging.getLogger("sqlalchemy.engine").setLevel("WARNING")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
