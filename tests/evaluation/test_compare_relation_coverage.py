"""Frozen extraction comparison is conservative and document scoped."""

import pytest

from scripts.compare_relation_coverage import compare_review, render_markdown


def _inputs():
    name = "aging.pdf"
    sample = {
        "seed": 42,
        "documents": [{"file_name": name, "sha256": "abc", "sample": [
            {"id": "p1", "page": 1, "text": "A increases B.",
             "context_before": "", "context_after": ""},
        ]}],
    }
    review = {
        "schema_version": 1, "seed": 42,
        "documents": [{"file_name": name, "sha256": "abc"}],
        "reviews": {"p1": {"eligible_fact": "yes", "gold_assertions": [
            {"source": "A", "predicate": "increases", "target": "B",
             "evidence": "A increases B.", "conditions": "during discharge"},
        ]}},
    }
    coverage = {
        "schema_version": 1, "document_name": name,
        "document_id": "doc-aging", "fingerprint": "frozen",
        "relations": [{"source": "A", "predicate": "increases", "target": "B",
                       "chunk_id": "chunk-1", "description": "A increases B."}],
    }
    return sample, review, coverage


def test_exact_labels_do_not_certify_conditions():
    result = compare_review(*_inputs())
    assert result["outcomes"] == {"exact_labels_condition_unverified": 1}
    assert result["rows"][0]["condition_status"] == "not_evaluated"
    assert result["rows"][0]["evidence_status"] == "located_in_sample_context"
    assert "Decision: **pending human review**" in render_markdown(result)


def test_signed_qualifier_does_not_become_exact():
    sample, review, coverage = _inputs()
    review["reviews"]["p1"]["gold_assertions"][0]["predicate"] = "increase significantly"
    result = compare_review(sample, review, coverage)
    assert result["rows"][0]["outcome"] == "candidate_requires_review"
    assert result["rows"][0]["predicate_qualifier"] == "significantly"


def test_typo_only_produces_lexical_lead_not_match():
    sample, review, coverage = _inputs()
    review["reviews"]["p1"]["gold_assertions"][0]["source"] = "Degredation"
    coverage["relations"][0]["source"] = "Cell Degradation"
    result = compare_review(sample, review, coverage)
    row = result["rows"][0]
    assert row["outcome"] == "no_match_under_conservative_rules"
    assert row["lexical_leads_not_matches"][0]["source"] == "Cell Degradation"


def test_rejects_wrong_sample_or_noneligible_gold():
    sample, review, coverage = _inputs()
    review["documents"][0]["sha256"] = "wrong"
    with pytest.raises(ValueError, match="PDF versions"):
        compare_review(sample, review, coverage)
    review["documents"][0]["sha256"] = "abc"
    review["reviews"]["p1"]["eligible_fact"] = "no"
    with pytest.raises(ValueError, match="Non-eligible"):
        compare_review(sample, review, coverage)


def test_rejects_unreviewed_or_unknown_passage():
    sample, review, coverage = _inputs()
    review["reviews"]["extra"] = {"eligible_fact": "no"}
    with pytest.raises(ValueError, match="unknown passage"):
        compare_review(sample, review, coverage)
    del review["reviews"]["extra"]
    del review["reviews"]["p1"]
    with pytest.raises(ValueError, match="not reviewed"):
        compare_review(sample, review, coverage)
