"""Compare current alias-path ordering with a versioned offline triage policy."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path


def load_policy(data: dict) -> dict:
    if data.get("version") != 1 or not isinstance(data.get("categories"), dict):
        raise ValueError("Expected version 1 and relation categories")
    seen = set()
    for labels in data["categories"].values():
        if not isinstance(labels, list) or not labels or seen.intersection(labels):
            raise ValueError("Empty or overlapping categories")
        seen.update(labels)
    for field in ("blocked_pairs", "review_pairs"):
        if not isinstance(data.get(field), list):
            raise ValueError(f"Missing {field}")
        for pair in data[field]:
            if not isinstance(pair, list) or len(pair) != 2 or any(
                label not in data["categories"] for label in pair
            ):
                raise ValueError(f"Invalid {field} entry")
    if set(map(tuple, data["blocked_pairs"])) & set(map(tuple, data["review_pairs"])):
        raise ValueError("Conflicting pair rules")
    return data


def assess_path(path: dict, policy: dict) -> dict:
    categories = {relation.casefold(): name for name, relations in policy["categories"].items()
                  for relation in relations}
    hops = path["hops"]
    labels = [categories.get(str(hop.get("relation_type", "")).casefold(), "unknown")
              for hop in hops]
    issues = []
    if any(not hop.get("source_id") for hop in hops):
        issues.append("missing_source_id")
    if any(not hop.get("file_path") for hop in hops):
        issues.append("missing_document")
    if "unknown" in labels:
        issues.append("unknown_predicate")
    blocked = set(map(tuple, policy["blocked_pairs"]))
    reviewed = set(map(tuple, policy["review_pairs"]))
    for pair in zip(labels, labels[1:]):
        if pair in blocked:
            issues.append("blocked_composition:" + ">".join(pair))
        elif pair not in reviewed:
            issues.append("unclassified_composition:" + ">".join(pair))
    status = ("blocked" if any(issue.startswith("blocked_composition:") for issue in issues)
              else "needs_check" if issues else "review_candidate")
    # A triage rank, never a calibrated confidence or factual-support score.
    rank = (2 if status == "review_candidate" else 1 if status == "needs_check" else 0,
            sum(bool(hop.get("source_id")) for hop in hops),
            sum(bool(hop.get("file_path")) for hop in hops), -len(hops))
    return {"status": status, "categories": labels, "issues": issues, "rank": rank}


def _identity(path: dict) -> tuple[str, ...]:
    return tuple(str(hop["id"]) for hop in path["hops"])


def _select(pool: list[dict], limit: int) -> list[dict]:
    selected = []
    endpoints = set()
    bridges = set()
    used_edges = set()
    remaining = sorted(pool, key=_identity, reverse=True)
    while remaining and len(selected) < limit:
        best = max(remaining, key=lambda path: (
            path["assessment"]["rank"],
            (path["hops"][0]["source"], path["hops"][-1]["target"]) not in endpoints,
            tuple(path["concept_nodes"][1:-1]) not in bridges,
            -sum(hop["id"] in used_edges for hop in path["hops"]),
        ))
        remaining.remove(best)
        selected.append(best)
        endpoints.add((best["hops"][0]["source"], best["hops"][-1]["target"]))
        bridges.add(tuple(best["concept_nodes"][1:-1]))
        used_edges.update(hop["id"] for hop in best["hops"])
    return selected


def compare(result: dict, policy_data: dict, limit: int = 20, pool_size: int = 100) -> dict:
    policy = load_policy(policy_data)
    if not 1 <= limit <= pool_size <= 1000:
        raise ValueError("Expected 1 <= limit <= pool_size <= 1000")
    assessed = [{**path, "assessment": assess_path(path, policy)}
                for path in result["additional_paths"]]
    current = sorted(assessed, key=lambda path: (
        not path["causal_only"], not path["mixed_causal"], len(path["hops"]),
        _identity(path)))[:limit]
    eligible = [path for path in assessed if path["assessment"]["status"] != "blocked"]
    pool = sorted(eligible, key=lambda path: (
        tuple(-value for value in path["assessment"]["rank"]), _identity(path)))[:pool_size]
    proposed = _select(pool, limit)
    return {
        "policy_version": policy["version"], "alias_version": result.get("alias_version"),
        "candidate_count": len(assessed), "pool_size": pool_size, "review_limit": limit,
        "triage_counts": dict(Counter(path["assessment"]["status"] for path in assessed)),
        "current_top": current, "policy_top": proposed,
        "overlap": len({_identity(path) for path in current} & {_identity(path) for path in proposed}),
        "candidates": assessed,
        "warning": "Offline triage only. Source IDs and descriptions do not verify original passages or path entailment.",
    }


def render_comparison(result: dict) -> str:
    lines = ["# Alias path policy comparison", "", result["warning"], "",
             f"Candidates: {result['candidate_count']} | Triage: {result['triage_counts']}",
             f"Top-list overlap: {result['overlap']} | Pool: {result['pool_size']}", ""]
    for title, key in (("Current causal-first selection", "current_top"),
                       ("Policy-ranked selection", "policy_top")):
        lines.extend([f"## {title}", ""])
        for index, path in enumerate(result[key], 1):
            assessment = path["assessment"]
            lines.extend([f"### {index}. {assessment['status']}",
                          f"Issues: {', '.join(assessment['issues']) or 'none detected by triage'}"])
            for hop in path["hops"]:
                lines.append(f"- {hop['source']} --[{hop['relation_type']}]--> {hop['target']} "
                             f"| {hop.get('file_path') or 'unknown file'} "
                             f"| {hop.get('source_id') or 'missing chunk'}")
            lines.extend(["- [ ] Original passages support every hop",
                          "- [ ] Bridge identity and conditions compatible",
                          "- [ ] Full path informative and composable", ""])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay", type=Path)
    parser.add_argument("policy", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--review-markdown", type=Path)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--pool-size", type=int, default=100)
    args = parser.parse_args()
    result = compare(json.loads(args.replay.read_text(encoding="utf-8")),
                     json.loads(args.policy.read_text(encoding="utf-8")),
                     args.limit, args.pool_size)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.review_markdown:
        args.review_markdown.write_text(render_comparison(result), encoding="utf-8")
    print({key: result[key] for key in ("candidate_count", "triage_counts", "overlap")})


if __name__ == "__main__":
    main()
