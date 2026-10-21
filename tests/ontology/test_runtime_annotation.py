import json
from pathlib import Path

import pytest

from lightrag.ontology_annotation import (
    annotate_ontology_label,
    ontology_annotation_revision,
    _load_mapping,
)
from lightrag.api.azure_batch import (
    AzureBatchOutputValidationError,
    _validate_ontology_batch_snapshot,
)
from lightrag.relation_assertions import parse_relation_assertions
from lightrag.relation_identity import (
    make_directional_relation_chunk_key,
    make_directional_relation_vdb_id,
)
from lightrag.operate import (
    _merge_edges_then_upsert,
    _merge_nodes_then_upsert,
    _process_json_extraction_result,
    _rebuild_single_relationship,
)


class Graph:
    def __init__(self):
        self.nodes = {}
        self.edges = {}

    async def get_node(self, key):
        return self.nodes.get(key)

    async def has_node(self, key):
        return key in self.nodes

    async def upsert_node(self, key, node_data):
        self.nodes[key] = node_data

    async def get_edge(self, source, target):
        return self.edges.get((source, target))

    async def has_edge(self, source, target):
        return (source, target) in self.edges

    async def upsert_edge(self, source, target, edge_data):
        self.edges[(source, target)] = edge_data


class KV:
    def __init__(self):
        self.rows = {}

    async def upsert(self, rows):
        self.rows.update(rows)

    async def get_by_id(self, key):
        return self.rows.get(key)

    async def delete(self, keys):
        for key in keys:
            self.rows.pop(key, None)


@pytest.fixture
def ontology_enabled(monkeypatch):
    monkeypatch.setenv("ONTOLOGY_ANNOTATION_ENABLED", "true")
    monkeypatch.setenv(
        "PEM_ONTOLOGY_MAPPING_PATH",
        str(Path(__file__).resolve().parents[2] / "ontology" / "pem_mapping_v1.json"),
    )
    _load_mapping.cache_clear()


@pytest.mark.offline
def test_annotation_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ONTOLOGY_ANNOTATION_ENABLED", raising=False)
    assert annotate_ontology_label("causes", relation=True) == {}


@pytest.mark.offline
def test_only_reviewed_exact_mapping_gets_iri(ontology_enabled):
    cause = annotate_ontology_label("causes", relation=True)
    assert cause["ontology_mapping_version"] == "1.0.0"
    assert cause["ontology_mapping_status"] == "mapped"
    assert cause["ontology_iri"].startswith("https://w3id.org/emmo#")
    assert cause["ontology_source"] == "EMMO core"
    for label in ("produces", "affects", "nonsense"):
        assert annotate_ontology_label(label, relation=True)["ontology_iri"] == ""
    assert annotate_ontology_label("Process", relation=False)["ontology_iri"] == ""


@pytest.mark.offline
@pytest.mark.asyncio
async def test_edge_write_keeps_raw_and_provenance(ontology_enabled):
    graph = Graph()
    await _merge_edges_then_upsert(
        "Defect", "Residual Solvent",
        [{
            "src_id": "Residual Solvent", "tgt_id": "Defect",
            "description": "Residual solvent causes a defect.",
            "keywords": "causes", "weight": 1.0,
            "source_id": "chunk-005", "file_path": "quality.pdf",
            "directionality": "directed", "relation_type": "causes",
            "relation_importance": 0.9,
            "semantic_src_id": "Residual Solvent", "semantic_tgt_id": "Defect",
        }],
        knowledge_graph_inst=graph, relationships_vdb=None, entity_vdb=None,
        global_config={
            "source_ids_limit_method": "KEEP",
            "max_source_ids_per_relation": 100,
            "max_source_ids_per_entity": 100,
            "max_file_paths": 10,
        },
    )
    edge = graph.edges[("Defect", "Residual Solvent")]
    assert edge["relation_type"] == "causes"
    assert edge["raw_relation_type"] == "causes"
    assert edge["semantic_src_id"] == "Residual Solvent"
    assert edge["semantic_tgt_id"] == "Defect"
    assert edge["source_id"] == "chunk-005"
    assert edge["file_path"] == "quality.pdf"
    assert edge["ontology_mapping_status"] == "mapped"
    assert edge["ontology_iri"].startswith("https://w3id.org/emmo#")


@pytest.mark.offline
@pytest.mark.asyncio
async def test_pair_edge_retains_distinct_assertions(ontology_enabled, monkeypatch):
    async def summarize(_kind, _name, descriptions, _separator, _config, _cache=None, **_kwargs):
        return " ".join(descriptions), False

    monkeypatch.setattr("lightrag.operate._handle_entity_relation_summary", summarize)
    graph = Graph()
    edges = [
        {
            "src_id": source, "tgt_id": target,
            "semantic_src_id": source, "semantic_tgt_id": target,
            "relation_type": predicate, "directionality": "directed",
            "relation_importance": 0.9,
            "description": f"{source} {predicate} {target}",
            "keywords": predicate, "weight": 1.0,
            "source_id": chunk, "file_path": "pilot.pdf",
        }
        for source, target, predicate, chunk in (
            ("A", "B", "causes", "chunk-1"),
            ("B", "A", "influences", "chunk-2"),
        )
    ]
    await _merge_edges_then_upsert(
        "A", "B", edges, knowledge_graph_inst=graph,
        relationships_vdb=None, entity_vdb=None, added_entities=[],
        global_config={
            "source_ids_limit_method": "KEEP", "max_source_ids_per_relation": 100,
            "max_source_ids_per_entity": 100, "max_file_paths": 10,
        },
    )
    assertions = parse_relation_assertions(graph.edges[("A", "B")], "A", "B")
    assert {(item["semantic_src_id"], item["relation_type"], item["semantic_tgt_id"])
            for item in assertions} == {
        ("A", "causes", "B"), ("B", "influences", "A")
    }
    assert next(item for item in assertions if item["relation_type"] == "causes")[
        "ontology_iri"
    ].startswith("https://w3id.org/emmo#")

    await _rebuild_single_relationship(
        knowledge_graph_inst=graph,
        relationships_vdb=KV(),
        entities_vdb=None,
        src="A", tgt="B", chunk_ids=["chunk-2"],
        chunk_relationships={"chunk-2": {("B", "A"): [edges[1]]}},
        llm_response_cache=None,
        global_config={
            "source_ids_limit_method": "KEEP", "max_source_ids_per_relation": 100,
            "max_source_ids_per_entity": 100, "max_file_paths": 10,
        },
        relation_chunks_storage=KV(),
    )
    rebuilt = parse_relation_assertions(graph.edges[("A", "B")], "A", "B")
    assert len(rebuilt) == 1
    assert rebuilt[0]["source_id"] == "chunk-2"
    assert rebuilt[0]["semantic_src_id"] == "B"
    assert graph.edges[("A", "B")]["relation_type"] == "influences"


@pytest.mark.offline
@pytest.mark.asyncio
async def test_reselecting_pair_edge_cleans_old_directional_records(
    ontology_enabled, monkeypatch
):
    async def summarize(_kind, _name, descriptions, _separator, _config, _cache=None, **_kwargs):
        return " ".join(descriptions), False

    monkeypatch.setattr("lightrag.operate._handle_entity_relation_summary", summarize)
    graph = Graph()
    graph.nodes = {
        name: {"source_id": "chunk-1", "description": name, "entity_type": "UNKNOWN"}
        for name in ("A", "B")
    }
    old = {
        "semantic_src_id": "A", "semantic_tgt_id": "B",
        "relation_type": "influences", "directionality": "directed",
        "relation_importance": 0.1, "description": "A influences B",
        "keywords": "influences", "weight": 1.0,
        "source_id": "chunk-1", "file_path": "pilot.pdf",
    }
    graph.edges[("A", "B")] = old
    relation_chunks = KV()
    relationships_vdb = KV()
    old_key = make_directional_relation_chunk_key("A", "B", old)
    old_id = make_directional_relation_vdb_id("A", "B", old)
    relation_chunks.rows[old_key] = {"chunk_ids": ["chunk-1"], "count": 1}
    relationships_vdb.rows[old_id] = {"content": "old"}
    new = {
        **old, "relation_type": "causes", "relation_importance": 1.0,
        "description": "A causes B", "keywords": "causes", "source_id": "chunk-2",
    }

    await _merge_edges_then_upsert(
        "A", "B", [new], knowledge_graph_inst=graph,
        relationships_vdb=relationships_vdb, entity_vdb=KV(),
        relation_chunks_storage=relation_chunks, entity_chunks_storage=KV(),
        global_config={
            "source_ids_limit_method": "KEEP", "max_source_ids_per_relation": 100,
            "max_source_ids_per_entity": 100, "max_file_paths": 10,
        },
    )

    assert old_key not in relation_chunks.rows
    assert old_id not in relationships_vdb.rows
    selected = graph.edges[("A", "B")]
    assert selected["relation_type"] == "causes"
    assert make_directional_relation_chunk_key("A", "B", selected) in relation_chunks.rows
    assert make_directional_relation_vdb_id("A", "B", selected) in relationships_vdb.rows


@pytest.mark.offline
@pytest.mark.asyncio
async def test_node_write_does_not_assert_conditional_type(ontology_enabled):
    graph = Graph()
    await _merge_nodes_then_upsert(
        "Stacking", [{
            "entity_name": "Stacking", "entity_type": "Process",
            "raw_entity_type": "Process",
            "description": "A cell assembly operation.",
            "source_id": "chunk-002", "file_path": "cell.pdf",
        }],
        knowledge_graph_inst=graph, entity_vdb=None,
        global_config={"max_source_ids_per_entity": 100, "max_file_paths": 10},
    )
    node = graph.nodes["Stacking"]
    assert node["entity_type"] == "Process"
    assert node["raw_entity_type"] == "Process"
    assert node["ontology_mapping_status"] == "conditional"
    assert node["ontology_iri"] == ""
    assert node["source_id"] == "chunk-002"


@pytest.mark.offline
@pytest.mark.asyncio
async def test_json_parser_retains_raw_entity_type_only_when_enabled(ontology_enabled):
    payload = json.dumps({
        "entities": [{"name": "Stacking", "type": "Process", "description": "Assembly."}],
        "relationships": [],
    })
    nodes, _ = await _process_json_extraction_result(payload, "chunk-002", 1)
    assert nodes["Stacking"][0]["entity_type"] == "process"
    assert nodes["Stacking"][0]["raw_entity_type"] == "Process"


@pytest.mark.offline
def test_bad_mapping_fails_closed(tmp_path, monkeypatch):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
    monkeypatch.setenv("ONTOLOGY_ANNOTATION_ENABLED", "true")
    monkeypatch.setenv("PEM_ONTOLOGY_MAPPING_PATH", str(path))
    with pytest.raises(ValueError, match="schema"):
        annotate_ontology_label("causes", relation=True)


@pytest.mark.offline
def test_batch_rejects_changed_mapping(ontology_enabled):
    snapshot = ontology_annotation_revision()
    job = {"submission_manifest": {"extraction_revision": {
        "ontology_annotation": snapshot,
    }}}
    _validate_ontology_batch_snapshot(job)
    job["submission_manifest"]["extraction_revision"]["ontology_annotation"] = {
        **snapshot, "mapping_sha256": "old"
    }
    with pytest.raises(AzureBatchOutputValidationError, match="mapping changed"):
        _validate_ontology_batch_snapshot(job)
