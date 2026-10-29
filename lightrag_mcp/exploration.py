"""Bounded, evidence-visible formatting for exploratory graph paths."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from lightrag_mcp.evidence import propose_relation_context, propose_relation_span
from lightrag_mcp.source_links import source_pdf_url


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


def domain_distance(
    start_domains: list[str], target_domains: list[str]
) -> tuple[float | None, str | None, str | None]:
    """Use the nearest plausible domain pair so multi-label terms are not overrated."""

    positions = _taxonomy().get("domain_positions", {})
    pairs = []
    for start in start_domains:
        for target in target_domains:
            if start in positions and target in positions:
                a, b = positions[start], positions[target]
                pairs.append((math.hypot(a[0] - b[0], a[1] - b[1]), start, target))
    if not pairs:
        return None, None, None
    return min(pairs)


def _normal(name: str) -> str:
    return " ".join(name.casefold().split())


def _invalid_path_reason(
    path: dict[str, Any], start: str, chunks: dict[str, dict[str, Any]]
) -> str | None:
    nodes = path.get("nodes") or []
    edges = path.get("edges") or []
    if not (3 <= len(nodes) <= 5 and len(edges) == len(nodes) - 1):
        return "unsupported_path_length"
    if _normal(str(nodes[0])) != _normal(start):
        return "different_start_node"
    for index, edge in enumerate(edges):
        if edge.get("directionality") != "directed" or edge.get("relation_type") not in CAUSAL_TYPES:
            return "unsupported_edge"
        if (
            _normal(str(edge.get("source") or "")) != _normal(str(nodes[index]))
            or _normal(str(edge.get("target") or "")) != _normal(str(nodes[index + 1]))
        ):
            return "edge_order_mismatch"
        if not any(source_id in chunks for source_id in edge.get("source_ids") or []):
            return "missing_source_chunk"
    return None


def _valid_path(
    path: dict[str, Any], start: str, chunks: dict[str, dict[str, Any]]
) -> bool:
    return _invalid_path_reason(path, start, chunks) is None


def format_exploration(
    payload: dict[str, Any], *, start: str, limit: int = 5,
    include_full_chunks: bool = False,
    max_paths_per_target: int = 1,
    public_webui_base_url: str = "",
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
    candidates: list[dict[str, Any]] = []
    target_counts: dict[str, int] = defaultdict(int)
    excluded: dict[str, int] = defaultdict(int)

    for path in diagnostics.get("paths") or []:
        reason = (
            _invalid_path_reason(path, start, chunks)
            if isinstance(path, dict) else "unsupported_path_length"
        )
        if reason:
            excluded[reason] += 1
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
        distance, start_domain, target_domain = domain_distance(
            path_start["domains"], target_subject["domains"]
        )
        target_key = _normal(target)
        if target_counts[target_key] >= max_paths_per_target:
            excluded["target_diversity_limit"] += 1
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
                chunk_doc_match = re.fullmatch(r"(doc-[0-9a-f]{32})-chunk-\d+", source_id)
                chunk_doc_id = chunk.get("full_doc_id") or (
                    chunk_doc_match.group(1) if chunk_doc_match else None
                )
                source = {
                        "chunk_id": source_id,
                        "document": file_path,
                        "document_id": chunk_doc_id,
                        "pdf_url": source_pdf_url(
                            public_webui_base_url, chunk_doc_id
                        ),
                        "pdf_location": chunk.get("pdf_location"),
                        "evidence_quote": edge.get("evidence") or None,
                        "url": ref.get("url")
                        or ref.get("source_url")
                        or ref.get("download_url"),
                        "chunk_excerpt": str(chunk.get("content") or "")[:900],
                        "candidate_span": propose_relation_span(
                            str(chunk.get("content") or ""),
                            edge["source"],
                            edge["target"],
                            description=str(edge.get("description") or ""),
                            evidence_quote=str(edge.get("evidence") or ""),
                        ),
                        "context_excerpt": propose_relation_context(
                            str(chunk.get("content") or ""),
                            edge["source"],
                            edge["target"],
                            description=str(edge.get("description") or ""),
                            evidence_quote=str(edge.get("evidence") or ""),
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
        candidates.append(
            {
                "from": start,
                "to": target,
                "start_domain": start_domain,
                "target_domain": target_domain,
                "start_domains": path_start["domains"],
                "target_domains": target_subject["domains"],
                "domain_distance": round(distance, 3) if distance is not None else None,
                "review_priority": (
                    "cross_domain" if distance is not None and distance > 0
                    else "same_domain" if distance is not None else "unclassified"
                ),
                "start_concept_id": path_start["concept_id"],
                "target_concept_id": target_subject["concept_id"],
                "start_subject_status": path_start["status"],
                "target_subject_status": target_subject["status"],
                "taxonomy_status": _taxonomy()["review_status"],
                "taxonomy_version": _taxonomy()["version"],
                "hops": len(steps),
                "path": steps,
                "status": "unreviewed_indirect_connection",
            }
        )

    candidates.sort(key=lambda item: (
        item["domain_distance"] is None,
        -(item["domain_distance"] or 0),
    ))
    results = candidates[:limit]
    return {
        "start": start,
        "start_domain": start_subject["domains"][0] if start_domains else None,
        "start_domains": start_subject["domains"],
        "start_subject_status": start_subject["status"],
        "taxonomy_version": _taxonomy()["version"],
        "suggested_start_nodes": suggested_starts if not results else [],
        "connections": results,
        "candidate_count": len(candidates),
        "retrieval_status": diagnostics.get("status", "unknown"),
        "retrieval_reason": diagnostics.get("reason"),
        "paths_examined": len(diagnostics.get("paths") or []),
        "excluded_paths": dict(excluded),
        "empty_reason": (
            "No directed, source-resolved 2-4-hop path survived the filters."
            if not results else None
        ),
        "notice": (
            "Exploratory, unreviewed paths. Versioned subject-map distance "
            "prioritizes review but is not evidence quality or causal confidence. "
            "Unknown and same-area endpoints remain eligible. Candidate "
            "spans only locate mentions, not proof. "
            "Each hop needs source and condition review; "
            "the endpoint pair is not a verified direct causal relation."
        ),
    }
