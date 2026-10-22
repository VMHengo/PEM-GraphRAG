import json

import pytest

from lightrag.constants import GRAPH_FIELD_SEP
from lightrag.operate import (
    _merge_edges_then_upsert,
    _process_extraction_result,
    _process_json_extraction_result,
)


class _FakeGraphStorage:
    def __init__(self):
        self.nodes = {}
        self.edges = {}

    async def has_edge(self, src_id, tgt_id):
        return (src_id, tgt_id) in self.edges

    async def get_edge(self, src_id, tgt_id):
        return self.edges.get((src_id, tgt_id))

    async def get_node(self, entity_id):
        return self.nodes.get(entity_id)

    async def upsert_node(self, entity_id, node_data):
        self.nodes[entity_id] = node_data

    async def upsert_edge(self, src_id, tgt_id, edge_data):
        self.edges[(src_id, tgt_id)] = edge_data


class _FakeVectorStorage:
    def __init__(self):
        self.records = {}

    async def upsert(self, records):
        self.records.update(records)


@pytest.mark.offline
@pytest.mark.asyncio
async def test_json_relationship_metadata_is_preserved():
    result = json.dumps(
        {
            "entities": [
                {
                    "name": "Electrode Stacking",
                    "type": "Process",
                    "description": "Electrode stacking is a battery cell assembly process step.",
                },
                {
                    "name": "Electrode Thickness",
                    "type": "Data",
                    "description": "Electrode thickness is a measurable production property.",
                },
            ],
            "relationships": [
                {
                    "source": "Electrode Stacking",
                    "target": "Electrode Thickness",
                    "keywords": "process parameter, thickness influence",
                    "description": "Electrode stacking influences electrode thickness.",
                    "directionality": "directed",
                    "relation_type": "influences",
                    "relation_importance": 0.93,
                    "chain_role": "process_parameter",
                    "direction_confidence": 0.88,
                    "direction_rationale": "The process step is stated as the influencing factor.",
                }
            ],
        }
    )

    nodes, edges = await _process_json_extraction_result(
        result,
        "chunk-001",
        123,
        "electrode-stacking.pdf",
    )

    assert "Electrode Stacking" in nodes
    edge = edges[("Electrode Stacking", "Electrode Thickness")][0]
    assert edge["directionality"] == "directed"
    assert edge["relation_type"] == "influences"
    assert edge["relation_importance"] == pytest.approx(0.93)
    assert edge["chain_role"] == "process_parameter"
    assert edge["direction_confidence"] == pytest.approx(0.88)
    assert edge["semantic_src_id"] == "Electrode Stacking"
    assert edge["semantic_tgt_id"] == "Electrode Thickness"


@pytest.mark.offline
@pytest.mark.asyncio
async def test_json_relationship_metadata_defaults_keep_old_outputs_compatible():
    result = json.dumps(
        {
            "entities": [
                {
                    "name": "Residual Solvent",
                    "type": "Concept",
                    "description": "Residual solvent remains after incomplete drying.",
                },
                {
                    "name": "Coating Defect",
                    "type": "Concept",
                    "description": "Coating defect is a battery electrode quality issue.",
                },
            ],
            "relationships": [
                {
                    "source": "Residual Solvent",
                    "target": "Coating Defect",
                    "keywords": "causes, defect formation",
                    "description": "Residual solvent causes coating defect formation.",
                }
            ],
        }
    )

    _, edges = await _process_json_extraction_result(result, "chunk-002", 456)

    edge = edges[("Residual Solvent", "Coating Defect")][0]
    assert edge["directionality"] == "unknown"
    assert edge["relation_type"] == "causes"
    assert edge["relation_importance"] == pytest.approx(0.5)
    assert edge["chain_role"] == "other"
    assert edge["semantic_src_id"] == "Residual Solvent"
    assert edge["semantic_tgt_id"] == "Coating Defect"


@pytest.mark.offline
@pytest.mark.asyncio
async def test_delimiter_relationship_metadata_accepts_new_nine_field_rows():
    result = (
        "relation<|#|>Insufficient Electrode Thickness<|#|>Coating Defect"
        "<|#|>causes, quality defect"
        "<|#|>Insufficient electrode thickness causes a coating defect."
        "<|#|>directed<|#|>causes<|#|>0.94<|#|>root_cause<|COMPLETE|>"
    )

    _, edges = await _process_extraction_result(result, "chunk-003", 789)

    edge = edges[("Insufficient Electrode Thickness", "Coating Defect")][0]
    assert edge["directionality"] == "directed"
    assert edge["relation_type"] == "causes"
    assert edge["relation_importance"] == pytest.approx(0.94)
    assert edge["chain_role"] == "root_cause"


@pytest.mark.offline
@pytest.mark.asyncio
async def test_delimiter_relationship_metadata_keeps_old_five_field_rows_compatible():
    result = (
        "relation<|#|>Thermal Runaway<|#|>Thermal Propagation"
        "<|#|>causes, safety event"
        "<|#|>Thermal runaway can cause thermal propagation."
        "<|COMPLETE|>"
    )

    _, edges = await _process_extraction_result(result, "chunk-004", 999)

    edge = edges[("Thermal Runaway", "Thermal Propagation")][0]
    assert edge["directionality"] == "unknown"
    assert edge["relation_type"] == "causes"
    assert edge["relation_importance"] == pytest.approx(0.5)
    assert edge["chain_role"] == "other"


@pytest.mark.offline
@pytest.mark.asyncio
async def test_relationship_metadata_survives_edge_merge_with_sorted_storage_key():
    graph = _FakeGraphStorage()
    edges_data = [
        {
            "src_id": "Residual Solvent",
            "tgt_id": "Coating Defect",
            "weight": 1.0,
            "description": "Residual solvent causes coating defect formation.",
            "keywords": "causes, defect formation",
            "source_id": "chunk-005",
            "file_path": "coating-defects.pdf",
            "timestamp": 111,
            "directionality": "directed",
            "relation_type": "causes",
            "relation_importance": 0.95,
            "chain_role": "root_cause",
            "semantic_src_id": "Residual Solvent",
            "semantic_tgt_id": "Coating Defect",
        }
    ]

    edge = await _merge_edges_then_upsert(
        "Coating Defect",
        "Residual Solvent",
        edges_data,
        knowledge_graph_inst=graph,
        relationships_vdb=None,
        entity_vdb=None,
        global_config={
            "source_ids_limit_method": "KEEP",
            "max_source_ids_per_relation": 100,
            "max_source_ids_per_entity": 100,
            "max_file_paths": 10,
        },
    )

    stored_edge = graph.edges[("Coating Defect", "Residual Solvent")]
    assert edge["directionality"] == "directed"
    assert stored_edge["relation_type"] == "causes"
    assert stored_edge["relation_importance"] == pytest.approx(0.95)
    assert stored_edge["chain_role"] == "root_cause"
    assert stored_edge["semantic_src_id"] == "Residual Solvent"
    assert stored_edge["semantic_tgt_id"] == "Coating Defect"


@pytest.mark.offline
@pytest.mark.asyncio
@pytest.mark.parametrize("use_entity_vdb", [False, True])
async def test_existing_edge_endpoint_updates_with_optional_entity_vdb(
    monkeypatch, use_entity_vdb
):
    async def summarize(_kind, _name, descriptions, _separator, _config, _cache=None, **_kwargs):
        return " ".join(descriptions), False

    monkeypatch.setattr("lightrag.operate._handle_entity_relation_summary", summarize)
    graph = _FakeGraphStorage()
    graph.nodes = {
        name: {
            "entity_id": name,
            "source_id": "chunk-old",
            "description": name,
            "entity_type": "concept",
            "file_path": "old.pdf",
        }
        for name in ("Process", "Defect")
    }
    entity_vdb = _FakeVectorStorage() if use_entity_vdb else None

    await _merge_edges_then_upsert(
        "Process",
        "Defect",
        [{
            "src_id": "Process", "tgt_id": "Defect",
            "description": "Process causes defect.",
            "keywords": "causes", "weight": 1.0,
            "source_id": "chunk-new", "file_path": "new.pdf",
            "directionality": "directed", "relation_type": "causes",
            "semantic_src_id": "Process", "semantic_tgt_id": "Defect",
        }],
        knowledge_graph_inst=graph,
        relationships_vdb=None,
        entity_vdb=entity_vdb,
        global_config={
            "source_ids_limit_method": "KEEP",
            "max_source_ids_per_relation": 100,
            "max_source_ids_per_entity": 100,
            "max_file_paths": 10,
        },
    )

    for node in graph.nodes.values():
        assert set(node["source_id"].split(GRAPH_FIELD_SEP)) == {
            "chunk-old", "chunk-new"
        }
    assert graph.edges[("Process", "Defect")]["relation_type"] == "causes"
    if entity_vdb is not None:
        assert len(entity_vdb.records) == 2
        assert {row["entity_name"] for row in entity_vdb.records.values()} == {
            "Process", "Defect"
        }
        for row in entity_vdb.records.values():
            assert set(row["source_id"].split(GRAPH_FIELD_SEP)) == {
                "chunk-old", "chunk-new"
            }
