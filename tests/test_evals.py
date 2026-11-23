"""The harness itself must be trustworthy: a correct fix passes, a non-fix fails."""

import asyncio

from conftest import EVALS, ScriptedRunner

from engassist.evals import load_tasks, run_eval, to_markdown


def test_golden_tasks_load():
    tasks = load_tasks(EVALS / "tasks")
    assert [t.id for t in tasks] == [
        "001-word-count-whitespace",
        "002-truncate-max-len",
        "003-add-slugify",
    ]
    for t in tasks:
        assert (EVALS / t.hidden_test).is_file()


def test_hidden_tests_fail_on_unfixed_repo():
    report = asyncio.run(run_eval(ScriptedRunner(writes={}), load_tasks(EVALS / "tasks"), EVALS))
    assert report["passed"] == 0
    assert {r["status"] for r in report["results"]} == {"no_change"}


def test_reference_fix_passes_every_task():
    report = asyncio.run(run_eval(ScriptedRunner(), load_tasks(EVALS / "tasks"), EVALS))
    assert report["completion_rate"] == 1.0, [r["test_output_tail"] for r in report["results"]]
    assert report["total_tokens"] == 3 * 1500
    assert "3/3" in to_markdown(report)


def test_agent_never_sees_hidden_tests():
    runner = ScriptedRunner(writes={})
    asyncio.run(run_eval(runner, load_tasks(EVALS / "tasks"), EVALS))
    for issue in runner.seen_issues:
        assert "hidden" not in issue.lower() and "_hidden_tests" not in issue
