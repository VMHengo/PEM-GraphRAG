from lightrag.evaluation.live_benchmark import (
    benchmark_document_preflight,
    score_graph_cases,
)
from lightrag.evaluation.semantic_matching import path_match, relation_match, text_match
from lightrag.relation_ontology import canonicalize_relation, predicate_similarity


def test_explicit_inverse_relation_is_normalized_during_extraction():
    source, target, relation_type, inverse = canonicalize_relation(
        "Coating defect", "Residual solvent", "caused by"
    )

    assert inverse is True
    assert (source, relation_type, target) == (
        "Residual solvent",
        "causes",
        "Coating defect",
    )

    from lightrag.operate import _build_relationship_metadata

    metadata = _build_relationship_metadata(
        relation_type="caused by",
        source="Coating defect",
        target="Residual solvent",
    )
    assert metadata["semantic_src_id"] == "Residual solvent"
    assert metadata["semantic_tgt_id"] == "Coating defect"
    assert metadata["relation_type"] == "causes"
    assert metadata["relation_inverse_normalized"] is True


def test_related_causal_predicates_receive_partial_not_exact_credit():
    similarity = predicate_similarity("causes", "leads_to")

    assert similarity.exact is False
    assert 0 < similarity.score < 1


def test_relation_alias_and_accepted_predicate_are_reported_as_semantic_match():
    match = relation_match(
        {
            "source": "Electrode coating",
            "source_aliases": ["Coating process"],
            "relation_type": "causes",
            "accepted_relation_types": {"leads_to": 0.9},
            "target": "Coating defect",
            "directionality": "directed",
        },
        {
            "semantic_src_id": "Coating process",
            "semantic_tgt_id": "Coating defect",
            "relation_type": "leads_to",
            "directionality": "directed",
        },
    )

    assert match["exact"] is False
    assert match["predicate"]["score"] == 0.9
    assert match["score"] == 0.9


def test_matching_predicate_cannot_compensate_for_a_wrong_endpoint():
    match = relation_match(
        {
            "source": "Electrolyte decomposition",
            "relation_type": "causes",
            "target": "Gas generation",
            "directionality": "directed",
        },
        {
            "semantic_src_id": "Electrolyte decomposition",
            "semantic_tgt_id": "Lithium plating",
            "relation_type": "causes",
            "directionality": "directed",
        },
    )

    assert match["source"]["score"] == 1
    assert match["target"]["score"] == 0
    assert match["predicate"]["score"] == 1
    assert match["direction_score"] == 1
    assert match["score"] == 0


def test_generic_shared_tokens_do_not_credit_different_battery_concepts():
    assert text_match("DC Resistance", "Warburg Resistance").score == 0
    assert text_match("Graphite", "High-Energy NCM/Graphite Pouch Cell").score == 0
    assert text_match("Graphite", "Graphite Anode").score == 0.85


def test_reviewed_structural_inverse_is_credited_but_reverse_cause_is_not():
    expected = {
        "source": "Pouch Lithium-Ion Cell",
        "source_aliases": ["Pouch Lithium-Ion Battery"],
        "relation_type": "contains",
        "accepted_inverse_relation_types": {"part_of": 1},
        "target": "NCM622",
        "target_aliases": ["NCM622 Cathode"],
        "directionality": "directed",
    }
    actual = {
        "semantic_src_id": "NCM622 Cathode",
        "semantic_tgt_id": "Pouch Lithium-Ion Battery",
        "relation_type": "part_of",
        "directionality": "directed",
    }

    match = relation_match(expected, actual)
    assert match["score"] == 1
    assert match["inverse_matched"] is True
    assert relation_match({**expected, "accepted_inverse_relation_types": {}}, actual)["score"] == 0
    assert relation_match(
        {"source": "A", "target": "B", "relation_type": "causes",
         "directionality": "directed"},
        {"semantic_src_id": "B", "semantic_tgt_id": "A", "relation_type": "causes",
         "directionality": "directed"},
    )["score"] == 0


def test_graph_case_keeps_exact_status_but_uses_partial_relation_score():
    benchmark = {
        "cases": [
            {
                "id": "partial-causal",
                "expected_relations": [
                    {
                        "source": "Impurity",
                        "relation_type": "causes",
                        "target": "Capacity loss",
                        "directionality": "directed",
                    }
                ],
            }
        ]
    }
    _, summary = score_graph_cases(
        benchmark,
        [],
        [
            {
                "semantic_src_id": "Impurity",
                "semantic_tgt_id": "Capacity loss",
                "relation_type": "affects",
                "directionality": "directed",
            }
        ],
    )

    assert 0 < summary["relation_score"] < 100
    assert summary["relation_exact_score"] == 0.0


def test_path_score_awards_partial_credit_for_one_correct_hop():
    expected = {
        "nodes": ["Impurity", "Inert phase", "Capacity loss"],
        "relation_types": ["causes", "degrades"],
        "source_documents": ["components.pdf"],
        "require_citations": True,
    }
    actual = {
        "nodes": ["Impurity", "Inert phase", "Transport loss"],
        "edges": [
            {
                "source": "Impurity",
                "target": "Inert phase",
                "relation_type": "causes",
            },
            {
                "source": "Inert phase",
                "target": "Transport loss",
                "relation_type": "affects",
            },
        ],
        "file_paths": ["components.pdf"],
        "reference_ids": ["chunk-1"],
    }

    score = path_match(expected, actual)

    assert 0 < score["score"] < 1
    assert 0 < score["edge_recall"] < 1
    assert score["citation_coverage"] == 1


def test_path_evidence_cannot_credit_an_unrelated_chain():
    score = path_match(
        {
            "nodes": ["Electrolyte decomposition", "Gas generation", "Lithium plating"],
            "relation_types": ["causes", "causes"],
            "source_documents": ["aging.pdf"],
            "require_citations": True,
        },
        {
            "nodes": ["Aging", "Resistance", "Heat"],
            "edges": [
                {"source": "Aging", "target": "Resistance", "relation_type": "causes"},
                {"source": "Resistance", "target": "Heat", "relation_type": "causes"},
            ],
            "file_paths": ["aging.pdf"],
            "reference_ids": ["chunk-1"],
        },
    )

    assert score["edge_recall"] == 0
    assert score["score"] == 0


def test_path_score_is_capped_by_the_fraction_of_matching_hops():
    score = path_match(
        {
            "nodes": ["A", "B", "C", "D"],
            "relation_types": ["causes", "causes", "causes"],
        },
        {
            "nodes": ["A", "B", "C", "Wrong"],
            "edges": [
                {"source": "A", "target": "B", "relation_type": "causes"},
                {"source": "B", "target": "C", "relation_type": "causes"},
                {"source": "C", "target": "Wrong", "relation_type": "causes"},
            ],
        },
    )

    assert score["edge_recall"] == 0.6667
    assert score["score"] <= score["edge_recall"]


def test_inbound_path_uses_traversal_order_without_reversing_semantic_edges():
    score = path_match(
        {
            "traversal_nodes": ["Defect", "Uneven coating", "Process instability"],
            "relation_types": ["causes", "influences"],
        },
        {
            "nodes": ["Defect", "Uneven coating", "Process instability"],
            "edges": [
                {
                    "source": "Uneven coating",
                    "target": "Defect",
                    "relation_type": "causes",
                },
                {
                    "source": "Process instability",
                    "target": "Uneven coating",
                    "relation_type": "influences",
                },
            ],
        },
        traversal_direction="in",
    )

    assert score["edge_recall"] == 1
    assert score["direction_accuracy"] == 1


def test_benchmark_preflight_identifies_missing_declared_source_document():
    preflight = benchmark_document_preflight(
        {
            "document_scope": [{"file": "components.pdf"}],
            "cases": [{"expected_documents": ["modules.pdf"]}],
            "directed_cases": [],
        },
        ["components.pdf"],
    )

    assert preflight["compatible"] is False
    assert preflight["missing_documents"] == ["modules.pdf"]
