"""Tests for persisted asynchronous benchmark run history."""

from __future__ import annotations

import json
from pathlib import Path

from lightrag.evaluation.run_history import (
    complete_run,
    create_run,
    fail_run,
    get_run,
    list_runs,
    mark_run_running,
    recover_interrupted_runs,
    update_run_metadata,
)


def _result() -> dict:
    return {
        "benchmark": {"id": "demo", "name": "Demo", "case_count": 1},
        "run": {"mode": "graph", "generated_at": "2026-09-28T12:00:00+00:00"},
        "scores": {"overall": 84.5, "graph": 90.0},
        "summary": {},
        "cases": {"graph": [], "query": []},
        "quality_gates": {"configured": True, "passed": True, "checks": []},
        "failed_checks": ["one failed check"],
    }


def test_completed_run_is_listed_loaded_and_editable(tmp_path: Path):
    run = create_run(
        tmp_path,
        benchmark_id="demo",
        benchmark_name="Demo benchmark",
        case_count=3,
        mode="graph",
        title="Baseline graph",
        note="Before prompt changes",
    )

    assert run["status"] == "queued"
    assert mark_run_running(tmp_path, run["id"])["status"] == "running"
    completed = complete_run(tmp_path, run["id"], _result())

    assert completed["status"] == "completed"
    assert completed["scores"]["overall"] == 84.5
    assert completed["quality_gates_passed"] is True
    assert completed["failed_check_count"] == 1

    runs, total = list_runs(tmp_path, benchmark_id="demo")
    assert total == 1
    assert runs[0]["id"] == run["id"]
    assert runs[0]["note"] == "Before prompt changes"

    updated = update_run_metadata(
        tmp_path,
        run["id"],
        title="Baseline graph after review",
        note="Prompt version 2",
    )
    detail = get_run(tmp_path, run["id"])

    assert updated["title"] == "Baseline graph after review"
    assert detail["run"]["note"] == "Prompt version 2"
    assert detail["result"]["run"]["title"] == "Baseline graph after review"
    assert detail["result"]["scores"]["overall"] == 84.5


def test_failed_and_interrupted_runs_preserve_their_error(tmp_path: Path):
    failed = create_run(
        tmp_path,
        benchmark_id="demo",
        benchmark_name="Demo",
        case_count=1,
        mode="retrieval",
    )
    failure = fail_run(tmp_path, failed["id"], "Provider was unavailable")

    interrupted = create_run(
        tmp_path,
        benchmark_id="demo",
        benchmark_name="Demo",
        case_count=1,
        mode="full",
    )
    assert recover_interrupted_runs(tmp_path) == 1

    failed_detail = get_run(tmp_path, failed["id"])
    interrupted_detail = get_run(tmp_path, interrupted["id"])

    assert failure["status"] == "failed"
    assert failed_detail["run"]["error"] == "Provider was unavailable"
    assert interrupted_detail["run"]["status"] == "interrupted"
    assert "stopped" in interrupted_detail["run"]["error"]


def test_legacy_result_is_listed_and_migrates_when_edited(tmp_path: Path):
    legacy_result = _result()
    legacy_result["benchmark"] = {
        "id": "legacy-demo",
        "name": "Legacy demo",
        "case_count": 1,
    }
    legacy_path = tmp_path / "evaluation_runs" / "20260928_legacy-demo.json"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text(json.dumps(legacy_result), encoding="utf-8")

    runs, total = list_runs(tmp_path)
    assert total == 1
    assert runs[0]["id"].startswith("legacy_")

    migrated = update_run_metadata(
        tmp_path,
        runs[0]["id"],
        title="Imported legacy run",
        note="Created before run history",
    )
    all_runs, total = list_runs(tmp_path)

    assert migrated["id"].startswith("2026")
    assert migrated["title"] == "Imported legacy run"
    assert total == 1
    assert all_runs[0]["id"] == migrated["id"]
    assert get_run(tmp_path, migrated["id"])["result"]["scores"]["graph"] == 90.0


def test_run_title_and_note_are_validated(tmp_path: Path):
    try:
        create_run(
            tmp_path,
            benchmark_id="demo",
            benchmark_name="Demo",
            case_count=1,
            mode="graph",
            title="   ",
        )
    except ValueError as exc:
        assert "must not be empty" in str(exc)
    else:
        raise AssertionError("An empty run title must be rejected")
