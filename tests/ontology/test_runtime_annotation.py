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
from lightrag.operate import (
    _merge_edges_then_upsert,
    _merge_nodes_then_upsert,
    _process_json_extraction_result,
)


class Graph:
    def __init__(self):
        self.nodes = {}
        self.edges = {}

    async def get_node(self, key):
        return self.nodes.get(key)

    async def upsert_node(self, key, node_data):
        self.nodes[key] = node_data

    async def get_edge(self, source, target):
        return self.edges.get((source, target))

    async def has_edge(self, source, target):
        return (source, target) in self.edges

    async def upsert_edge(self, source, target, edge_data):
        self.edges[(source, target)] = edge_data


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
