"""Bounded, evidence-visible formatting for exploratory graph paths."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from lightrag_mcp.evidence import propose_relation_span


CAUSAL_TYPES = frozenset(
    {
        "causes",
        "affects",
        "influences",
        "leads_to",
        "results_in",
        "increases",
        "decreases",
        "degrades",
        "improves",
        "promotes",
        "prevents",
        "reduces",
        "enables",
    }
)


TAXONOMY_PATH = (
    Path(__file__).resolve().parent.parent / "ontology" / "exploration_subjects_v1.json"
)


@lru_cache(maxsize=1)
def _taxonomy() -> dict[str, Any]:
    return json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))


def classify_subject(
    name: str, *, source_files: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Resolve exact aliases with optional file scope; unknown is explicit."""

    files = {Path(file).name.casefold() for file in source_files}
    matches = []
    for concept in _taxonomy()["concepts"]:
        if _normal(name) not in {_normal(alias) for alias in concept["aliases"]}:
            continue
        scope = {file.casefold() for file in concept.get("source_files", [])}
        if scope and not scope.intersection(files):
            continue
        matches.append(concept)
    scoped = [item for item in matches if item.get("source_files")]
    if scoped:
        matches = scoped
    if len(matches) > 1:
        return {"concept_id": None, "domains": [], "status": "ambiguous"}
    if not matches:
        domains = [
            domain
            for domain, terms in _taxonomy().get("fallback_terms", {}).items()
            if any(
                re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", name.casefold())
                for term in terms
            )
        ]
        return {
            "concept_id": None,
            "domains": domains,
            "status": "provisional_keyword" if domains else "unknown",
        }
    concept = matches[0]
    return {
        "concept_id": concept["id"],
        "domains": list(concept["domains"]),
        "status": _taxonomy()["review_status"],
    }


def classify_domain(name: str) -> str | None:
    """Legacy single-label view; exploration uses all subject labels."""

    domains = classify_subject(name)["domains"]
    return domains[0] if domains else None


def _normal(name: str) -> str:
    return " ".join(name.casefold().split())


def _valid_path(
    path: dict[str, Any], start: str, chunks: dict[str, dict[str, Any]]
) -> bool:
    nodes = path.get("nodes") or []
    edges = path.get("edges") or []
    if not (3 <= len(nodes) <= 5 and len(edges) == len(nodes) - 1):
        return False
    if _normal(str(nodes[0])) != _normal(start):
        return False
    for index, edge in enumerate(edges):
        if (
            edge.get("directionality") != "directed"
            or edge.get("relation_type") not in CAUSAL_TYPES
            or _normal(str(edge.get("source") or "")) != _normal(str(nodes[index]))
            or _normal(str(edge.get("target") or "")) != _normal(str(nodes[index + 1]))
            or not any(
                source_id in chunks for source_id in edge.get("source_ids") or []
            )
        ):
            return False
    return True


def format_exploration(
    payload: dict[str, Any], *, start: str, limit: int = 5,
    include_full_chunks: bool = False,
    max_paths_per_target: int = 1,
) -> dict[str, Any]:
    """Return diverse cross-domain candidates, never a synthesized direct edge."""

    data = payload.get("data") or {}
    diagnostics = (payload.get("metadata") or {}).get("directed_paths") or {}
    chunks = {
        str(chunk.get("chunk_id")): chunk
        for chunk in data.get("chunks") or []
        if isinstance(chunk, dict) and chunk.get("chunk_id")
    }
    references = {
        str(ref.get("file_path")): ref
        for ref in data.get("references") or []
        if isinstance(ref, dict) and ref.get("file_path")
    }
    suggested_starts = [
        str(entity.get("entity_name") or entity.get("entity_id"))
        for entity in data.get("entities") or []
        if isinstance(entity, dict)
        and (entity.get("entity_name") or entity.get("entity_id"))
        and _normal(start)
        in _normal(str(entity.get("entity_name") or entity.get("entity_id")))
    ][:10]
    start_subject = classify_subject(start)
    start_domains = set(start_subject["domains"])
    by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    target_counts: dict[str, int] = defaultdict(int)

    for path in diagnostics.get("paths") or []:
        if not isinstance(path, dict) or not _valid_path(path, start, chunks):
            continue
        nodes = path["nodes"]
        target = str(nodes[-1])
        first_files = tuple(
            str(chunks[source_id].get("file_path") or "")
            for source_id in path["edges"][0].get("source_ids") or []
            if source_id in chunks
        )
        last_files = tuple(
            str(chunks[source_id].get("file_path") or "")
            for source_id in path["edges"][-1].get("source_ids") or []
            if source_id in chunks
        )
        path_start = classify_subject(start, source_files=first_files)
        target_subject = classify_subject(target, source_files=last_files)
        target_domains = set(target_subject["domains"])
        if not path_start["domains"] or not target_domains:
            continue
        if set(path_start["domains"]).intersection(target_domains):
            continue
        target_key = _normal(target)
        if target_counts[target_key] >= max_paths_per_target:
            continue
        target_counts[target_key] += 1
        steps = []
        for edge in path["edges"]:
            sources = []
            for source_id in edge.get("source_ids") or []:
                chunk = chunks.get(source_id)
                if not chunk:
                    continue
                file_path = str(chunk.get("file_path") or "")
                ref = references.get(file_path) or {}
                source = {
                        "chunk_id": source_id,
                        "document": file_path,
                        "url": ref.get("url")
                        or ref.get("source_url")
                        or ref.get("download_url"),
                        "chunk_excerpt": str(chunk.get("content") or "")[:900],
                        "candidate_span": propose_relation_span(
                            str(chunk.get("content") or ""),
                            edge["source"],
                            edge["target"],
                        ),
                        "note": "Chunk excerpt; exact relation span not independently verified.",
                    }
                if include_full_chunks:
                    content = str(chunk.get("content") or "")
                    source["full_chunk_text"] = content[:12000]
                    source["full_chunk_truncated"] = len(content) > 12000
                sources.append(source)
                if len(sources) >= (3 if include_full_chunks else 1):
                    break
            steps.append(
                {
                    "source": edge["source"],
                    "relation": edge["relation_type"],
                    "target": edge["target"],
                    "description": edge.get("description") or "",
                    "available_source_count": len(edge.get("source_ids") or []),
                    "sources": sources,
                }
            )
        target_domain = sorted(target_domains)[0]
        by_domain[target_domain].append(
            {
                "from": start,
                "to": target,
                "start_domain": path_start["domains"][0],
                "target_domain": target_domain,
                "start_domains": path_start["domains"],
                "target_domains": target_subject["domains"],
                "start_concept_id": path_start["concept_id"],
                "target_concept_id": target_subject["concept_id"],
                "start_subject_status": path_start["status"],
                "target_subject_status": target_subject["status"],
                "taxonomy_status": _taxonomy()["review_status"],
                "hops": len(steps),
                "path": steps,
                "status": "unreviewed_indirect_connection",
            }
        )

    results: list[dict[str, Any]] = []
    while len(results) < limit and any(by_domain.values()):
        for domain in sorted(by_domain):
            if by_domain[domain] and len(results) < limit:
                results.append(by_domain[domain].pop(0))
    return {
        "start": start,
        "start_domain": start_subject["domains"][0] if start_domains else None,
        "start_domains": start_subject["domains"],
        "start_subject_status": start_subject["status"],
        "taxonomy_version": _taxonomy()["version"],
        "suggested_start_nodes": suggested_starts if not results else [],
        "connections": results,
        "candidate_count": sum(len(paths) for paths in by_domain.values())
        + len(results),
        "retrieval_status": diagnostics.get("status", "unknown"),
        "retrieval_reason": diagnostics.get("reason"),
        "paths_examined": len(diagnostics.get("paths") or []),
        "empty_reason": (
            "Starting node has no provisional subject classification."
            if not start_domains
            else "No directed, source-resolved cross-area path survived the filters."
            if not results
            else None
        ),
        "notice": (
            "Exploratory, unreviewed paths. Cross-domain labels use a provisional "
            "versioned taxonomy with provisional keyword fallback. Candidate "
            "spans only locate mentions, not proof. "
            "Each hop needs source and condition review; "
            "the endpoint pair is not a verified direct causal relation."
        ),
    }
