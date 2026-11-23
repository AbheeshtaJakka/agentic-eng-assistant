"""Append-only audit log of every tool call: who did what, with which arguments, and the outcome.

Phase 1 writes JSON Lines to a file; phase 5 moves this into a Postgres `audit_log` table and
adds the approver for write actions. Arguments are redacted and truncated before writing.
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from engassist.contracts import utcnow
from engassist.workspace import redact

MAX_ARG_CHARS = 500


class AuditLog:
    def __init__(self, path: Path | None):
        self.path = path
        self._lock = threading.Lock()
        self.records: list[dict[str, Any]] = []  # in-memory copy (tests, per-task summaries)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        task_id: str,
        agent: str,
        tool: str,
        args: dict[str, Any],
        status: str,
        duration_ms: float,
        detail: str = "",
    ) -> None:
        entry = {
            "ts": utcnow().isoformat(),
            "task_id": task_id,
            "agent": agent,
            "tool": tool,
            "args": {k: _clip(redact(str(v))) for k, v in args.items()},
            "status": status,
            "duration_ms": round(duration_ms, 1),
            "detail": _clip(redact(detail)),
        }
        with self._lock:
            self.records.append(entry)
            if self.path:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")

    @contextmanager
    def timed(self, *, task_id: str, agent: str, tool: str, args: dict[str, Any]):
        """Usage: with audit.timed(...) as done: result = ...; done("ok")"""
        t0 = time.perf_counter()
        outcome = {"status": "error", "detail": "exception"}

        def done(status: str, detail: str = "") -> None:
            outcome.update(status=status, detail=detail)

        try:
            yield done
        finally:
            self.record(
                task_id=task_id,
                agent=agent,
                tool=tool,
                args=args,
                duration_ms=(time.perf_counter() - t0) * 1000,
                **outcome,
            )


def _clip(s: str) -> str:
    return s if len(s) <= MAX_ARG_CHARS else s[:MAX_ARG_CHARS] + f"...(+{len(s) - MAX_ARG_CHARS})"
