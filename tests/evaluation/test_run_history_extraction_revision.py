from __future__ import annotations

from lightrag.evaluation.run_history import create_run, get_run, list_runs


def test_run_history_persists_extraction_revision(tmp_path):
    revision = {
        "version": "1.2.0",
        "fingerprint": "f" * 64,
        "prompt_profile": "pem-a.yml",
    }
    run = create_run(
        tmp_path,
        benchmark_id="benchmark",
        benchmark_name="Benchmark",
        case_count=2,
        mode="retrieval",
        extraction_revision=revision,
    )

    runs, total = list_runs(tmp_path)
    loaded = get_run(tmp_path, run["id"])

    assert total == 1
    assert runs[0]["extraction_revision"] == revision
    assert loaded["run"]["extraction_revision"] == revision
