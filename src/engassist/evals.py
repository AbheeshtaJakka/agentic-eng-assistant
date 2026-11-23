"""Eval harness: does the agent actually fix issues?

Each golden task = an issue on the practice repo + HIDDEN tests the agent never sees. After the
agent finishes, the hidden test file is copied into the workspace and run with pytest. Pass/fail
is objective; no LLM judge involved.

Phase 1 runs the hidden tests in a subprocess with a timeout and a stripped environment. That is
NOT a sandbox: the code under test was written by a model. Phase 4 moves this into a locked-down
container (no network, CPU/memory/time limits, read-only root, non-root user).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from engassist.audit import AuditLog
from engassist.contracts import TaskRecord, TaskRequest, TaskStatus
from engassist.service import CodingRunner, execute_task
from engassist.workspace import Workspace

HIDDEN_DIR = "_hidden_tests"


@dataclass
class EvalTask:
    id: str
    repo: str
    issue: str
    hidden_test: str  # path relative to the evals dir


@dataclass
class EvalResult:
    id: str
    passed: bool
    status: str
    seconds: float
    tokens: int = 0
    files_changed: list[str] = field(default_factory=list)
    error: str | None = None
    test_output_tail: str = ""


def load_tasks(tasks_dir: Path) -> list[EvalTask]:
    return [EvalTask(**json.loads(p.read_text())) for p in sorted(tasks_dir.glob("*.json"))]


def run_hidden_tests(ws: Workspace, hidden_test: Path, timeout_s: float = 60) -> tuple[bool, str]:
    dest = ws.root / HIDDEN_DIR / hidden_test.name
    dest.parent.mkdir(exist_ok=True)
    shutil.copy2(hidden_test, dest)
    env = {  # no API keys or other secrets reach model-written code
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(ws.root),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                f"{HIDDEN_DIR}/{hidden_test.name}",
            ],
            cwd=ws.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return False, f"hidden tests timed out after {timeout_s}s"
    out = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, out[-1500:]


async def run_eval(
    runner: CodingRunner,
    tasks: list[EvalTask],
    evals_dir: Path,
    audit: AuditLog | None = None,
    timeout_s: float = 300,
) -> dict:
    audit = audit or AuditLog(None)
    results: list[EvalResult] = []
    for t in tasks:
        t0 = time.perf_counter()
        ws = Workspace.create(evals_dir / t.repo, t.id)
        try:
            record = TaskRecord(request=TaskRequest(repo=t.repo, issue=t.issue))
            await execute_task(record, ws, runner, audit, timeout_s)
            passed, tail = False, ""
            if record.status in (TaskStatus.succeeded, TaskStatus.no_change):
                passed, tail = await asyncio.to_thread(
                    run_hidden_tests, ws, evals_dir / t.hidden_test
                )
            results.append(
                EvalResult(
                    id=t.id,
                    passed=passed,
                    status=record.status.value,
                    seconds=round(time.perf_counter() - t0, 1),
                    tokens=record.usage.total_tokens,
                    files_changed=record.change.files_changed if record.change else [],
                    error=record.error,
                    test_output_tail=tail,
                )
            )
        finally:
            ws.cleanup()

    n = len(results)
    return {
        "n": n,
        "passed": sum(r.passed for r in results),
        "completion_rate": round(sum(r.passed for r in results) / n, 3) if n else 0.0,
        "total_tokens": sum(r.tokens for r in results),
        "results": [asdict(r) for r in results],
    }


def to_markdown(report: dict) -> str:
    lines = [
        f"**Completion: {report['passed']}/{report['n']} "
        f"({report['completion_rate']:.0%})** · tokens: {report['total_tokens']:,}",
        "",
        "| Task | Result | Status | Seconds | Tokens | Files changed |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in report["results"]:
        lines.append(
            f"| {r['id']} | {'pass' if r['passed'] else 'FAIL'} | {r['status']} | "
            f"{r['seconds']} | {r['tokens']:,} | {', '.join(r['files_changed']) or '-'} |"
        )
    return "\n".join(lines)
