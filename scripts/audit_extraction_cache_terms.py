"""Report whether requested terms survived raw extraction and parsed artifacts.

Reads private prompt-experiment cache files locally; prints no raw prompt,
response, quote, or source text. A text mention is not a structured endpoint.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
from pathlib import Path
from typing import Any


def _norm(value: object) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _endpoint_names(payload: dict[str, Any]) -> set[str]:
    names = {str(entity.get("name") or "") for entity in payload.get("entities", []) if isinstance(entity, dict)}
    for relation in payload.get("relationships", []):
        if isinstance(relation, dict):
            names.update((str(relation.get("source") or ""), str(relation.get("target") or "")))
    return {_norm(name) for name in names if name}


def inspect(cache_path: Path, artifact_path: Path, terms: list[str]) -> dict[str, Any]:
    with gzip.open(cache_path, "rt", encoding="utf-8") as stream:
        cache = json.load(stream)
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    if len(artifact.get("documents", [])) != 1:
        raise ValueError("Expected one isolated document")
    parsed_names: set[str] = set()
    parsed_edges: list[dict[str, str]] = []
    for chunk in artifact["documents"][0].get("chunk_results", []):
        parsed_names.update(_norm(node.get("entity_id")) for node in chunk.get("nodes", []))
        for edge in chunk.get("edges", []):
            parsed_names.update((_norm(edge.get("source")), _norm(edge.get("target"))))
            for record in edge.get("records", []):
                parsed_edges.append({
                    "source": str(record.get("semantic_src_id") or edge.get("source") or ""),
                    "type": str(record.get("relation_type") or ""),
                    "target": str(record.get("semantic_tgt_id") or edge.get("target") or ""),
                })

    responses = [item for item in cache.values() if isinstance(item, dict) and isinstance(item.get("return"), str)]
    raw_names: set[str] = set()
    raw_text = []
    invalid = 0
    for item in responses:
        text = item["return"]
        raw_text.append(_norm(text))
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            invalid += 1
            continue
        if isinstance(payload, dict):
            raw_names.update(_endpoint_names(payload))
        else:
            invalid += 1
    return {
        "cache_records": len(responses),
        "unparseable_as_direct_json": invalid,
        "terms": {
            term: {
                "raw_text_mentions": sum(_norm(term) in text for text in raw_text),
                "raw_structured_endpoint": _norm(term) in raw_names,
                "parsed_structured_endpoint": _norm(term) in parsed_names,
                "raw_endpoint_contains": any(_norm(term) in name for name in raw_names),
                "parsed_endpoint_contains": any(_norm(term) in name for name in parsed_names),
                "raw_matching_endpoints": sorted(name for name in raw_names if _norm(term) in name)[:5],
                "parsed_matching_endpoints": sorted(name for name in parsed_names if _norm(term) in name)[:5],
                "parsed_matching_edges": [
                    edge for edge in parsed_edges
                    if _norm(term) in _norm(edge["source"])
                    or _norm(term) in _norm(edge["target"])
                ][:5],
            }
            for term in terms
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache", type=Path)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--term", action="append", required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.cache, args.artifact, args.term), indent=2))


if __name__ == "__main__":
    main()
