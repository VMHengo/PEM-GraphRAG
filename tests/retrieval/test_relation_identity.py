import pytest

from lightrag.relation_identity import (
    legacy_relation_vdb_ids,
    make_directional_relation_chunk_key,
    make_directional_relation_vdb_id,
    relation_identity,
)


@pytest.mark.offline
def test_directed_relation_identity_preserves_semantic_endpoint_order():
    relation = {
        "semantic_src_id": "Electrode Stacking",
        "semantic_tgt_id": "Electrode Thickness",
        "directionality": "directed",
        "relation_type": "influences",
    }

    forward = relation_identity("Electrode Thickness", "Electrode Stacking", relation)
    reverse = relation_identity(
        "Electrode Thickness",
        "Electrode Stacking",
        {**relation, "semantic_src_id": "Electrode Thickness", "semantic_tgt_id": "Electrode Stacking"},
    )

    assert "Electrode Stacking" in forward
    assert forward != reverse
    assert make_directional_relation_vdb_id("x", "y", relation) != make_directional_relation_vdb_id(
        "x",
        "y",
        {**relation, "semantic_src_id": "Electrode Thickness", "semantic_tgt_id": "Electrode Stacking"},
    )


@pytest.mark.offline
def test_undirected_relation_identity_keeps_endpoint_order_stable():
    relation = {"directionality": "unknown", "relation_type": "related_to"}

    assert relation_identity("B", "A", relation) == relation_identity("A", "B", relation)
    assert make_directional_relation_chunk_key("B", "A", relation).startswith("rel-v2")


@pytest.mark.offline
def test_legacy_relation_vdb_candidates_remain_available_for_old_data():
    candidates = legacy_relation_vdb_ids("Electrode Stacking", "Electrode Thickness")

    assert candidates
    assert all(candidate.startswith("rel-") for candidate in candidates)
