"""Description-to-structure hints are focused and never mutate graph data."""

import pytest

from scripts.audit_description_structure import _flags, audit_description_structure


def _edge(source, predicate, target, description):
    return {"source": source, "predicate": predicate, "target": target,
            "description": description, "chunk_id": "chunk-1"}


def _codes(edge):
    return {flag["code"] for flag in _flags(edge)}


def test_aging_state_and_rate_mismatch():
    edge = _edge(
        "Cell Capacity", "decreases", "Temperature Rise Rate",
        "Degradation of cell capacity makes the temperature rise decrease.",
    )
    assert {"rise_vs_rise_rate", "stateful_source_collapsed"} <= _codes(edge)


def test_reaction_partner_in_description_only():
    edge = _edge(
        "Plated Metallic Lithium", "produces", "Organic Lithium Salts",
        "Plated metallic lithium reacts with the electrolyte to form organic lithium salts.",
    )
    assert "reaction_participant_not_endpoint" in _codes(edge)


def test_severity_and_doubled_change_are_review_hints():
    edge = _edge(
        "Cell Degradation", "increases", "DC Resistance Increase",
        "Severe degradation significantly increases DC resistance.",
    )
    assert {"condition_only_in_description", "effect_double_encoded"} <= _codes(edge)


def test_normal_relation_has_no_targeted_flags():
    assert _codes(_edge("Deeper Aging", "increases", "Temperature Rise Rate",
                       "Deeper aging increases temperature rise rate.")) == set()


def test_scopes_to_candidate_edges_and_validates_artifact():
    edge = {"id": "r1", **_edge("Cell Capacity", "decreases", "Temperature Rise Rate",
                                "Degradation of cell capacity makes the temperature rise decrease.")}
    coverage = {"fingerprint": "abc", "document_id": "doc-1", "relations": [edge]}
    comparison = {"artifact_fingerprint": "abc", "document_id": "doc-1", "rows": [{
        "passage_id": "p1", "gold": {"source": "Capacity Degradation"},
        "candidates": [{key: edge[key] for key in ("source", "predicate", "target", "chunk_id")}],
    }]}
    report = audit_description_structure(coverage, comparison)
    assert report["inspected_assertions"] == 1
    assert report["flag_counts"]["rise_vs_rise_rate"] == 1
    assert coverage["relations"][0] == edge
    comparison["artifact_fingerprint"] = "wrong"
    with pytest.raises(ValueError, match="different frozen artifacts"):
        audit_description_structure(coverage, comparison)
