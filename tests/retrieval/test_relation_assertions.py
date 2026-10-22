import json

import pytest

from lightrag.relation_assertions import (
    RELATION_ASSERTIONS_FIELD,
    filter_relation_assertions,
    merge_relation_assertions,
    parse_relation_assertions,
    relation_assertion_identity,
    make_assertion_vdb_id,
    serialize_relation_assertions,
)
from lightrag.base import QueryParam
from lightrag.operate import _assertion_vector_rows, _get_edge_data
from lightrag.utils import convert_to_user_format


def _assertion(source, target, predicate, chunk_id, **extra):
    return {
        "semantic_src_id": source,
        "semantic_tgt_id": target,
        "relation_type": predicate,
        "directionality": "directed",
        "source_id": chunk_id,
        "description": f"{source} {predicate} {target}",
        **extra,
    }


@pytest.mark.offline
def test_preserves_two_predicates_and_opposite_directions_on_same_pair():
    assertions = [
        _assertion("A", "B", "causes", "chunk-1"),
        _assertion("A", "B", "increases", "chunk-1"),
        _assertion("B", "A", "causes", "chunk-1"),
    ]

    merged = merge_relation_assertions(None, assertions, "A", "B")

    assert len(merged) == 3
    identities = {
        relation_assertion_identity("A", "B", assertion) for assertion in merged
    }
    assert len(identities) == 3
    assert len({make_assertion_vdb_id("A", "B", item) for item in merged}) == 3
    assert parse_relation_assertions(
        {RELATION_ASSERTIONS_FIELD: serialize_relation_assertions(merged)}, "A", "B"
    ) == merged


@pytest.mark.asyncio
@pytest.mark.offline
async def test_normal_retrieval_preserves_assertions_on_one_pair():
    assertions = [
        _assertion("A", "B", "causes", "chunk-1"),
        _assertion("B", "A", "influences", "chunk-2"),
    ]
    rows = _assertion_vector_rows("A", "B", assertions, {})

    class Vectors:
        cosine_better_than_threshold = 0.0

        async def query(self, *_args, **_kwargs):
            return list(rows.values())

    class Graph:
        async def get_edges_batch(self, _pairs):
            return {("A", "B"): {
                "description": "selected pair summary",
                "relation_type": "causes",
                "source_id": "chunk-1<SEP>chunk-2",
            }}

        async def get_nodes_batch(self, _names):
            return {"A": {}, "B": {}}

    edges, _nodes = await _get_edge_data(
        "cause", Graph(), Vectors(), QueryParam(mode="global")
    )
    assert [(edge["semantic_src_id"], edge["relation_type"],
             edge["semantic_tgt_id"], edge["source_id"]) for edge in edges] == [
        ("A", "causes", "B", "chunk-1"),
        ("B", "influences", "A", "chunk-2"),
    ]


@pytest.mark.offline
def test_user_format_keeps_two_assertions_on_one_physical_pair():
    relations = [
        {"entity1": "A", "entity2": "B", "assertion_id": "assert-1"},
        {"entity1": "A", "entity2": "B", "assertion_id": "assert-2"},
        {"entity1": "B", "entity2": "A", "assertion_id": "assert-3"},
    ]
    originals = {
        "assert-1": {"src_id": "A", "tgt_id": "B", "relation_type": "causes",
                     "source_id": "chunk-1"},
        "assert-2": {"src_id": "A", "tgt_id": "B", "relation_type": "increases",
                     "source_id": "chunk-2"},
        "assert-3": {"src_id": "A", "tgt_id": "B", "semantic_src_id": "B",
                     "semantic_tgt_id": "A", "relation_type": "influences",
                     "source_id": "chunk-3"},
    }
    response = convert_to_user_format(
        [], relations, [], [], "global", relation_id_to_original=originals
    )
    assert [(item["src_id"], item["relation_type"], item["tgt_id"],
             item["source_id"]) for item in response["data"]["relationships"]] == [
        ("A", "causes", "B", "chunk-1"),
        ("A", "increases", "B", "chunk-2"),
        ("B", "influences", "A", "chunk-3"),
    ]


@pytest.mark.offline
def test_duplicate_replay_is_idempotent_and_serialization_is_deterministic():
    assertion = _assertion(
        "Coating",
        "Thickness",
        "influences",
        "chunk-7",
        raw_relation_type="affects",
        evidence="The coating step controls final thickness.",
        keywords="coating, thickness",
        file_path="paper.pdf",
        ontology_iri="https://example.test/influences",
        ontology_mapping_status="mapped",
        ontology_mapping_version="v1",
    )
    first = merge_relation_assertions(None, [assertion], "Coating", "Thickness")
    edge = {RELATION_ASSERTIONS_FIELD: serialize_relation_assertions(first)}

    replayed = merge_relation_assertions(
        edge, [assertion, dict(assertion)], "Coating", "Thickness"
    )
    other = _assertion("Thickness", "Coating", "limits", "chunk-8")

    assert replayed == first
    assert serialize_relation_assertions([assertion, other]) == (
        serialize_relation_assertions([other, assertion])
    )
    assert json.loads(serialize_relation_assertions(replayed))[0]["ontology_iri"] == (
        "https://example.test/influences"
    )


@pytest.mark.offline
def test_filter_removes_only_assertions_from_deleted_source_chunks():
    assertions = [
        _assertion("A", "B", "causes", "chunk-delete"),
        _assertion("B", "A", "prevents", "chunk-keep"),
    ]

    retained = filter_relation_assertions(
        assertions, {"chunk-delete"}, "A", "B"
    )

    assert [item["source_id"] for item in retained] == ["chunk-keep"]
    assert retained[0]["semantic_src_id"] == "B"
    assert retained[0]["semantic_tgt_id"] == "A"


@pytest.mark.offline
def test_remapping_clears_old_ontology_iri_for_same_assertion():
    old = _assertion(
        "A", "B", "causes", "chunk-1",
        ontology_iri="https://example.test/old",
        ontology_source="old-source",
        ontology_mapping_status="mapped",
        ontology_mapping_version="v1",
    )
    edge = {RELATION_ASSERTIONS_FIELD: serialize_relation_assertions([old])}
    updated = _assertion(
        "A", "B", "causes", "chunk-1",
        ontology_iri="",
        ontology_source="",
        ontology_mapping_status="unmapped",
        ontology_mapping_version="v2",
    )

    [assertion] = merge_relation_assertions(edge, [updated], "A", "B")

    assert assertion["ontology_iri"] == ""
    assert assertion["ontology_source"] == ""
    assert assertion["ontology_mapping_status"] == "unmapped"
    assert assertion["ontology_mapping_version"] == "v2"


@pytest.mark.offline
def test_legacy_fallback_splits_sources_and_new_schema_fails_closed():
    legacy_edge = {
        "semantic_src_id": "Drying",
        "semantic_tgt_id": "Residual Solvent",
        "relation_type": "decreases",
        "directionality": "directed",
        "raw_relation_type": "reduces",
        "description": "Longer drying reduces residual solvent.",
        "keywords": "drying, solvent",
        "source_id": "chunk-1<SEP>chunk-2",
        "file_path": "one.pdf<SEP>two.pdf",
    }

    assertions = parse_relation_assertions(legacy_edge, "Drying", "Residual Solvent")

    assert [item["source_id"] for item in assertions] == ["chunk-1", "chunk-2"]
    assert [item["file_path"] for item in assertions] == ["one.pdf", "two.pdf"]
    with pytest.raises(ValueError, match="Invalid relation assertions JSON"):
        parse_relation_assertions(
            {**legacy_edge, RELATION_ASSERTIONS_FIELD: "{not valid json"},
            "Drying",
            "Residual Solvent",
        )
