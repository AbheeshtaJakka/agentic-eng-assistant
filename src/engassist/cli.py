"""CLI.

engassist run --repo ./path/to/repo --issue "word_count('') returns 1"
engassist eval                       # run the golden set in evals/
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from engassist.audit import AuditLog
from engassist.contracts import TaskRecord, TaskRequest


def _runner():
    from engassist.config import get_settings
    from engassist.specialists.coding import SdkCodingRunner

    s = get_settings()
    if not s.openai_api_key:
        sys.exit("OPENAI_API_KEY is not set (see .env.example)")
    return SdkCodingRunner(s.coding_model, s.max_turns, s.tracing_disabled), s


async def _run(args) -> int:
    from engassist.service import execute_task
    from engassist.workspace import Workspace

    runner, s = _runner()
    repo = Path(args.repo)
    issue = Path(args.issue[1:]).read_text() if args.issue.startswith("@") else args.issue
    ws = Workspace.create(repo, "cli")
    name = re.sub(r"[^A-Za-z0-9_.\-]", "-", repo.resolve().name).strip(".") or "repo"
    record = TaskRecord(request=TaskRequest(repo=name, issue=issue))
    try:
        await execute_task(record, ws, runner, AuditLog(s.audit_log_path), s.task_timeout_s)
        print(f"status: {record.status.value}   tokens: {record.usage.total_tokens:,}")
        if record.summary:
            print(f"summary: {record.summary}")
        for r in record.risks:
            print(f"risk: {r}")
        if record.error:
            print(f"error: {record.error}")
        if record.change:
            print("\n" + record.change.diff)
        if args.keep:
            print(f"workspace kept at: {ws.root}")
    finally:
        if not args.keep:
            ws.cleanup()
    return 0 if record.status.value in ("succeeded", "no_change") else 1


async def _eval(args) -> int:
    from engassist.evals import load_tasks, run_eval, to_markdown

    runner, s = _runner()
    evals_dir = Path(args.evals_dir)
    tasks = load_tasks(evals_dir / "tasks")
    if args.only:
        tasks = [t for t in tasks if t.id in args.only]
    report = await run_eval(runner, tasks, evals_dir, AuditLog(s.audit_log_path), s.task_timeout_s)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(to_markdown(report))
    print(f"\nfull report: {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="engassist")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="fix one issue in a local repo (works on a copy)")
    r.add_argument("--repo", required=True, help="path to a local repository")
    r.add_argument("--issue", required=True, help="issue text, or @file.md to read it from a file")
    r.add_argument("--keep", action="store_true", help="keep the workspace for inspection")

    e = sub.add_parser("eval", help="run the golden set")
    e.add_argument("--evals-dir", default="evals")
    e.add_argument("--only", nargs="*", help="task ids to run")
    e.add_argument("--out", default="evals/results/latest.json")

    args = p.parse_args(argv)
    return asyncio.run(_run(args) if args.cmd == "run" else _eval(args))


if __name__ == "__main__":
    raise SystemExit(main())
