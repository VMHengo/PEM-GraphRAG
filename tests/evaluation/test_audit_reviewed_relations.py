"""Offline reviewer decisions remain separate from benchmark scores."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.audit_reviewed_relations import audit, render_markdown


GOLD = Path("evaluation/reviews/aging_20261104_reviewed_relations.json")


def _artifact(*edges: tuple[str, str, str, str]) -> dict:
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
                                    }
                                ],
                            }
                            for source, predicate, target, direction in edges
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
