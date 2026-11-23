"""Isolated, path-confined workspace for one task.

The agent's tools can only touch files through this class, so this is the permission boundary
for phase 1. Every path is normalised and checked against the workspace root; symlinks that
point outside are rejected because we check the *resolved* path. A pristine copy of the repo
is kept alongside so we can compute the diff ourselves rather than trusting the model.

Phase 2 moves these operations behind an MCP server; the checks stay the same.
"""

from __future__ import annotations

import difflib
import hashlib
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from engassist.contracts import CodeChange

IGNORED = (
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "*.pyc",
    ".env",
    ".env.*",
)
DENIED_PARTS = {".git", ".env"}
WRITABLE_SUFFIXES = {".py", ".md", ".txt", ".toml", ".cfg", ".ini", ".json", ".yaml", ".yml"}
MAX_FILE_BYTES = 200_000
MAX_LIST_ENTRIES = 500
MAX_SEARCH_HITS = 50


class WorkspaceError(ValueError):
    """Raised for any rejected operation. Messages are safe to show to the model."""


class Workspace:
    def __init__(self, root: Path, base: Path, owns_tmp: Path | None = None):
        self.root = root.resolve()
        self.base = base.resolve()
        self._owns_tmp = owns_tmp

    # ---------- lifecycle ----------
    @classmethod
    def create(cls, source: Path, task_id: str = "task") -> Workspace:
        source = source.resolve()
        if not source.is_dir():
            raise WorkspaceError(f"source repo not found: {source}")
        tmp = Path(tempfile.mkdtemp(prefix=f"engassist-{task_id[:8]}-"))
        ignore = shutil.ignore_patterns(*IGNORED)
        shutil.copytree(source, tmp / "base", ignore=ignore, symlinks=True)
        shutil.copytree(source, tmp / "repo", ignore=ignore, symlinks=True)
        return cls(tmp / "repo", tmp / "base", owns_tmp=tmp)

    def cleanup(self) -> None:
        if self._owns_tmp and self._owns_tmp.exists():
            shutil.rmtree(self._owns_tmp, ignore_errors=True)

    # ---------- path safety ----------
    def resolve(self, rel: str) -> Path:
        if not rel or not rel.strip():
            raise WorkspaceError("path is empty")
        rel = rel.strip().replace("\\", "/")
        pure = PurePosixPath(rel)
        if pure.is_absolute():
            raise WorkspaceError("absolute paths are not allowed; use a repository-relative path")
        if ".." in pure.parts:
            raise WorkspaceError("'..' is not allowed in paths")
        if any(p in DENIED_PARTS or p.startswith(".env") for p in pure.parts):
            raise WorkspaceError(f"access to '{rel}' is not allowed")
        candidate = (self.root / pure).resolve()
        if candidate != self.root and not candidate.is_relative_to(self.root):
            raise WorkspaceError("path escapes the workspace")
        return candidate

    def _rel(self, p: Path) -> str:
        return p.relative_to(self.root).as_posix()

    # ---------- tool operations ----------
    def list_files(self, subdir: str = "") -> list[str]:
        start = self.resolve(subdir) if subdir else self.root
        if not start.is_dir():
            raise WorkspaceError(f"not a directory: {subdir}")
        out: list[str] = []
        for p in sorted(start.rglob("*")):
            if p.is_file() and not p.is_symlink():
                rel = self._rel(p)
                if not any(part in DENIED_PARTS for part in PurePosixPath(rel).parts):
                    out.append(rel)
            if len(out) >= MAX_LIST_ENTRIES:
                out.append(f"... truncated at {MAX_LIST_ENTRIES} entries")
                break
        return out

    def read_file(self, rel: str) -> str:
        p = self.resolve(rel)
        if not p.is_file():
            raise WorkspaceError(f"file not found: {rel}")
        if p.stat().st_size > MAX_FILE_BYTES:
            raise WorkspaceError(f"file too large to read (> {MAX_FILE_BYTES} bytes): {rel}")
        try:
            return p.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise WorkspaceError(f"not a UTF-8 text file: {rel}") from e

    def write_file(self, rel: str, content: str) -> str:
        p = self.resolve(rel)
        if p.suffix.lower() not in WRITABLE_SUFFIXES:
            raise WorkspaceError(
                f"writing '{p.suffix or 'no extension'}' files is not allowed; "
                f"allowed: {sorted(WRITABLE_SUFFIXES)}"
            )
        data = content.encode("utf-8")
        if len(data) > MAX_FILE_BYTES:
            raise WorkspaceError(f"content too large (> {MAX_FILE_BYTES} bytes)")
        if p.is_symlink():
            raise WorkspaceError("refusing to write through a symlink")
        p.parent.mkdir(parents=True, exist_ok=True)
        existed = p.exists()
        p.write_bytes(data)
        return f"{'updated' if existed else 'created'} {self._rel(p)} ({len(data)} bytes)"

    def search_code(self, query: str, glob: str = "*.py") -> list[str]:
        """Case-sensitive literal search. Literal (not regex) avoids ReDoS from model input."""
        if not query:
            raise WorkspaceError("query is empty")
        if "/" in glob or ".." in glob:
            raise WorkspaceError("glob must be a file-name pattern like '*.py'")
        hits: list[str] = []
        for p in sorted(self.root.rglob(glob)):
            if not p.is_file() or p.is_symlink() or p.stat().st_size > MAX_FILE_BYTES:
                continue
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for n, line in enumerate(lines, 1):
                if query in line:
                    hits.append(f"{self._rel(p)}:{n}: {line.strip()[:200]}")
                    if len(hits) >= MAX_SEARCH_HITS:
                        return [*hits, f"... truncated at {MAX_SEARCH_HITS} hits"]
        return hits

    # ---------- diff ----------
    def diff(self) -> CodeChange:
        def text_files(root: Path) -> dict[str, str]:
            files = {}
            for p in root.rglob("*"):
                if p.is_file() and not p.is_symlink() and "__pycache__" not in p.parts:
                    try:
                        files[p.relative_to(root).as_posix()] = p.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        continue
            return files

        before, after = text_files(self.base), text_files(self.root)
        chunks, changed = [], []
        for rel in sorted(before.keys() | after.keys()):
            a, b = before.get(rel), after.get(rel)
            if a == b:
                continue
            changed.append(rel)
            chunks.extend(
                difflib.unified_diff(
                    (a or "").splitlines(keepends=True),
                    (b or "").splitlines(keepends=True),
                    fromfile=f"a/{rel}" if a is not None else "/dev/null",
                    tofile=f"b/{rel}" if b is not None else "/dev/null",
                )
            )
        diff = "".join(c if c.endswith("\n") else c + "\n" for c in chunks)
        return CodeChange(
            diff=diff,
            diff_sha256=hashlib.sha256(diff.encode()).hexdigest(),
            files_changed=changed,
        )


_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|ghp_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,})")


def redact(text: str) -> str:
    """Mask things that look like API keys / tokens before they reach logs."""
    return _SECRET_RE.sub("[REDACTED]", text)
