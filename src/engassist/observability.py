"""Structured JSON logs. Agent traces come from the Agents SDK's built-in tracing (grouped by
task id); phase 8 adds LangSmith so workflow, agent and tool spans share one trace tree."""

from __future__ import annotations

import json
import logging
import sys

_STD = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update({k: v for k, v in record.__dict__.items() if k not in _STD})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO", json_logs: bool = True) -> None:
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(JsonFormatter() if json_logs else logging.Formatter("%(levelname)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
