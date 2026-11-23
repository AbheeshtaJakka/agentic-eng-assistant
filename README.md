# Agentic Engineering Assistant

A production-style multi-agent system that turns a GitHub issue into a reviewed, tested pull
request, with a human approving every write.

**Status: phase 1 of 8.** A single Coding agent (OpenAI Agents SDK) fixes issues in an isolated
copy of a repository, behind a FastAPI service, with an audit log and an objective eval harness.
The full target design (LangGraph workflow, five agents, MCP servers, sandboxed tests, memory,
approvals) is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## What works today

```bash
engassist run --repo evals/practice_repo \
  --issue "word_count('') returns 1, expected 0; multiple spaces count as extra words"
```
It prints the task status, token usage, the agent's summary and risks, and the unified diff it
produced. The original repo is untouched; pass `--keep` to inspect the modified copy.

- **Coding agent** with four tools (`list_files`, `read_file`, `search_code`, `write_file`) and
  a typed `CodingResult` output enforced by the SDK.
- **Isolated workspaces:** every task works on a temporary copy; the source repo is never modified.
- **Path-confined tools:** absolute paths, `..`, symlink escapes, `.git` and `.env` are rejected;
  writes are limited to text file types and 200 KB. Rejections come back to the model as
  `ERROR: ...` so it can recover instead of crashing the run.
- **We compute the diff ourselves** from the workspace (plus its SHA-256, which later binds
  approvals), never trusting the model's claims about what it changed.
- **Audit log:** every tool call recorded as JSON Lines with redacted arguments, status and timing.
- **API:** `POST /tasks` (202, `Idempotency-Key` supported), `GET /tasks/{id}`, `GET /health`.
  Clients name a repo under `REPOS_ROOT`; they can't pass server paths.
- **Tracing:** Agents SDK traces grouped per task id.
- **Evals:** golden issues with **hidden tests** the agent never sees, scored pass/fail.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
make install
cp .env.example .env            # add OPENAI_API_KEY
make test                       # no API key needed: uses a scripted fake agent

engassist run --repo evals/practice_repo --issue @issue.md   # one issue, prints the diff
engassist eval                                               # the golden set

make serve                      # API on :8000, docs at /docs
curl -s localhost:8000/tasks -H 'content-type: application/json' \
  -d '{"repo": "practice_repo", "issue": "truncate() returns strings longer than max_len"}'
```

Or with Docker: `make up`.

## Evaluation

Each golden task is an issue on `evals/practice_repo` plus a hidden pytest file. After the agent
finishes, the hidden tests are copied in and run; the task passes only if they pass. The harness
is itself tested: the unfixed repo scores 0/3 and a reference fix scores 3/3.

| Task | What it tests |
| --- | --- |
| 001 word-count whitespace | Bug fix with edge cases (empty string, tabs, newlines) |
| 002 truncate max length | Off-by-suffix bug, plus an edge case stated only in prose |
| 003 add slugify | New feature that must also be exported from the package |

Results: _run `engassist eval` and paste the table here._ The golden set grows to 20–30 tasks
in phase 8, split into a dev set and a held-out test set.

> **Known limitation (phase 1):** hidden tests run in a subprocess with a timeout and a stripped
> environment, not in a real sandbox. Model-written code is untrusted; phase 4 moves execution
> into a locked-down container (no network, resource limits, read-only root, non-root user).

## Project layout

```
src/engassist/
  contracts.py          Pydantic models: the internal API between components
  workspace.py          isolated, path-confined file operations + diff (the permission boundary)
  tools.py              tool logic + audit, framework-free and unit-tested
  specialists/coding.py the Coding agent: thin Agents SDK wrapper over tools.py
  service.py            execute_task() + in-memory async task service
  api.py                FastAPI app
  evals.py              golden-set harness with hidden tests
  audit.py, config.py, observability.py, cli.py
evals/                  practice repo, task definitions, hidden tests
tests/                  unit, service, eval-harness and API tests (scripted fake agent)
docs/ARCHITECTURE.md    target design, security model, decisions
```

## Roadmap

- [x] **1. One agent:** Coding agent, isolated workspaces, audit log, API, CLI, tracing, golden-set harness
- [ ] **2. MCP servers:** `repo` and `knowledge` servers; tools move behind MCP with per-agent allowlists
- [ ] **3. LangGraph workflow:** Triage → Research → Coding → Review → Testing; Postgres checkpoints; Redis queue + workers; resume after crash
- [ ] **4. Sandboxed testing:** locked-down container per test run; bounded retry loops
- [ ] **5. Approvals:** diff-hash-bound human approval before opening a PR; audit log in Postgres *(interview-ready milestone)*
- [ ] **6. Memory:** episodic memory in pgvector, context budgets, summarization
- [ ] **7. Optimization:** model routing, semantic cache, rate limits, fallbacks, cost per task
- [ ] **8. Evals + deploy:** 20–30 task golden set, calibrated LLM judge, single-agent baseline, LangSmith, AWS (ECS Fargate, RDS, ElastiCache)

## Design decisions

- **Logic outside the framework.** Tools, workspace safety, diffs and evals are plain Python with
  unit tests; the Agents SDK layer is a thin adapter. Frameworks change fast; the core shouldn't.
- **Errors are data for the model.** A rejected tool call returns `ERROR: ...` text, so the agent
  can correct course; only infrastructure failures fail the task.
- **Objective evals first.** Hidden tests decide pass/fail before any LLM-as-judge is added.
- **Every framework gets one job** (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#key-decisions)).
