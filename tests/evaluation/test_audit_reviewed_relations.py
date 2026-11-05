"""Offline reviewer decisions remain separate from benchmark scores."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.audit_reviewed_relations import audit, render_markdown


GOLD = Path("evaluation/reviews/aging_20261104_reviewed_relations.json")


def _artifact(*edges: tuple[str, str, str, str] | tuple[str, str, str, str, str]) -> dict:
    return {
        "documents": [
            {
                "doc_id": "doc-1",
                "file_path": "Heat Generation and Degradation Mechanism of Lithium-Ion Batteries during High-Temperature Aging.pdf",
                "source_fingerprint": "source-1",
                "selected_fingerprint": "chunks-1",
                "chunk_ids": ["chunk-1"],
                "chunk_results": [
                    {
                        "edges": [
                            {
                                "source": source,
                                "target": target,
                                "records": [
                                    {
                                        "relation_type": predicate,
                                        "directionality": direction,
                                        "source_id": "chunk-1",
                                        "description": edge[4] if len(edge) > 4 else "",
                                    }
                                ],
                            }
                            for edge in edges
                            for source, predicate, target, direction in [edge[:4]]
                        ]
                    }
                ],
            }
        ]
    }


def test_review_gold_is_unique_and_source_anchored():
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    ids = [case["id"] for case in gold["cases"]]

    assert len(ids) == len(set(ids)) == 15
    assert all(case["pages"] and case["direct"] for case in gold["cases"])
    assert all(case["pdf_support"].startswith("supported") for case in gold["cases"])


def test_reviewed_alias_is_direct_but_shortcut_is_not():
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    baseline = _artifact(
        ("Transition-Metal Dissolution", "influences", "Side Reactions", "directed"),
        ("Local Electrolyte Drying", "causes", "Nonuniform Local Current", "directed"),
    )
    variant = _artifact(
        ("Transition-Metal Dissolution", "influences", "Side Reaction", "directed"),
        ("Local Electrolyte Drying", "leads_to", "Nonuniform Local Current", "directed"),
    )

    report = audit(gold, baseline, variant)
    cases = {case["id"]: case for case in report["cases"]}

    assert cases["G07"]["baseline"]["status"] == "direct_match"
    assert cases["G07"]["variant"]["status"] == "direct_match"
    assert cases["G01"]["baseline"]["status"] == "related_only"
    assert cases["G01"]["variant"]["status"] == "related_only"
    assert cases["G02"]["variant"]["status"] == "related_only"
    assert "independent verification" in render_markdown(report)


def test_reverse_and_undirected_edges_do_not_get_direct_credit():
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    reverse = _artifact(
        ("Loss Of Lithium Inventory", "causes", "Lithium Plating", "directed"),
        ("Transition-Metal Dissolution", "influences", "Side Reactions", "undirected"),
    )
    report = audit(gold, reverse, reverse)
    cases = {case["id"]: case for case in report["cases"]}

    assert cases["G05"]["baseline"]["status"] == "missing"
    assert cases["G07"]["baseline"]["status"] == "missing"


def test_artifacts_must_use_the_same_frozen_chunks():
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    baseline = _artifact()
    variant = _artifact()
    variant["documents"][0]["selected_fingerprint"] = "other"

    with pytest.raises(ValueError, match="selected_fingerprint"):
        audit(gold, baseline, variant)


def test_two_chunk_report_only_counts_explicitly_selected_cases():
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    artifact = _artifact()
    report = audit(gold, artifact, artifact, {"G01", "G02", "R01"})

    assert [case["id"] for case in report["cases"]] == ["G01", "G02", "R01"]
    assert report["baseline_summary"] == {"missing": 3}
    with pytest.raises(ValueError, match="Unknown reviewed case IDs"):
        audit(gold, artifact, artifact, {"not-reviewed"})


def test_reversed_causal_claims_are_flagged_separately_from_recall():
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    baseline = _artifact()
    variant = _artifact(
        ("Side Reactions", "influences", "Transition-Metal Dissolution", "directed"),
        ("Deteriorated Electrochemical Performance", "causes", "High-Temperature Aging", "directed"),
    )

    report = audit(gold, baseline, variant, {"G07"})

    assert report["baseline_forbidden"] == []
    assert {item["id"] for item in report["variant_forbidden"]} == {
        "reverse_transition_metal", "reverse_aging",
    }
    assert report["cases"][0]["variant"]["status"] == "missing"


def test_reviewed_diffusion_difficulty_alias_is_not_generic_diffusion():
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    specific = _artifact(
        ("Lithium Ion Diffusion Difficulty In Active Material Particles", "increases", "Warburg Resistance", "directed")
    )
    generic = _artifact(
        ("Lithium Ion Diffusion", "increases", "Warburg Resistance", "directed")
    )

    report = audit(gold, generic, specific, {"R01"})

    assert report["cases"][0]["baseline"]["status"] == "missing"
    assert report["cases"][0]["variant"]["status"] == "direct_match"


def test_case_specific_predicates_and_signed_diffusion_variants():
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    artifact = _artifact(
        ("Local Potential Change", "influences", "Nonuniform Local Current", "directed"),
        ("Gas Generation", "affects", "Electrode Distance Change", "directed"),
        ("Electrode Distance Change", "leads_to", "Local Current Nonuniformity", "directed"),
        ("Increased Lithium-Ion Diffusion Difficulty", "increases", "Warburg Resistance", "directed"),
    )
    report = audit(gold, artifact, artifact, {"G02", "G03", "G04", "R01"})
    assert all(case["baseline"]["status"] == "direct_match" for case in report["cases"])
    assert report["chains"][0]["baseline"]["status"] == "direct_chain"


def test_generic_intermediate_requires_description_and_gets_partial_chain():
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    variant = _artifact(
        ("Local Electrolyte Drying", "changes", "Local Potential", "directed",
         "Local electrolyte drying causes the local potential to change."),
        ("Local Potential", "affects", "Nonuniform Local Current", "directed",
         "Local potential change contributes to nonuniform local current during recharging."),
    )
    report = audit(gold, _artifact(), variant, {"G01", "G02"})
    assert [case["variant"]["status"] for case in report["cases"]] == [
        "state_in_description_only", "state_in_description_only",
    ]
    chain = report["chains"][0]["variant"]
    assert chain["status"] == "partial_chain"
    assert chain["matched_paths"][0]["first"]["target"] == "Local Potential"
    assert chain["matched_paths"][0]["second"]["source"] == "Local Potential"


def test_generic_state_without_explicit_change_is_not_credited():
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    artifact = _artifact(
        ("Local Electrolyte Drying", "changes", "Local Potential", "directed",
         "Local electrolyte drying and local potential were observed."),
        ("Local Potential", "affects", "Nonuniform Local Current", "directed",
         "Local potential and nonuniform local current were observed."),
        ("Gas Generation", "increases", "Electrode Distance Change", "directed",
         "Generated gas changes the distance; the sign is not known."),
    )
    report = audit(gold, artifact, artifact, {"G01", "G02", "G03"})
    assert all(case["baseline"]["status"] == "missing" for case in report["cases"])
    assert report["chains"][0]["baseline"]["status"] == "missing_chain"


def test_shortcut_disconnected_and_reverse_paths_never_complete_chain():
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    artifact = _artifact(
        ("Gas Generation", "leads_to", "Local Current Nonuniformity", "directed"),
        ("Gas Generation", "affects", "Electrode Distance Change", "directed"),
        ("Changed Electrode Spacing", "leads_to", "Local Current Nonuniformity", "directed"),
        ("Local Current Nonuniformity", "leads_to", "Electrode Distance Change", "directed"),
    )
    report = audit(gold, artifact, artifact, {"G03", "G04"})
    assert all(case["baseline"]["status"] == "direct_match" for case in report["cases"])
    assert report["chains"][0]["baseline"]["status"] == "missing_chain"
