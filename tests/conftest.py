"""Shared fixtures: fake agents that act through the real ToolBox (so tool guards and the
audit log are exercised) without calling a model."""

from __future__ import annotations

from pathlib import Path

import pytest

from engassist.contracts import AgentOutcome, CodingResult, Usage
from engassist.tools import TaskContext, ToolBox

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"

FIXED_CORE = '''"""Core text helpers."""

import re


def word_count(text: str) -> int:
    """Return the number of words in `text`."""
    return len(text.split())


def truncate(text: str, max_len: int, suffix: str = "...") -> str:
    """Shorten `text` so the result is at most `max_len` characters, ending with `suffix`
    when anything was cut."""
    if len(text) <= max_len:
        return text
    if max_len <= len(suffix):
        return suffix[:max_len]
    return text[: max_len - len(suffix)] + suffix


def slugify(text: str) -> str:
    """Lowercase, runs of non-alphanumerics become '-', no leading/trailing '-'."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
'''

FIXED_INIT = '''"""textkit: tiny text utilities. Practice repository for the eval golden set."""

from textkit.core import slugify, truncate, word_count

__all__ = ["slugify", "truncate", "word_count"]
'''


class ScriptedRunner:
    """Reads the file first (like a well-behaved agent), then writes the reference fix."""

    def __init__(self, writes: dict[str, str] | None = None, usage: Usage | None = None):
        self.writes = (
            writes
            if writes is not None
            else {"textkit/core.py": FIXED_CORE, "textkit/__init__.py": FIXED_INIT}
        )
        self.usage = usage or Usage(requests=3, input_tokens=1200, output_tokens=300)
        self.seen_issues: list[str] = []

    async def run(self, ctx: TaskContext, issue: str) -> AgentOutcome:
        self.seen_issues.append(issue)
        tb = ToolBox(ctx)
        changed = []
        for path, content in self.writes.items():
            tb.read_file(path)
            out = tb.write_file(path, content)
            if not out.startswith("ERROR"):
                changed.append(path)
        return AgentOutcome(
            result=CodingResult(summary="applied reference fix", files_changed=changed, risks=[]),
            usage=self.usage,
        )


class FailingRunner:
    async def run(self, ctx, issue):
        raise RuntimeError("model provider unavailable")


class SlowRunner:
    async def run(self, ctx, issue):
        import asyncio

        await asyncio.sleep(5)


@pytest.fixture
def practice_repo() -> Path:
    return EVALS / "practice_repo"
