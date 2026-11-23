import asyncio
import shutil

import pytest
from conftest import FailingRunner, ScriptedRunner, SlowRunner

from engassist.audit import AuditLog
from engassist.contracts import TaskRecord, TaskRequest, TaskStatus
from engassist.service import ServiceConfig, TaskService, execute_task
from engassist.workspace import Workspace, WorkspaceError

ISSUE = "word_count('') returns 1, expected 0"


@pytest.fixture
def repos_root(tmp_path, practice_repo):
    shutil.copytree(practice_repo, tmp_path / "practice_repo")
    return tmp_path


def _execute(runner, practice_repo, timeout=10):
    ws = Workspace.create(practice_repo)
    rec = TaskRecord(request=TaskRequest(repo="practice_repo", issue=ISSUE))
    try:
        return asyncio.run(execute_task(rec, ws, runner, AuditLog(None), timeout))
    finally:
        ws.cleanup()


def test_success_records_diff_and_usage(practice_repo):
    rec = _execute(ScriptedRunner(), practice_repo)
    assert rec.status is TaskStatus.succeeded
    assert rec.change.files_changed == ["textkit/__init__.py", "textkit/core.py"]
    assert rec.usage.total_tokens == 1500


def test_no_change_is_its_own_status(practice_repo):
    rec = _execute(ScriptedRunner(writes={}), practice_repo)
    assert rec.status is TaskStatus.no_change and rec.change is None


def test_runner_exception_becomes_failed_record(practice_repo):
    rec = _execute(FailingRunner(), practice_repo)
    assert rec.status is TaskStatus.failed
    assert "model provider unavailable" in rec.error


def test_timeout(practice_repo):
    rec = _execute(SlowRunner(), practice_repo, timeout=0.1)
    assert rec.status is TaskStatus.failed and "timed out" in rec.error


def test_original_repo_is_never_modified(practice_repo):
    before = (practice_repo / "textkit" / "core.py").read_text()
    _execute(ScriptedRunner(), practice_repo)
    assert (practice_repo / "textkit" / "core.py").read_text() == before


def test_service_submit_runs_in_background_and_cleans_up(repos_root):
    async def scenario():
        svc = TaskService(ServiceConfig(repos_root=repos_root), ScriptedRunner(), AuditLog(None))
        rec = svc.submit(TaskRequest(repo="practice_repo", issue=ISSUE))
        assert rec.status is TaskStatus.queued
        await svc.drain()
        return svc.get(rec.task_id)

    done = asyncio.run(scenario())
    assert done.status is TaskStatus.succeeded


def test_idempotency_key_returns_same_task(repos_root):
    async def scenario():
        runner = ScriptedRunner()
        svc = TaskService(ServiceConfig(repos_root=repos_root), runner, AuditLog(None))
        a = svc.submit(TaskRequest(repo="practice_repo", issue=ISSUE), "key-1")
        b = svc.submit(TaskRequest(repo="practice_repo", issue=ISSUE), "key-1")
        await svc.drain()
        return a, b, runner

    a, b, runner = asyncio.run(scenario())
    assert a.task_id == b.task_id and len(runner.seen_issues) == 1


@pytest.mark.parametrize("name", ["missing", "..", "practice_repo/../.."])
def test_unknown_or_escaping_repo_rejected(repos_root, name):
    svc = TaskService(ServiceConfig(repos_root=repos_root), ScriptedRunner(), AuditLog(None))
    with pytest.raises(WorkspaceError):
        svc.repo_path(name)
