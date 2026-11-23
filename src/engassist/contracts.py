"""Typed contracts: the system's internal API.

Agents never hand each other free text; every hand-over is one of these models, validated on
the way out of one component and into the next. Phase 1 uses the coding-related subset; the
rest of the contracts from docs/ARCHITECTURE.md are added in the phase that needs them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


class TaskStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"  # agent finished and produced a non-empty diff
    no_change = "no_change"  # agent finished but changed nothing
    failed = "failed"


class TaskRequest(BaseModel):
    """What a client submits. `repo` is a NAME under the server's repos root, never a path,
    so a client cannot point the agent at arbitrary directories on the server."""

    repo: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.\-]+$")
    issue: str = Field(min_length=10, max_length=20_000)
    title: str | None = Field(default=None, max_length=200)

    @field_validator("repo")
    @classmethod
    def _no_dots_only(cls, v: str) -> str:
        if set(v) <= {"."}:
            raise ValueError("invalid repo name")
        return v


class CodingResult(BaseModel):
    """Structured final output the Coding agent must return (the SDK enforces this schema)."""

    summary: str = Field(description="One or two sentences: what was wrong and what you changed.")
    files_changed: list[str] = Field(description="Repository-relative paths you modified.")
    # No defaults here on purpose: structured-output "strict" JSON schemas require every field.
    risks: list[str] = Field(
        description="Anything a reviewer should double-check (edge cases, assumptions). "
        "Empty list if none.",
    )


class CodeChange(BaseModel):
    """The diff is computed by us from the workspace, never trusted from the model's claims."""

    diff: str
    diff_sha256: str  # approvals (phase 5) are bound to this hash
    files_changed: list[str]


class Usage(BaseModel):
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class AgentOutcome(BaseModel):
    result: CodingResult
    usage: Usage = Field(default_factory=Usage)


class TaskRecord(BaseModel):
    task_id: UUID = Field(default_factory=uuid4)
    status: TaskStatus = TaskStatus.queued
    request: TaskRequest
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    summary: str | None = None
    risks: list[str] = Field(default_factory=list)
    change: CodeChange | None = None
    usage: Usage = Field(default_factory=Usage)
    error: str | None = None

    def touch(self, status: TaskStatus | None = None) -> None:
        if status is not None:
            self.status = status
        self.updated_at = utcnow()
