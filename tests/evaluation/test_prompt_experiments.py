from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lightrag.evaluation.prompt_experiments import (
    _cancel_unfinished_candidates,
    _estimate_for_profile,
    _serialise_chunk_results,
    deserialise_chunk_results,
    list_prompt_experiments,
    list_prompt_profiles,
    recover_interrupted_prompt_experiments,
    save_prompt_experiment,
    source_fingerprint,
)


_original_argv = sys.argv[:]
sys.argv = [sys.argv[0]]
_evaluation_routes = importlib.import_module("lightrag.api.routers.evaluation_routes")
sys.argv = _original_argv

create_evaluation_routes = _evaluation_routes.create_evaluation_routes


@pytest.mark.offline
@pytest.mark.asyncio
async def test_candidate_merge_does_not_require_live_pipeline_status():
    """Prompt candidates merge into isolated workspaces without pipeline UI state."""

    from lightrag.operate import merge_nodes_and_edges

    await merge_nodes_and_edges(
        chunk_results=[],
        knowledge_graph_inst=object(),
        entity_vdb=object(),
        relationships_vdb=object(),
        global_config={"llm_model_max_async": 1},
        pipeline_status=None,
        pipeline_status_lock=None,
    )


def test_chunk_result_artifact_round_trip_preserves_tuple_edge_keys():
    original = [
        (
            {"ELECTRODE STACKING": [{"entity_type": "process", "source_id": "chunk-1"}]},
            {
                ("ELECTRODE STACKING", "ELECTRODE THICKNESS"): [
                    {"relation_type": "influences", "directionality": "directed"}
                ]
            },
        )
    ]

    restored = deserialise_chunk_results(_serialise_chunk_results(original))

    assert restored == original


def test_source_fingerprint_changes_when_retained_chunk_content_changes():
    chunks = {
        "chunk-1": {"content": "Electrode stacking changes thickness.", "tokens": 6, "full_doc_id": "doc-1"}
    }
    changed = {
        "chunk-1": {"content": "Electrode stacking improves thickness.", "tokens": 6, "full_doc_id": "doc-1"}
    }

    assert source_fingerprint(chunks) != source_fingerprint(changed)


def test_cost_estimate_accounts_for_profile_size_and_one_gleaning_pass(monkeypatch):
    monkeypatch.setenv("PROMPT_EXPERIMENT_SYSTEM_OVERHEAD_TOKENS", "100")
    monkeypatch.setenv("PROMPT_EXPERIMENT_ESTIMATED_OUTPUT_TOKENS", "20")
    monkeypatch.setenv("PROMPT_EXPERIMENT_INPUT_COST_PER_MILLION", "1")
    monkeypatch.setenv("PROMPT_EXPERIMENT_OUTPUT_COST_PER_MILLION", "2")
    profile = {
        "entity_types_guidance": "Battery manufacturing entities.",
        "entity_extraction_json_examples": ["{}"],
        "entity_extraction_examples": ["example"],
    }
    documents = [
        {
            "chunks": {
                "chunk-1": {"tokens": 100},
                "chunk-2": {"tokens": 50},
            }
        }
    ]

    without_gleaning = _estimate_for_profile(
        "compact.yml", profile, documents, max_gleaning=0
    )
    with_gleaning = _estimate_for_profile(
        "compact.yml", profile, documents, max_gleaning=1
    )

    assert without_gleaning["estimated_llm_calls"] == 2
    assert with_gleaning["estimated_llm_calls"] == 4
    assert with_gleaning["estimated_input_tokens"] == without_gleaning["estimated_input_tokens"] * 2
    assert with_gleaning["estimated_output_tokens"] == without_gleaning["estimated_output_tokens"] * 2
    assert with_gleaning["estimated_cost_usd"] > without_gleaning["estimated_cost_usd"]


def test_profile_listing_marks_the_active_file_and_skips_invalid_yaml(tmp_path, monkeypatch):
    prompt_dir = tmp_path / "prompts" / "entity_type"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "active.yml").write_text(
        """entity_types_guidance: Battery manufacturing entities.
entity_extraction_examples:
  - example
entity_extraction_json_examples:
  - '{}'
""",
        encoding="utf-8",
    )
    (prompt_dir / "invalid.yml").write_text("- not-a-mapping", encoding="utf-8")
    (prompt_dir / "wrong-mode.yml").write_text(
        """entity_types_guidance: Battery manufacturing entities.
entity_extraction_json_examples:
  - '{}'
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("PROMPT_DIR", str(tmp_path / "prompts"))

    class Rag:
        addon_params = {"entity_type_prompt_file": "active.yml"}

    profiles = list_prompt_profiles(Rag())

    assert [profile["file"] for profile in profiles] == ["active.yml"]
    assert profiles[0]["active"] is True
    assert profiles[0]["estimated_prompt_tokens"] > 0


def test_prompt_experiment_config_route_supports_lightweight_rag(tmp_path, monkeypatch):
    prompt_dir = tmp_path / "prompts" / "entity_type"
    prompt_dir.mkdir(parents=True)
    monkeypatch.setenv("PROMPT_DIR", str(tmp_path / "prompts"))
    monkeypatch.delenv("PROMPT_EXPERIMENTS_ENABLED", raising=False)
    rag = SimpleNamespace(working_dir=str(tmp_path / "rag_storage"), addon_params={})
    app = FastAPI()
    app.include_router(create_evaluation_routes(rag, "test-key"))

    with TestClient(app) as client:
        response = client.get(
            "/evaluation/prompt-experiments/config",
            headers={"X-API-Key": "test-key"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is False
    assert response.json()["active_extraction_revision"] is None
    assert response.json()["limits"] == {"max_documents": 20, "max_profiles": 5}


def test_recovery_marks_only_inflight_experiments_interrupted(tmp_path):
    running = {
        "id": "prompt_running",
        "status": "running",
        "created_at": "2026-01-01T00:00:00+00:00",
        "candidates": [{"status": "running"}, {"status": "completed"}],
    }
    complete = {
        "id": "prompt_complete",
        "status": "completed",
        "created_at": "2026-01-02T00:00:00+00:00",
        "candidates": [{"status": "completed"}],
    }
    save_prompt_experiment(tmp_path, running)
    save_prompt_experiment(tmp_path, complete)

    assert recover_interrupted_prompt_experiments(tmp_path) == 1
    manifests = {item["id"]: item for item in list_prompt_experiments(tmp_path)}
    assert manifests["prompt_running"]["status"] == "interrupted"
    assert manifests["prompt_running"]["candidates"][0]["status"] == "interrupted"
    assert manifests["prompt_complete"]["status"] == "completed"


def test_cancellation_moves_unfinished_candidates_to_terminal_state():
    manifest = {
        "candidates": [
            {"profile_file": "failed.yml", "status": "failed", "error": "boom"},
            {"profile_file": "running.yml", "status": "running", "error": None},
            {"profile_file": "queued.yml", "status": "queued", "error": None},
        ]
    }

    _cancel_unfinished_candidates(manifest)

    assert manifest["candidates"][0] == {
        "profile_file": "failed.yml",
        "status": "failed",
        "error": "boom",
    }
    assert manifest["candidates"][1]["status"] == "cancelled"
    assert manifest["candidates"][2]["status"] == "cancelled"
    assert manifest["candidates"][1]["error"] == "Cancelled by an operator."
    assert manifest["candidates"][2]["completed_at"]
