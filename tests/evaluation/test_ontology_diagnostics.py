import copy
import json
from pathlib import Path

import pytest

from lightrag.evaluation.ontology_diagnostics import score_ontology_edges
from lightrag.evaluation.live_benchmark import score_graph_cases


ROOT = Path(__file__).resolve().parents[2]
MAPPING_PATH = ROOT / "ontology" / "pem_mapping_v1.json"


def edge(source, relation_type, target, **extra):
    return {
        "source": source,
        "relation_type": relation_type,
        "target": target,
        **extra,
    }


def test_reports_raw_alias_mapped_iri_and_inverse_separately():
    cause_iri = "https://w3id.org/emmo#EMMO_d67ee67e_4fac_4676_82c9_aec361dba698"
    expected = [
        edge("A", "causes", "B", case_id="raw"),
        edge("C", "causes", "D", case_id="alias"),
        edge("E", "causes", "F", case_id="iri", relation_iri=cause_iri),
        edge("G", "causes", "H", case_id="inverse"),
    ]
    given = [
        edge("A", "causes", "B"),
        edge("C", "verursacht", "D"),
        edge("E", "external_label", "F", relation_iri=cause_iri),
        edge("H", "caused_by", "G"),
    ]

    result = score_ontology_edges(expected, given)

    assert [case["match_type"] for case in result["cases"]] == [
        "raw_exact",
        "alias_equivalent",
        "mapped_iri_exact",
        "inverse_equivalent",
    ]
    assert all(case["score"] == 1.0 for case in result["cases"])
    assert result["summary"]["mean_diagnostic_score"] == 1.0
    assert result["summary"]["false_positive_rate"] == 0.0


def test_inverse_requires_the_reviewed_endpoint_swap():
    result = score_ontology_edges(
        [edge("cause", "causes", "effect")],
        [edge("cause", "caused_by", "effect")],
    )

    assert result["cases"][0]["match_type"] == "missing"
    assert result["summary"]["false_positive_count"] == 1


def test_inverse_iri_also_requires_the_reviewed_endpoint_swap():
    direct_iri = "https://w3id.org/emmo#EMMO_d67ee67e_4fac_4676_82c9_aec361dba698"
    inverse_iri = "https://w3id.org/emmo#EMMO_6735d3ff_67f8_43b5_b5b0_240fbfab4517"
    expected = [edge("cause", "causes", "effect", relation_iri=direct_iri)]

    wrong = score_ontology_edges(
        expected,
        [edge("cause", "external", "effect", relation_iri=inverse_iri)],
    )
    correct = score_ontology_edges(
        expected,
        [edge("effect", "external", "cause", relation_iri=inverse_iri)],
    )

    assert wrong["cases"][0]["match_type"] == "missing"
    assert correct["cases"][0]["match_type"] == "inverse_equivalent"


def test_ambiguous_and_unmapped_relations_do_not_gain_equivalence_credit():
    result = score_ontology_edges(
        [edge("A", "affects", "B"), edge("C", "degrades", "D")],
        [edge("A", "affect", "B"), edge("C", "unknown_relation", "D")],
    )

    assert [case["match_type"] for case in result["cases"]] == ["missing", "missing"]
    assert result["summary"]["expected_unmapped_rate"] == 1.0
    assert result["summary"]["given_unmapped_rate"] == 1.0
    assert result["summary"]["false_positive_rate"] == 1.0


def test_conditional_mapping_is_not_an_asserted_equivalence():
    result = score_ontology_edges(
        [edge("Process", "produces", "Output")],
        [edge("Process", "erzeugt", "Output")],
    )
    assert result["cases"][0]["match_type"] == "missing"
    assert result["summary"]["expected_unmapped_rate"] == 1.0


def test_hierarchy_is_partial_only_when_explicitly_reviewed():
    mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    mapping["relations"].append(
        {
            "label": "drives",
            "status": "mapped",
            "iri": "urn:test:drives",
            "aliases": [],
        }
    )
    mapping["relation_hierarchy"] = [
        {"narrower": "causes", "broader": "drives", "reviewed": False}
    ]
    expected = [edge("A", "causes", "B")]
    given = [edge("A", "drives", "B")]

    unreviewed = score_ontology_edges(expected, given, mapping)
    reviewed_mapping = copy.deepcopy(mapping)
    reviewed_mapping["relation_hierarchy"][0]["reviewed"] = True
    reviewed = score_ontology_edges(expected, given, reviewed_mapping)

    assert unreviewed["cases"][0]["match_type"] == "missing"
    assert reviewed["cases"][0]["match_type"] == "hierarchy_partial"
    assert reviewed["cases"][0]["score"] == 0.5
    assert reviewed["cases"][0]["full_credit"] is False


def test_matching_is_one_to_one_and_extra_edges_are_false_positives():
    result = score_ontology_edges(
        [edge("A", "causes", "B")],
        [edge("A", "causes", "B"), edge("A", "causes", "B")],
    )

    assert result["summary"]["matched_count"] == 1
    assert result["summary"]["false_positive_count"] == 1
    assert result["summary"]["false_positive_rate"] == 0.5


def test_input_and_mapping_schema_are_validated():
    with pytest.raises(TypeError, match="must be lists"):
        score_ontology_edges({}, [])
    with pytest.raises(TypeError, match="must be a dictionary"):
        score_ontology_edges(["not an edge"], [])
    with pytest.raises(ValueError, match="schema_version 1"):
        score_ontology_edges([], [], {"schema_version": 2, "relations": []})


def test_live_benchmark_opt_in_adds_diagnostics_without_changing_scores():
    benchmark = {"cases": [{
        "id": "causal", "expected_relations": [edge("A", "causes", "B")]
    }]}
    nodes = [{"entity_id": "A"}, {"entity_id": "B"}]
    edges = [edge("A", "causes", "B")]
    baseline_cases, baseline_summary = score_graph_cases(benchmark, nodes, edges)
    benchmark["ontology_diagnostics"] = True
    annotated_cases, annotated_summary = score_graph_cases(benchmark, nodes, edges)
    assert annotated_summary == baseline_summary
    assert annotated_cases[0]["relation_score"] == baseline_cases[0]["relation_score"]
    assert "ontology_diagnostics" not in baseline_cases[0]
    assert annotated_cases[0]["ontology_diagnostics"]["cases"][0]["match_type"] == "raw_exact"
