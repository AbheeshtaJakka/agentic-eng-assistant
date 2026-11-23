import json

import pytest

from engassist.audit import AuditLog
from engassist.contracts import CodingResult, TaskRequest
from engassist.tools import TaskContext, ToolBox
from engassist.workspace import Workspace


@pytest.fixture
def toolbox(tmp_path, practice_repo):
    ws = Workspace.create(practice_repo, "audit")
    audit = AuditLog(tmp_path / "audit.jsonl")
    yield ToolBox(TaskContext(task_id="task-1", workspace=ws, audit=audit)), audit
    ws.cleanup()


def test_errors_become_messages_not_exceptions(toolbox):
    tb, audit = toolbox
    assert tb.read_file("../../etc/passwd").startswith("ERROR:")
    assert tb.read_file("missing.py").startswith("ERROR: file not found")
    assert [r["status"] for r in audit.records] == ["rejected", "rejected"]


def test_every_call_is_audited_and_written(toolbox, tmp_path):
    tb, audit = toolbox
    assert "textkit/core.py" in tb.list_files()
    assert "def word_count" in tb.read_file("textkit/core.py")
    tb.write_file("textkit/extra.py", "token = 'sk-abcdefghijklmnopqrst'\n")
    lines = [json.loads(x) for x in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert [x["tool"] for x in lines] == ["list_files", "read_file", "write_file"]
    assert all(x["task_id"] == "task-1" and x["status"] == "ok" for x in lines)
    assert "content" not in lines[2]["args"]  # we log the size, never the file contents


def test_audit_redacts_secrets_in_args(tmp_path):
    audit = AuditLog(None)
    audit.record(
        task_id="t",
        agent="coding",
        tool="x",
        args={"q": "sk-abcdefghijklmnop"},
        status="ok",
        duration_ms=1,
    )
    assert audit.records[0]["args"]["q"] == "[REDACTED]"


def test_request_validation():
    with pytest.raises(ValueError):
        TaskRequest(repo="../etc", issue="something is broken here")
    with pytest.raises(ValueError):
        TaskRequest(repo="..", issue="something is broken here")
    assert TaskRequest(repo="practice_repo", issue="something is broken here")


def test_coding_result_schema_has_all_fields_required():
    # Strict structured outputs need every field required; guard against a future default.
    assert set(CodingResult.model_json_schema()["required"]) == {
        "summary",
        "files_changed",
        "risks",
    }
