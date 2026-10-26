"""Composition rules must not turn path hypotheses into fabricated direct facts."""

from __future__ import annotations

import pytest

from lightrag.evaluation.human_review import select_review_candidates
from lightrag.evaluation.path_inference import infer_indirect_connection
from lightrag_mcp.exploration import format_exploration


def _candidate(*relations: str) -> dict:
    nodes = [f"Variable {index}" for index in range(len(relations) + 1)]
    return {
        "from": nodes[0],
        "to": nodes[-1],
        "path": [
            {
                "source": nodes[index],
                "target": nodes[index + 1],
                "relation": relation,
                "sources": [
                    {"chunk_id": f"chunk-{index}", "chunk_excerpt": "Source text"}
                ],
            }
            for index, relation in enumerate(relations)
        ],
    }


@pytest.mark.parametrize(
    ("relations", "expected"),
    [
        (("increases", "increases"), "indirectly_increases"),
        (("decreases", "decreases"), "indirectly_increases"),
        (("increases", "decreases"), "indirectly_decreases"),
        (("decreases", "increases", "decreases"), "indirectly_increases"),
    ],
)
def test_signed_monotonic_hypotheses_are_explicitly_conditional(relations, expected):
    result = infer_indirect_connection(_candidate(*relations))
    assert result["relation"] == expected
    assert result["status"] == "candidate"
    assert result["rule"] == "signed_monotonic_composition"
    assert "monotonic" in " ".join(result["caveats"])


def test_affects_does_not_inherit_a_downstream_positive_sign():
    result = infer_indirect_connection(_candidate("affects", "increases"))
    assert result["relation"] == "may_indirectly_affect"
    assert result["polarity"] == "unknown"


def test_causal_chain_is_indirect_and_not_a_direct_cause():
    result = infer_indirect_connection(_candidate("causes", "results_in", "leads_to"))
    assert result["relation"] == "may_indirectly_lead_to"
    assert result["polarity"] == "unknown"


@pytest.mark.parametrize(
    "relation", ["precedes", "part_of", "uses", "prevents", "does_not_cause"]
)
def test_unsupported_predicates_do_not_compose_into_causation(relation):
    result = infer_indirect_connection(_candidate("causes", relation))
    assert result["status"] == "not_composable"
    assert result["relation"] is None
    assert result["rule"] == "unsupported_predicate"


def test_broken_continuity_and_missing_sources_block_composition():
    broken = _candidate("increases", "increases")
    broken["path"][1]["source"] = "Different variable"
    assert infer_indirect_connection(broken)["rule"] == "broken_path"

    missing = _candidate("increases", "increases")
    missing["path"][1]["sources"] = []
    assert infer_indirect_connection(missing)["rule"] == "missing_source"


def test_inference_does_not_mutate_extracted_hops():
    candidate = _candidate("decreases", "increases")
    original = [hop.copy() for hop in candidate["path"]]
    infer_indirect_connection(candidate)
    assert candidate["path"] == original


def test_review_selection_keeps_opposing_paths_without_collapsing_them():
    positive = _candidate("increases", "increases")
    negative = _candidate("increases", "decreases")
    others = []
    for index in range(4):
        candidate = _candidate("causes", "leads_to")
        candidate["to"] = f"Different endpoint {index}"
        candidate["path"][-1]["target"] = candidate["to"]
        others.append(candidate)
    selected = select_review_candidates(
        [{"connections": [positive, *others, negative]}], limit=5
    )
    same_endpoint = [item for item in selected if item["to"] == positive["to"]]
    assert len(selected) == 5
    assert {item["inferred_connection"]["polarity"] for item in same_endpoint} == {
        "positive",
        "negative",
    }


def test_full_chunk_and_parallel_paths_are_opt_in_for_review_only():
    def path(last_relation):
        return {
            "nodes": ["Electrode Calendering", "Cathode Porosity", "Lithium Plating"],
            "edges": [
                {
                    "source": "Electrode Calendering",
                    "target": "Cathode Porosity",
                    "relation_type": "increases",
                    "directionality": "directed",
                    "source_ids": ["chunk-1"],
                },
                {
                    "source": "Cathode Porosity",
                    "target": "Lithium Plating",
                    "relation_type": last_relation,
                    "directionality": "directed",
                    "source_ids": ["chunk-2"],
                },
            ],
        }

    payload = {
        "data": {
            "chunks": [
                {"chunk_id": "chunk-1", "file_path": "a.pdf", "content": "A" * 1100},
                {"chunk_id": "chunk-2", "file_path": "a.pdf", "content": "B" * 100},
            ],
            "references": [],
        },
        "metadata": {
            "directed_paths": {
                "status": "completed",
                "paths": [path("increases"), path("decreases")],
            }
        },
    }
    compact = format_exploration(payload, start="Electrode Calendering", limit=10)
    assert len(compact["connections"]) == 1
    assert "full_chunk_text" not in compact["connections"][0]["path"][0]["sources"][0]

    review = format_exploration(
        payload,
        start="Electrode Calendering",
        limit=10,
        include_full_chunks=True,
        max_paths_per_target=2,
    )
    assert len(review["connections"]) == 2
    assert (
        len(review["connections"][0]["path"][0]["sources"][0]["full_chunk_text"])
        == 1100
    )
    payload["data"]["chunks"][0]["content"] = "A" * 12001
    truncated = format_exploration(
        payload,
        start="Electrode Calendering",
        limit=10,
        include_full_chunks=True,
        max_paths_per_target=2,
    )["connections"][0]["path"][0]["sources"][0]
    assert len(truncated["full_chunk_text"]) == 12000
    assert truncated["full_chunk_truncated"] is True
