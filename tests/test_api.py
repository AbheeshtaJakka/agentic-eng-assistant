import shutil
import time

import pytest

fastapi = pytest.importorskip("fastapi")
from conftest import ScriptedRunner  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from engassist.api import create_app  # noqa: E402
from engassist.audit import AuditLog  # noqa: E402
from engassist.service import ServiceConfig, TaskService  # noqa: E402

BODY = {"repo": "practice_repo", "issue": "word_count('') returns 1, expected 0"}


@pytest.fixture
def client(tmp_path, practice_repo):
    shutil.copytree(practice_repo, tmp_path / "practice_repo")
    svc = TaskService(ServiceConfig(repos_root=tmp_path), ScriptedRunner(), AuditLog(None))
    with TestClient(create_app(svc)) as c:
        yield c


def _wait(client, task_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/tasks/{task_id}").json()
        if body["status"] not in ("queued", "running"):
            return body
        time.sleep(0.05)
    raise AssertionError("task did not finish")


def test_submit_and_poll(client):
    r = client.post("/tasks", json=BODY)
    assert r.status_code == 202 and r.json()["status"] == "queued"
    done = _wait(client, r.json()["task_id"])
    assert done["status"] == "succeeded"
    assert "textkit/core.py" in done["change"]["files_changed"]


def test_idempotency_header(client):
    a = client.post("/tasks", json=BODY, headers={"Idempotency-Key": "abc"}).json()
    b = client.post("/tasks", json=BODY, headers={"Idempotency-Key": "abc"}).json()
    assert a["task_id"] == b["task_id"]


def test_validation_and_not_found(client):
    assert client.post("/tasks", json={**BODY, "repo": "../etc"}).status_code == 422
    assert client.post("/tasks", json={**BODY, "repo": "nope"}).status_code == 404
    assert client.get("/tasks/00000000-0000-0000-0000-000000000000").status_code == 404
    assert client.get("/health").json() == {"status": "ok"}
