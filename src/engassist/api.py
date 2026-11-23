"""FastAPI service.

  POST /tasks          submit an issue (202); optional Idempotency-Key header
  GET  /tasks/{id}     status, summary, diff, token usage
  GET  /health         liveness

Phase 5 adds POST /tasks/{id}/approvals; phase 3 adds an SSE events stream.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status

from engassist.contracts import TaskRecord, TaskRequest
from engassist.service import TaskService
from engassist.workspace import WorkspaceError


def _default_service() -> TaskService:
    from engassist.audit import AuditLog
    from engassist.config import get_settings
    from engassist.observability import setup_logging
    from engassist.service import ServiceConfig
    from engassist.specialists.coding import SdkCodingRunner

    s = get_settings()
    setup_logging(s.log_level)
    return TaskService(
        ServiceConfig(repos_root=s.repos_root, timeout_s=s.task_timeout_s),
        SdkCodingRunner(s.coding_model, s.max_turns, s.tracing_disabled),
        AuditLog(s.audit_log_path),
    )


def create_app(service: TaskService | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.service = service or _default_service()
        yield
        await app.state.service.drain()

    app = FastAPI(title="Agentic Engineering Assistant", version="0.1.0", lifespan=lifespan)

    def get_service(request: Request) -> TaskService:
        return request.app.state.service

    Svc = Annotated[TaskService, Depends(get_service)]

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/tasks", response_model=TaskRecord, status_code=status.HTTP_202_ACCEPTED)
    async def submit(
        req: TaskRequest,
        svc: Svc,
        idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
    ):
        try:
            return svc.submit(req, idempotency_key)
        except WorkspaceError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e

    @app.get("/tasks/{task_id}", response_model=TaskRecord)
    def get_task(task_id: UUID, svc: Svc):
        rec = svc.get(task_id)
        if rec is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
        return rec

    return app


app = create_app()
