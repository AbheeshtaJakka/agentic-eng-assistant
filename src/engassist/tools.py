"""Framework-free tool implementations.

Each method is what one agent tool does: validate via the Workspace, audit the call, and turn
rejections into a plain-text error the model can read and recover from (instead of crashing
the run). The Agents SDK wrappers in `agents/coding.py` are one-liners over these, which keeps
all the logic testable without a model or the SDK installed.
"""

from __future__ import annotations

from dataclasses import dataclass

from engassist.audit import AuditLog
from engassist.workspace import Workspace, WorkspaceError


@dataclass
class TaskContext:
    """Local run context handed to every tool. Never sent to the model."""

    task_id: str
    workspace: Workspace
    audit: AuditLog
    agent: str = "coding"


class ToolBox:
    def __init__(self, ctx: TaskContext):
        self.ctx = ctx

    def _run(self, tool: str, args: dict, fn) -> str:
        with self.ctx.audit.timed(
            task_id=self.ctx.task_id, agent=self.ctx.agent, tool=tool, args=args
        ) as done:
            try:
                out = fn()
            except WorkspaceError as e:
                done("rejected", str(e))
                return f"ERROR: {e}"
            done("ok")
            return out

    def list_files(self, subdir: str = "") -> str:
        return self._run(
            "list_files",
            {"subdir": subdir},
            lambda: "\n".join(self.ctx.workspace.list_files(subdir)) or "(empty)",
        )

    def read_file(self, path: str) -> str:
        return self._run("read_file", {"path": path}, lambda: self.ctx.workspace.read_file(path))

    def search_code(self, query: str, glob: str = "*.py") -> str:
        return self._run(
            "search_code",
            {"query": query, "glob": glob},
            lambda: "\n".join(self.ctx.workspace.search_code(query, glob)) or "(no matches)",
        )

    def write_file(self, path: str, content: str) -> str:
        return self._run(
            "write_file",
            {"path": path, "bytes": len(content.encode())},
            lambda: self.ctx.workspace.write_file(path, content),
        )
