import asyncio
import json
from pathlib import Path

from lightrag.evaluation.live_benchmark import (
    list_benchmarks,
    load_benchmark,
    run_live_benchmark,
    score_graph_cases,
)


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
