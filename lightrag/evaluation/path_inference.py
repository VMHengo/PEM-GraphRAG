"""Conservative, explainable composition of exploratory path predicates."""

from __future__ import annotations

from typing import Any


RULE_VERSION = "1"
_SIGNED = {"increases": 1, "decreases": -1}
_CAUSAL = {"causes", "results_in", "leads_to"}
_UNSIGNED = {
    "affects",
    "influences",
    "promotes",
    "enables",
    "degrades",
    "improves",
    "reduces",
}
_CONTEXT_CAVEAT = (
    "Conditions and competing pathways have not been checked automatically."
)


def _normal(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def infer_indirect_connection(candidate: dict[str, Any]) -> dict[str, Any]:
    """Describe a path hypothesis, never a new direct graph assertion."""

    path = candidate.get("path") or []
    base: dict[str, Any] = {
        "relation": None,
        "label": "No indirect relation derived",
        "polarity": None,
        "status": "not_composable",
        "rule": "invalid_path",
        "rule_version": RULE_VERSION,
        "caveats": [],
        "path_hops": len(path),
    }
    if not 2 <= len(path) <= 4 or not all(isinstance(hop, dict) for hop in path):
        base["caveats"] = ["A complete 2-4-hop path is required."]
        return base
    if (
        _normal(path[0].get("source")) != _normal(candidate.get("from"))
        or _normal(path[-1].get("target")) != _normal(candidate.get("to"))
        or any(
            not _normal(left.get("target"))
            or _normal(left.get("target")) != _normal(right.get("source"))
            for left, right in zip(path, path[1:])
        )
    ):
        base["rule"] = "broken_path"
        base["caveats"] = ["The displayed hops do not form a continuous directed path."]
        return base
    if any(
        not any(
            source.get("full_chunk_text") or source.get("chunk_excerpt")
            for source in hop.get("sources") or []
        )
        for hop in path
    ):
        base["rule"] = "missing_source"
        base["caveats"] = ["At least one hop has no resolved source text."]
        return base

    relations = [str(hop.get("relation") or "").casefold().strip() for hop in path]
    unsupported = sorted(set(relations) - set(_SIGNED) - _CAUSAL - _UNSIGNED)
    if unsupported:
        base["rule"] = "unsupported_predicate"
        base["caveats"] = [
            f"No causal composition rule exists for: {', '.join(unsupported)}."
        ]
        return base

    if all(relation in _SIGNED for relation in relations):
        sign = 1
        for relation in relations:
            sign *= _SIGNED[relation]
        direction = "increases" if sign > 0 else "decreases"
        base.update(
            relation=f"indirectly_{direction}",
            label=f"may indirectly {'increase' if sign > 0 else 'decrease'}",
            polarity="positive" if sign > 0 else "negative",
            status="candidate",
            rule="signed_monotonic_composition",
            caveats=[
                "Signed composition assumes monotonic, comparable variables across all hops.",
                _CONTEXT_CAVEAT,
            ],
        )
    elif all(relation in _CAUSAL for relation in relations):
        base.update(
            relation="may_indirectly_lead_to",
            label="may indirectly lead to",
            polarity="unknown",
            status="candidate",
            rule="causal_chain",
            caveats=[_CONTEXT_CAVEAT],
        )
    else:
        base.update(
            relation="may_indirectly_affect",
            label="may indirectly affect",
            polarity="unknown",
            status="candidate",
            rule="unsigned_or_mixed_influence",
            caveats=[
                "At least one predicate lacks a composable sign or causal guarantee.",
                _CONTEXT_CAVEAT,
            ],
        )
    return base
