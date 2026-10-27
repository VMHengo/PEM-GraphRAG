"""Exact-start review discovery stays independent from keyword-retrieval anchors."""

import asyncio

from lightrag.base import QueryParam
from lightrag.evaluation.exploration_discovery import discover_from_start
from lightrag_mcp.exploration import classify_subject, format_exploration


def test_battery_cell_has_provisional_subject_area():
    subject = classify_subject("Battery Cell")
    assert subject["concept_id"] == "battery_cell"
    assert subject["domains"] == ["Materialien und Komponenten"]


def test_discovery_anchors_only_the_selected_node_and_resolves_source_chunks():
    class Graph:
        async def get_directed_neighbor_edges_batch(self, node_ids):
            records = {
                "Battery Cell": [{
                    "src_id": "Battery Cell", "tgt_id": "Heat Generation",
                    "directionality": "directed", "relation_type": "causes",
                    "relation_importance": 0.9, "source_id": "c1",
                }],
                "Heat Generation": [{
                    "src_id": "Heat Generation", "tgt_id": "Thermal Runaway",
                    "directionality": "directed", "relation_type": "leads_to",
                    "relation_importance": 0.9, "source_id": "c2",
                }],
            }
            return {node: records.get(node, []) for node in node_ids}

    class Chunks:
        async def get_by_ids(self, ids):
            contents = {
                "c1": "Battery Cell causes Heat Generation.",
                "c2": "Heat Generation leads to Thermal Runaway.",
            }
            return [{"content": contents[source_id], "file_path": "paper.pdf"} for source_id in ids]

    class Rag:
        chunk_entity_relation_graph = Graph()
        text_chunks = Chunks()

    param = QueryParam(
        mode="mix", retrieval_strategy="directed", edge_direction="out",
        hop_depth=2, chain_top_k=20, ll_keywords=["Battery Cell"],
    )
    payload = asyncio.run(discover_from_start(Rag(), "Battery Cell", param))
    assert payload is not None
    assert payload["metadata"]["directed_paths"]["anchor_entities"] == ["Battery Cell"]
    result = format_exploration(payload, start="Battery Cell")
    assert result["candidate_count"] == 1
    assert result["connections"][0]["path"][0]["sources"][0]["chunk_id"] == "c1"
    assert result["connections"][0]["path"][1]["sources"][0]["chunk_id"] == "c2"


def test_discovery_falls_back_when_provider_is_unavailable():
    assert asyncio.run(discover_from_start(object(), "Battery Cell", QueryParam())) is None
