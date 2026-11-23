"""Task execution and the in-process task service.

`execute_task` is the one code path that runs an agent against a workspace; the API, the CLI
and the eval harness all use it. The diff is always computed from the workspace, never taken
from the agent's own claims.

Phase 1 keeps tasks in memory and runs them as asyncio tasks inside the API process. Phase 3
replaces this with a Redis job queue, separate workers and Postgres-checkpointed LangGraph
runs, so tasks survive restarts.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from engassist.audit import AuditLog
from engassist.contracts import AgentOutcome, TaskRecord, TaskRequest, TaskStatus
from engassist.tools import TaskContext
from engassist.workspace import Workspace, WorkspaceError

log = logging.getLogger(__name__)


class CodingRunner(Protocol):
    async def run(self, ctx: TaskContext, issue: str) -> AgentOutcome: ...


async def execute_task(
    record: TaskRecord, ws: Workspace, runner: CodingRunner, audit: AuditLog, timeout_s: float
) -> TaskRecord:
    """Run the agent on `ws` and fill in `record`. Never raises: failures land in the record."""
    record.touch(TaskStatus.running)
    ctx = TaskContext(task_id=str(record.task_id), workspace=ws, audit=audit)
    try:
        outcome = await asyncio.wait_for(runner.run(ctx, record.request.issue), timeout_s)
        record.summary = outcome.result.summary
        record.risks = outcome.result.risks
        record.usage = outcome.usage
        change = ws.diff()
        record.change = change if change.files_changed else None
        record.touch(TaskStatus.succeeded if change.files_changed else TaskStatus.no_change)
    except TimeoutError:
        record.error = f"timed out after {timeout_s:.0f}s"
        record.touch(TaskStatus.failed)
    except Exception as e:  # noqa: BLE001 - a task failure must never crash the service
        log.exception("task_failed", extra={"task_id": str(record.task_id)})
        record.error = f"{type(e).__name__}: {e}"
        record.touch(TaskStatus.failed)
    log.info(
        "task_finished",
        extra={
            "task_id": str(record.task_id),
            "status": record.status.value,
            "tokens": record.usage.total_tokens,
        },
    )
    return record


@dataclass
class ServiceConfig:
    repos_root: Path
    timeout_s: float = 300.0
    keep_workspaces: bool = False


class TaskService:
    def __init__(self, config: ServiceConfig, runner: CodingRunner, audit: AuditLog):
        self.config = config
        self.runner = runner
        self.audit = audit
        self._tasks: dict[UUID, TaskRecord] = {}
        self._by_idempotency_key: dict[str, UUID] = {}
        self._running: set[asyncio.Task] = set()  # keep references so tasks aren't GC'd

    def repo_path(self, name: str) -> Path:
        root = self.config.repos_root.resolve()
        path = (root / name).resolve()
        if not path.is_relative_to(root) or path == root or not path.is_dir():
            raise WorkspaceError(f"unknown repo: {name}")
        return path

    def get(self, task_id: UUID) -> TaskRecord | None:
        return self._tasks.get(task_id)

    def submit(self, request: TaskRequest, idempotency_key: str | None = None) -> TaskRecord:
        """Validate, record and start a task; returns immediately (status=queued)."""
        if idempotency_key and idempotency_key in self._by_idempotency_key:
            return self._tasks[self._by_idempotency_key[idempotency_key]]
        source = self.repo_path(request.repo)  # fail fast on bad repo names
        record = TaskRecord(request=request)
        self._tasks[record.task_id] = record
        if idempotency_key:
            self._by_idempotency_key[idempotency_key] = record.task_id
        t = asyncio.create_task(self._run(record, source))
        self._running.add(t)
        t.add_done_callback(self._running.discard)
        return record

    async def _run(self, record: TaskRecord, source: Path) -> None:
        try:
            ws = Workspace.create(source, str(record.task_id))
        except Exception as e:  # noqa: BLE001
            record.error = f"workspace setup failed: {e}"
            record.touch(TaskStatus.failed)
            return
        try:
            await execute_task(record, ws, self.runner, self.audit, self.config.timeout_s)
        finally:
            if not self.config.keep_workspaces:
                ws.cleanup()

    async def drain(self) -> None:
        """Wait for in-flight tasks (used on shutdown and in tests)."""
        if self._running:
            await asyncio.gather(*self._running, return_exceptions=True)
