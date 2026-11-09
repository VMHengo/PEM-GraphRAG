"""Read-only comparison of directed paths with and without curated aliases."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re

CAUSAL_TYPES = frozenset({
    "causes", "affects", "influences", "leads_to", "results_in",
    "increases", "decreases", "degrades", "improves", "promotes",
    "prevents", "reduces", "enables",
})
MAX_EDGES = 10000
MAX_PATHS = 100000
STATE_WORDS = frozenset({"higher", "lower", "increased", "decreased", "reduced", "elevated"})


def _alias_key(label: str) -> str:
    words = label.casefold().split()
    return " ".join(words[:-1] + [re.sub(r"s$", "", words[-1])]) if words else ""


def suggest_aliases(edges: list[dict], approved: dict[str, str]) -> list[dict]:
    """Offer lexical leads near causal edges; never promote them automatically."""
    incident: dict[str, int] = defaultdict(int)
    for edge in edges:
        if edge["relation_type"] in CAUSAL_TYPES:
            incident[edge["source"]] += 1
            incident[edge["target"]] += 1
    groups: dict[str, set[str]] = defaultdict(set)
    for label in {name for edge in edges for name in (edge["source"], edge["target"])}:
        if label and label.casefold().split()[0] not in STATE_WORDS:
            groups[_alias_key(label)].add(label)
    proposals = []
    for names in groups.values():
        for left in sorted(names):
            for right in sorted(names):
                if left >= right or not (incident[left] and incident[right]):
                    continue
                if approved.get(left) == approved.get(right) and left in approved:
                    continue
                proposals.append({
                    "left": left, "right": right,
                    "causal_incident_left": incident[left],
                    "causal_incident_right": incident[right],
                    "status": "review_required",
                })
    return sorted(proposals, key=lambda item: (
        -min(item["causal_incident_left"], item["causal_incident_right"]),
        item["left"], item["right"],
    ))


def load_aliases(data: dict) -> dict[str, str]:
    if data.get("version") != 1 or not isinstance(data.get("concepts"), list):
        raise ValueError("Alias file must have version 1 and concepts list")
    mapping: dict[str, str] = {}
    for concept in data["concepts"]:
        canonical = concept["canonical"]
        for label in [canonical, *concept["aliases"]]:
            if not isinstance(label, str) or not label.strip():
                raise ValueError("Empty alias label")
            if label in mapping and mapping[label] != canonical:
                raise ValueError(f"Conflicting alias: {label}")
            mapping[label] = canonical
    return mapping


def prepare_edges(data: dict) -> list[dict]:
    records = data.get("edges")
    if not isinstance(records, list) or len(records) > MAX_EDGES:
        raise ValueError("Expected a bounded edges list")
    edges = []
    seen_ids = set()
    for index, record in enumerate(records):
        if record.get("directionality") != "directed":
            continue
        source = record.get("semantic_src_id")
        target = record.get("semantic_tgt_id")
        if not source or not target or source == target:
            continue
        edge_id = str(record.get("id", index))
        if edge_id in seen_ids:
            raise ValueError(f"Duplicate edge id: {edge_id}")
        seen_ids.add(edge_id)
        edges.append({
            "id": edge_id,
            "source": source,
            "target": target,
            "relation_type": str(record.get("relation_type") or "unknown").lower(),
            "source_id": record.get("source_id"),
            "file_path": record.get("file_path"),
            "description": record.get("description"),
        })
    return edges


def _paths(edges: list[dict], aliases: dict[str, str], max_hops: int) -> dict[tuple[str, ...], dict]:
    adjacency = defaultdict(list)
    for edge in edges:
        adjacency[aliases.get(edge["source"], edge["source"])].append(edge)
    found = {}

    def visit(node: str, nodes: tuple[str, ...], chain: tuple[dict, ...]) -> None:
        if len(chain) >= 2:
            key = tuple(edge["id"] for edge in chain)
            found[key] = {
                "concept_nodes": list(nodes),
                "original_nodes": [chain[0]["source"], *(edge["target"] for edge in chain)],
                "hops": chain,
                "causal_only": all(edge["relation_type"] in CAUSAL_TYPES for edge in chain),
                "mixed_causal": any(edge["relation_type"] in CAUSAL_TYPES for edge in chain)
                and not all(edge["relation_type"] in CAUSAL_TYPES for edge in chain),
            }
            if len(found) > MAX_PATHS:
                raise ValueError("Path cap exceeded; reduce the export scope")
        if len(chain) == max_hops:
            return
        for edge in adjacency[node]:
            target = aliases.get(edge["target"], edge["target"])
            if target not in nodes:
                visit(target, (*nodes, target), (*chain, edge))

    for node in sorted(adjacency):
        visit(node, (node,), ())
    return found


def replay(graph: dict, alias_file: dict, max_hops: int = 4) -> dict:
    if not 2 <= max_hops <= 4:
        raise ValueError("max_hops must be between 2 and 4")
    aliases = load_aliases(alias_file)
    edges = prepare_edges(graph)
    baseline = _paths(edges, {}, max_hops)
    projected = _paths(edges, aliases, max_hops)
    additional = [path for key, path in projected.items() if key not in baseline]
    additional.sort(key=lambda path: (len(path["hops"]), tuple(h["id"] for h in path["hops"])))
    mixed = [path for path in additional if path["mixed_causal"]]
    return {
        "alias_version": alias_file["version"],
        "edge_count": len(edges),
        "baseline_path_count": len(baseline),
        "projected_path_count": len(projected),
        "additional_path_count": len(additional),
        "causal_additional_count": sum(path["causal_only"] for path in additional),
        "mixed_additional_count": len(mixed),
        "suggested_aliases": suggest_aliases(edges, aliases),
        "additional_paths": additional,
        "causal_additional_paths": [path for path in additional if path["causal_only"]],
        "mixed_additional_paths": mixed,
    }


def render_review(result: dict, limit: int = 20) -> str:
    """Render a compact, explicitly unverified sample for source review."""
    prioritized = sorted(result["additional_paths"], key=lambda path: (
        not path["causal_only"], not path["mixed_causal"],
        len(path["hops"]), tuple(edge["id"] for edge in path["hops"]),
    ))
    lines = [
        "# Alias path review",
        "",
        "Candidate paths only. Check each original source before accepting a bridge.",
        "",
        f"Baseline: {result['baseline_path_count']} | Projected: {result['projected_path_count']} "
        f"| Additional: {result['additional_path_count']} "
        f"| Causal: {result['causal_additional_count']} "
        f"| Mixed: {result['mixed_additional_count']}",
        "",
    ]
    for number, path in enumerate(prioritized[:limit], 1):
        category = "causal" if path["causal_only"] else "mixed" if path["mixed_causal"] else "other"
        lines += [f"## {number}. {category} candidate", ""]
        for hop in path["hops"]:
            lines.append(f"- {hop['source']} --[{hop['relation_type']}]--> {hop['target']}")
            lines.append(f"  Source: {hop['source_id'] or 'missing'} | File: {hop['file_path'] or 'unknown'}")
            if hop["description"]:
                lines.append(f"  Description: {str(hop['description']).replace(chr(10), ' ')[:300]}")
        lines += ["- [ ] Both hops source-supported and semantically composable", ""]
    if result["suggested_aliases"]:
        lines += ["## Unapproved lexical leads", ""]
        for item in result["suggested_aliases"][:limit]:
            lines.append(f"- [ ] {item['left']} / {item['right']} "
                         f"(causal incident: {item['causal_incident_left']}, "
                         f"{item['causal_incident_right']})")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph", type=Path)
    parser.add_argument("aliases", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--max-hops", type=int, default=4)
    parser.add_argument("--review-markdown", type=Path)
    args = parser.parse_args()
    result = replay(
        json.loads(args.graph.read_text(encoding="utf-8")),
        json.loads(args.aliases.read_text(encoding="utf-8")),
        args.max_hops,
    )
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.review_markdown:
        args.review_markdown.write_text(render_review(result), encoding="utf-8")
    print({key: value for key, value in result.items()
           if not key.endswith("_paths") and key != "suggested_aliases"})


if __name__ == "__main__":
    main()
