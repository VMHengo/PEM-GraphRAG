"""Exact-start, bounded path discovery for human review sessions."""

from __future__ import annotations

from dataclasses import replace
from functools import partial
from typing import Any

from lightrag.adaptive_retrieval import route_retrieval_query
from lightrag.base import QueryParam
from lightrag.directed_retrieval import find_directed_paths, route_chain_roles
from lightrag_mcp.exploration import CAUSAL_TYPES


async def discover_from_start(
    rag: Any, start: str, param: QueryParam, *, references: list[dict] | None = None
) -> dict[str, Any] | None:
    """Use the graph provider directly so unrelated query anchors cannot fill the beam."""

    graph = getattr(rag, "chunk_entity_relation_graph", None)
    text_chunks = getattr(rag, "text_chunks", None)
    fetch_edges = getattr(graph, "get_directed_neighbor_edges_batch", None)
    get_chunks = getattr(text_chunks, "get_by_ids", None)
    if not callable(fetch_edges) or not callable(get_chunks):
        return None

    route = route_retrieval_query(
        f"What can {start} cause or influence downstream?", param
    )
    route = replace(route, target_relation_types=tuple(sorted(CAUSAL_TYPES)))
    if getattr(graph, "supports_query_aware_neighbor_selection", False):
        fetch_edges = partial(
            fetch_edges,
            target_relation_types=route.target_relation_types,
            target_chain_roles=(
                route_chain_roles(route) if param.allow_evidence_predicates else ()
            ),
        )
    stages: dict[str, Any] = {}
    paths = await find_directed_paths(
        (start,), fetch_edges, route=route, query_param=param,
        focus_entities=(start,), diagnostics=stages,
        provider_candidate_limit=getattr(graph, "directed_neighbor_candidate_limit", None),
    )
    source_ids = list(dict.fromkeys(
        source_id
        for path in paths
        for edge in path.edges
        for source_id in edge.source_ids
    ))
    stored_chunks = await get_chunks(source_ids) if source_ids else []
    chunks = [
        {
            "chunk_id": source_id,
            "content": chunk.get("content") or "",
            "file_path": chunk.get("file_path") or "",
        }
        for source_id, chunk in zip(source_ids, stored_chunks)
        if isinstance(chunk, dict)
    ]
    diagnostics = [
        {
            "nodes": list(path.nodes),
            "edges": [
                {
                    "source": edge.source,
                    "target": edge.target,
                    "relation_type": edge.relation_type,
                    "directionality": edge.directionality,
                    "description": edge.description,
                    "source_ids": list(edge.source_ids),
                }
                for edge in path.edges
            ],
        }
        for path in paths
    ]
    return {
        "data": {"chunks": chunks, "references": references or []},
        "metadata": {"directed_paths": {
            "status": "completed",
            "reason": "paths_found" if paths else "no_matching_paths",
            "paths": diagnostics,
            "stages": stages,
            "anchor_entities": [start],
        }},
    }
