"""Explicit intermediate states must survive JSON parsing and graph merge."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lightrag.operate import _merge_edges_then_upsert, _process_json_extraction_result
from lightrag.prompt import load_entity_extraction_prompt_profile
from lightrag.relation_assertions import parse_relation_assertions


class _Graph:
    def __init__(self) -> None:
        self.nodes: dict = {}
        self.edges: dict = {}

    async def has_edge(self, source: str, target: str) -> bool:
        return (source, target) in self.edges

    async def get_edge(self, source: str, target: str) -> dict | None:
        return self.edges.get((source, target))

    async def get_node(self, entity_id: str) -> dict | None:
        return self.nodes.get(entity_id)

    async def upsert_node(self, entity_id: str, node_data: dict) -> None:
        self.nodes[entity_id] = node_data

    async def upsert_edge(self, source: str, target: str, edge_data: dict) -> None:
        self.edges[(source, target)] = edge_data


@pytest.mark.offline
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "names", "relations", "condition"),
    [
        (
            "Local electrolyte drying causes local potential to change. "
            "During recharging, the potential change contributes to nonuniform local current.",
            ("Local Electrolyte Drying", "Local Potential Change", "Nonuniform Local Current"),
            ("causes", "influences"),
            "During recharging",
        ),
        (
            "High-temperature aging makes lithium-ion diffusion more difficult. "
            "The increased diffusion difficulty leads to increased Warburg resistance.",
            (
                "High-Temperature Aging",
                "Increased Lithium-Ion Diffusion Difficulty",
                "Increased Warburg Resistance",
            ),
            ("results_in", "leads_to"),
            "increased diffusion difficulty",
        ),
    ],
)
async def test_intermediate_edges_and_quotes_survive_parser_and_merge(
    monkeypatch, content, names, relations, condition
):
    async def summarize(_kind, _name, descriptions, _separator, _config, _cache=None):
        return " ".join(descriptions), False

    monkeypatch.setattr("lightrag.operate._handle_entity_relation_summary", summarize)
    graph = _Graph()
    sentences = content.split(". ")
    sentences[0] += "."
    payload = {
        "entities": [
            {"name": name, "type": "Data", "description": name}
            for name in names
        ],
        "relationships": [
            {
                "source": names[index],
                "target": names[index + 1],
                "description": sentences[index],
                "keywords": relation_type,
                "directionality": "directed",
                "relation_type": relation_type,
                "relation_importance": 0.9,
                "chain_role": "consequence",
                "evidence_quote": sentences[index],
            }
            for index, relation_type in enumerate(relations)
        ],
    }
    nodes, edges = await _process_json_extraction_result(
        json.dumps(payload), "chunk-aging", 123, "aging.pdf", chunk_content=content
    )

    assert set(nodes) == set(names)
    assert set(edges) == {(names[0], names[1]), (names[1], names[2])}
    assert all(record[0]["evidence"] for record in edges.values())
    assert condition.casefold() in edges[(names[1], names[2])][0]["description"].casefold()

    config = {
        "source_ids_limit_method": "KEEP",
        "max_source_ids_per_relation": 100,
        "max_source_ids_per_entity": 100,
        "max_file_paths": 10,
    }
    for (source, target), records in edges.items():
        await _merge_edges_then_upsert(
            source, target, records, knowledge_graph_inst=graph,
            relationships_vdb=None, entity_vdb=None, global_config=config,
        )

    for (source, target), relation_type in zip(edges, relations, strict=True):
        assertions = parse_relation_assertions(graph.edges[(source, target)], source, target)
        assert len(assertions) == 1
        assert assertions[0]["semantic_src_id"] == source
        assert assertions[0]["semantic_tgt_id"] == target
        assert assertions[0]["relation_type"] == relation_type
        assert assertions[0]["directionality"] == "directed"
        assert assertions[0]["evidence_status"] == "quoted"


def test_explicit_intermediate_prompt_profile_is_valid_and_non_leaking():
    profile = load_entity_extraction_prompt_profile(
        Path("prompts/samples/pem_aging_explicit_intermediates_v2.sample.yml")
    )
    example = profile["entity_extraction_json_examples"][0]
    payload = json.loads(example.split("---Output---", 1)[1].strip())

    assert len(payload["entities"]) == 4
    assert len(payload["relationships"]) == 3
    assert "Higher Enclosure Temperature" in {
        item["name"] for item in payload["entities"]
    }
    assert "local electrolyte drying" not in example.casefold()
