"""Bounded, evidence-visible formatting for exploratory graph paths."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


DOMAIN_TERMS: dict[str, tuple[str, ...]] = {
    "Degradation und Alterung": (
        "decomposition", "degradation", "aging", "ageing", "plating",
        "sei", "gas generation", "corrosion", "zersetzung", "alterung",
    ),
    "Fertigung": (
        "calendering", "calender", "coating process", "drying temperature", "drying process",
        "stacking", "welding", "mixing", "formation process", "kalandrier",
        "beschichtung", "trocknung", "stapeln", "schweißen",
    ),
    "Diagnostik": (
        "microscopy", "spectroscopy", "measurement", "eis", "xps", "sem",
        "diagnostic", "mikroskop", "spektroskop", "messung",
    ),
    "Zellqualitaet und Sicherheit": (
        "defect", "failure", "safety", "thermal runaway", "capacity fade",
        "fehler", "sicherheit", "kapazitaetsverlust",
    ),
    "Eigenschaften und Transport": (
        "porosity", "resistance", "thickness", "conductivity", "potential",
        "current nonuniformity", "nonuniform current", "waerme", "heat",
        "porositaet", "widerstand", "dicke", "leitfaehigkeit",
    ),
    "Materialien und Komponenten": (
        "electrolyte", "electrode", "cathode", "anode", "separator",
        "solvent", "binder", "graphite", "elektrolyt", "elektrode",
        "kathode", "separator", "loesungsmittel",
    ),
}

CAUSAL_TYPES = frozenset({
    "causes", "affects", "influences", "leads_to", "results_in",
    "increases", "decreases", "degrades", "improves", "promotes",
    "prevents", "reduces", "enables",
})


def classify_domain(name: str) -> str | None:
    text = name.casefold()
    for domain, terms in DOMAIN_TERMS.items():
        if any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text) for term in terms):
            return domain
    return None


def _normal(name: str) -> str:
    return " ".join(name.casefold().split())


def _valid_path(path: dict[str, Any], start: str, chunks: dict[str, dict[str, Any]]) -> bool:
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
            or not any(source_id in chunks for source_id in edge.get("source_ids") or [])
        ):
            return False
    return True


def format_exploration(
    payload: dict[str, Any], *, start: str, limit: int = 5
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
        and _normal(start) in _normal(str(entity.get("entity_name") or entity.get("entity_id")))
    ][:10]
    start_domain = classify_domain(start)
    by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_targets: set[str] = set()

    for path in diagnostics.get("paths") or []:
        if not isinstance(path, dict) or not _valid_path(path, start, chunks):
            continue
        nodes = path["nodes"]
        target = str(nodes[-1])
        target_domain = classify_domain(target)
        if not start_domain or not target_domain or target_domain == start_domain:
            continue
        if _normal(target) in seen_targets:
            continue
        seen_targets.add(_normal(target))
        steps = []
        for edge in path["edges"]:
            sources = []
            for source_id in edge.get("source_ids") or []:
                chunk = chunks.get(source_id)
                if not chunk:
                    continue
                file_path = str(chunk.get("file_path") or "")
                ref = references.get(file_path) or {}
                sources.append({
                    "chunk_id": source_id,
                    "document": file_path,
                    "url": ref.get("url") or ref.get("source_url") or ref.get("download_url"),
                    "chunk_excerpt": str(chunk.get("content") or "")[:900],
                    "note": "Chunk excerpt; exact relation span not independently verified.",
                })
                if sources:
                    break
            steps.append({
                "source": edge["source"],
                "relation": edge["relation_type"],
                "target": edge["target"],
                "description": edge.get("description") or "",
                "available_source_count": len(edge.get("source_ids") or []),
                "sources": sources,
            })
        by_domain[target_domain].append({
            "from": start,
            "to": target,
            "start_domain": start_domain,
            "target_domain": target_domain,
            "hops": len(steps),
            "path": steps,
            "status": "unreviewed_indirect_connection",
        })

    results: list[dict[str, Any]] = []
    while len(results) < limit and any(by_domain.values()):
        for domain in sorted(by_domain):
            if by_domain[domain] and len(results) < limit:
                results.append(by_domain[domain].pop(0))
    return {
        "start": start,
        "start_domain": start_domain,
        "suggested_start_nodes": suggested_starts if not results else [],
        "connections": results,
        "candidate_count": sum(len(paths) for paths in by_domain.values()) + len(results),
        "retrieval_status": diagnostics.get("status", "unknown"),
        "retrieval_reason": diagnostics.get("reason"),
        "paths_examined": len(diagnostics.get("paths") or []),
        "empty_reason": (
            "Starting node has no provisional subject classification."
            if not start_domain else
            "No directed, source-resolved cross-area path survived the filters."
            if not results else None
        ),
        "notice": (
            "Exploratory, unreviewed paths. Cross-domain labels are provisional "
            "keyword classifications. Each hop needs source and condition review; "
            "the endpoint pair is not a verified direct causal relation."
        ),
    }
