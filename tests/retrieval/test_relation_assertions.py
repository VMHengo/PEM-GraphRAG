import json

import pytest

from lightrag.relation_assertions import (
    RELATION_ASSERTIONS_FIELD,
    filter_relation_assertions,
    merge_relation_assertions,
    parse_relation_assertions,
    relation_assertion_identity,
    serialize_relation_assertions,
)


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
    assert parse_relation_assertions(
        {RELATION_ASSERTIONS_FIELD: serialize_relation_assertions(merged)}, "A", "B"
    ) == merged


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
