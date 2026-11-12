import json
from pathlib import Path

import pytest

from scripts.rank_alias_paths import assess_path, compare, load_policy, render_comparison


POLICY = json.loads(Path("evaluation/aliases/path_policy_v1.json").read_text(encoding="utf-8"))


def path(identifier, first, second, *, source=True, bridge="Model"):
    hops = [
        {"id": f"{identifier}-1", "source": "Start", "target": bridge,
         "relation_type": first, "source_id": "chunk-1" if source else None, "file_path": "a.pdf"},
        {"id": f"{identifier}-2", "source": bridge + "s", "target": "Target",
         "relation_type": second, "source_id": "chunk-2", "file_path": "b.pdf"},
    ]
    return {"hops": hops, "concept_nodes": ["Start", bridge, "Target"],
            "causal_only": first == second == "causes", "mixed_causal": "causes" in (first, second)}


def test_invalid_method_to_causal_bridge_is_blocked():
    assert assess_path(path("x", "measures", "causes"), POLICY)["status"] == "blocked"


def test_methodological_bridge_stays_candidate_not_proven():
    assessment = assess_path(path("x", "produces", "measures"), POLICY)
    assert assessment["status"] == "review_candidate"
    assert assessment["categories"] == ["functional", "method"]


def test_missing_source_and_unknown_predicate_require_check():
    assessment = assess_path(path("x", "causes", "novel", source=False), POLICY)
    assert assessment["status"] == "needs_check"
    assert "missing_source_id" in assessment["issues"]


def test_policy_conflicts_rejected():
    with pytest.raises(ValueError, match="Conflicting"):
        load_policy({**POLICY, "review_pairs": POLICY["review_pairs"] + [["method", "causal"]]})


def test_comparison_keeps_sources_and_is_deterministic():
    paths = [path("bad", "studies", "causes"), path("good", "causes", "causes"),
             path("method", "produces", "measures", bridge="Prediction")]
    result = {"additional_paths": paths, "alias_version": 1}
    first = compare(result, POLICY, limit=2, pool_size=3)
    assert first == compare(result, POLICY, limit=2, pool_size=3)
    assert first["triage_counts"]["blocked"] == 1
    assert len(first["policy_top"]) == 2
    assert "chunk-2" in render_comparison(first)
    assert all(item["assessment"]["status"] != "blocked" for item in first["policy_top"])


def test_no_unverified_path_is_called_supported():
    result = compare({"additional_paths": [path("x", "causes", "causes")]}, POLICY)
    assert "review_candidate" == result["policy_top"][0]["assessment"]["status"]
    assert "do not verify" in result["warning"]
