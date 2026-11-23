import os

import pytest

from engassist.workspace import MAX_FILE_BYTES, Workspace, WorkspaceError, redact


@pytest.fixture
def ws(tmp_path):
    src = tmp_path / "src"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "mod.py").write_text("def f():\n    return 1\n")
    (src / "README.md").write_text("# demo\n")
    (src / ".git").mkdir()
    (src / ".git" / "config").write_text("secret")
    (src / ".env").write_text("OPENAI_API_KEY=sk-should-not-copy")
    w = Workspace.create(src, "t1")
    yield w
    w.cleanup()


def test_copy_excludes_git_and_env(ws):
    files = ws.list_files()
    assert files == ["README.md", "pkg/mod.py"]
    assert not (ws.root / ".git").exists() and not (ws.root / ".env").exists()


@pytest.mark.parametrize(
    "bad",
    ["/etc/passwd", "../outside.py", "pkg/../../x.py", "", ".git/config", ".env", "pkg/.env.local"],
)
def test_rejects_unsafe_paths(ws, bad):
    with pytest.raises(WorkspaceError):
        ws.resolve(bad)


def test_rejects_symlink_escape(ws, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    os.symlink(secret, ws.root / "link.txt")
    with pytest.raises(WorkspaceError, match="escapes"):
        ws.read_file("link.txt")


def test_write_rules(ws):
    assert ws.write_file("pkg/new.py", "x = 1\n").startswith("created")
    assert ws.write_file("pkg/new.py", "x = 2\n").startswith("updated")
    with pytest.raises(WorkspaceError, match="not allowed"):
        ws.write_file("run.sh", "rm -rf /")
    with pytest.raises(WorkspaceError, match="too large"):
        ws.write_file("big.py", "x" * (MAX_FILE_BYTES + 1))


def test_search_is_literal(ws):
    assert ws.search_code("return 1") == ["pkg/mod.py:2: return 1"]
    assert ws.search_code("(a+)+$") == []  # regex metacharacters are just text
    with pytest.raises(WorkspaceError):
        ws.search_code("x", glob="../*.py")


def test_diff_and_hash(ws):
    assert ws.diff().files_changed == []
    ws.write_file("pkg/mod.py", "def f():\n    return 2\n")
    ws.write_file("pkg/added.py", "y = 1\n")
    change = ws.diff()
    assert change.files_changed == ["pkg/added.py", "pkg/mod.py"]
    assert "-    return 1" in change.diff and "+    return 2" in change.diff
    assert "--- /dev/null" in change.diff
    assert len(change.diff_sha256) == 64
    assert ws.diff().diff_sha256 == change.diff_sha256  # deterministic


def test_cleanup(tmp_path):
    (tmp_path / "s").mkdir()
    w = Workspace.create(tmp_path / "s")
    w.cleanup()
    assert not w.root.exists()


def test_redact():
    assert redact("key sk-abcdefghijklmnop and ghp_abcdefghijkl") == "key [REDACTED] and [REDACTED]"
