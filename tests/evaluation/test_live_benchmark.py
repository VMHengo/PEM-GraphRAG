import asyncio
import json
from pathlib import Path

from lightrag.evaluation.live_benchmark import (
    _directed_path_matches,
    evaluate_quality_gates,
    list_benchmarks,
    load_benchmark,
    run_live_benchmark,
    score_graph_cases,
)


def test_directed_path_match_can_require_resolved_source_citations():
    expected = {
        "nodes": ["Cause", "Effect"],
        "relation_types": ["causes"],
        "require_citations": True,
    }
    actual = {
        "nodes": ["Cause", "Effect"],
        "edges": [{"relation_type": "causes"}],
        "reference_ids": [],
    }

    matched, checks = _directed_path_matches(expected, actual)

    assert matched is False
    assert checks[-1]["kind"] == "source_citations"
    assert checks[-1]["passed"] is False


def test_quality_gates_report_a_failed_threshold():
    gates = evaluate_quality_gates(
        {"quality_gates": {"min_scores": {"directed": 90}}},
        scores={"directed": 80.0},
        graph_summary={"metadata_coverage": {}},
        directed_summary={"cases": 1, "strategies": {}},
        failed_checks=[],
    )

    assert gates["configured"] is True
    assert gates["passed"] is False
    assert gates["checks"] == [
        {
            "kind": "min_score:directed",
            "expected": 90.0,
            "actual": 80.0,
            "passed": False,
        }
    ]


def test_graph_case_scores_directed_relation_metadata():
    benchmark = {
        "cases": [
            {
                "id": "chain",
                "question": "What caused the defect?",
                "expected_entities": [
                    "Electrode Stacking",
                    "Electrode Thickness",
                    "Coating Defect",
                ],
                "expected_relations": [
                    {
                        "source": "Electrode Stacking",
                        "relation_type": "influences",
                        "target": "Electrode Thickness",
                        "directionality": "directed",
                    },
                    {
                        "source": "Insufficient Electrode Thickness",
                        "relation_type": "causes",
                        "target": "Coating Defect",
                        "directionality": "directed",
                    },
                ],
            }
        ]
    }
    nodes = [
        {"entity_id": "Electrode Stacking"},
        {"entity_id": "Electrode Thickness"},
        {"entity_id": "Coating Defect"},
    ]
    edges = [
        {
            "source": "Electrode Stacking",
            "target": "Electrode Thickness",
            "semantic_src_id": "Electrode Stacking",
            "semantic_tgt_id": "Electrode Thickness",
            "relation_type": "influences",
            "directionality": "directed",
            "relation_importance": 0.91,
            "chain_role": "process_parameter",
        },
        {
            "source": "Insufficient Electrode Thickness",
            "target": "Coating Defect",
            "semantic_src_id": "Insufficient Electrode Thickness",
            "semantic_tgt_id": "Coating Defect",
            "relation_type": "causes",
            "directionality": "directed",
            "relation_importance": 0.95,
            "chain_role": "root_cause",
        },
    ]

    results, summary = score_graph_cases(benchmark, nodes, edges)

    assert results[0]["entity_score"] == 100.0
    assert results[0]["relation_score"] == 100.0
    assert summary["metadata_coverage"]["directionality"] == 100.0
    assert summary["metadata_coverage"]["relation_type"] == 100.0
    assert summary["metadata_coverage"]["chain_role"] == 100.0


def test_benchmark_discovery_uses_working_dir_data_folder(tmp_path, monkeypatch):
    benchmark_dir = tmp_path / "evaluation" / "benchmarks"
    benchmark_dir.mkdir(parents=True)
    benchmark_file = benchmark_dir / "demo.json"
    benchmark_file.write_text(
        json.dumps(
            {
                "id": "demo",
                "name": "Demo",
                "description": "Demo benchmark",
                "cases": [{"id": "case", "question": "What is tested?"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EVALUATION_BENCHMARK_DIR", str(benchmark_dir))

    refs = list_benchmarks(str(tmp_path / "rag_storage"))
    benchmark = load_benchmark("demo", str(tmp_path / "rag_storage"))

    assert any(ref.id == "demo" for ref in refs)
    assert benchmark["name"] == "Demo"


class _FakeGraph:
    async def get_all_nodes(self):
        return [{"entity_id": "Laser-Based Drying"}, {"entity_id": "Electrode Drying"}]

    async def get_all_edges(self):
        return [
            {
                "source": "Laser-Based Drying",
                "target": "Electrode Drying",
                "semantic_src_id": "Laser-Based Drying",
                "semantic_tgt_id": "Electrode Drying",
                "relation_type": "optimizes",
                "directionality": "directed",
                "relation_importance": 0.9,
                "chain_role": "process_optimization",
            }
        ]


class _FakeRag:
    def __init__(self, working_dir: Path):
        self.working_dir = str(working_dir)
        self.chunk_entity_relation_graph = _FakeGraph()


class _DirectedFakeRag(_FakeRag):
    def __init__(self, working_dir: Path):
        super().__init__(working_dir)
        self.strategies: list[str] = []

    async def aquery_llm(self, query, param):
        self.strategies.append(param.retrieval_strategy)
        effective_strategy = (
            "combined" if param.retrieval_strategy == "auto" else param.retrieval_strategy
        )
        diagnostics = {
            "status": "skipped",
            "reason": "strategy_normal",
            "path_count": 0,
            "paths": [],
        }
        route = {
            "effective_strategy": effective_strategy,
            "edge_direction": "in",
        }
        if param.retrieval_strategy != "normal":
            diagnostics = {
                "status": "completed",
                "reason": "paths_found",
                "path_count": 1,
                "paths": [
                    {
                        "nodes": ["Defect X", "Uneven Coating", "Process Instability"],
                        "edges": [
                            {"relation_type": "causes"},
                            {"relation_type": "influences"},
                        ],
                        "file_paths": ["defects.pdf", "coating.pdf"],
                        "reference_ids": ["1", "2"],
                    }
                ],
            }
        return {
            "status": "success",
            "data": {"chunks": [], "references": []},
            "metadata": {
                "retrieval_route": route,
                "directed_paths": diagnostics,
            },
            "llm_response": {"content": ""},
        }


def test_run_live_benchmark_graph_mode(tmp_path, monkeypatch):
    benchmark_dir = tmp_path / "evaluation" / "benchmarks"
    benchmark_dir.mkdir(parents=True)
    (benchmark_dir / "laser.json").write_text(
        json.dumps(
            {
                "id": "laser",
                "name": "Laser",
                "cases": [
                    {
                        "id": "laser",
                        "question": "How does laser drying affect electrode drying?",
                        "expected_entities": ["Laser-Based Drying", "Electrode Drying"],
                        "expected_relations": [
                            {
                                "source": "Laser-Based Drying",
                                "relation_type": "optimizes",
                                "target": "Electrode Drying",
                                "directionality": "directed",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EVALUATION_BENCHMARK_DIR", str(benchmark_dir))
    rag = _FakeRag(tmp_path / "rag_storage")

    result = asyncio.run(
        run_live_benchmark(rag, "laser", mode="graph", save_result=True)
    )

    assert result["scores"]["graph"] == 100.0
    assert result["scores"]["retrieval"] is None
    assert result["failed_checks"] == []
    assert Path(result["run"]["saved_to"]).exists()


def test_run_live_benchmark_compares_normal_directed_and_combined_paths(
    tmp_path, monkeypatch
):
    benchmark_dir = tmp_path / "evaluation" / "benchmarks"
    benchmark_dir.mkdir(parents=True)
    (benchmark_dir / "directed.json").write_text(
        json.dumps(
            {
                "id": "directed",
                "name": "Directed",
                "quality_gates": {
                    "min_directed_strategy_scores": {"auto": 90},
                    "max_failed_checks": 0,
                    "require_directed_cases": True,
                },
                "cases": [],
                "directed_cases": [
                    {
                        "id": "root-cause",
                        "question": "What causes defect X?",
                        "expected_edge_direction": "in",
                        "expected_directed_paths": [
                            {
                                "traversal_nodes": [
                                    "Defect X",
                                    "Uneven Coating",
                                    "Process Instability",
                                ],
                                "relation_types": ["causes", "influences"],
                                "source_documents": ["defects.pdf"],
                                "require_citations": True,
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EVALUATION_BENCHMARK_DIR", str(benchmark_dir))
    rag = _DirectedFakeRag(tmp_path / "rag_storage")

    result = asyncio.run(
        run_live_benchmark(rag, "directed", mode="retrieval", save_result=False)
    )

    assert rag.strategies == ["normal", "directed", "combined", "auto"]
    assert result["scores"]["directed"] == 100.0
    assert result["run"]["directed_path_checks_enabled"] is True
    assert result["summary"]["directed"]["strategies"]["normal"]["path_score"] == 100.0
    assert result["summary"]["directed"]["strategies"]["directed"]["path_score"] == 100.0
    assert result["summary"]["directed"]["strategies"]["combined"]["path_score"] == 100.0
    assert result["summary"]["directed"]["strategies"]["auto"]["path_score"] == 100.0
    assert result["quality_gates"]["configured"] is True
    assert result["quality_gates"]["passed"] is True
    assert result["failed_checks"] == []
