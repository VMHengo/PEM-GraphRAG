"""Pure edge preparation for a future directed multi-hop retrieval layer.

The existing LightRAG graph APIs still expose mostly undirected relationships.
This module deliberately has no storage dependency: it turns raw relationship
records into consistently shaped semantic edges, filters them for a routed
query, and provides deterministic ranking. A later Neo4j traversal can use
these helpers without changing normal LightRAG retrieval.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any, Literal
import unicodedata

from lightrag.adaptive_retrieval import RetrievalRoute
from lightrag.base import QueryParam

RelationDirectionality = Literal["directed", "undirected", "unknown"]
EdgeTraversalDirection = Literal["both", "in", "out"]

_DIRECTION_RELIABILITY = {
    "directed": 1.0,
    "undirected": 0.85,
    "unknown": 0.75,
}
_GENERIC_RELATION_TYPES = frozenset({"related_to", "co_occurs_with", "unknown"})
_RELATION_TYPE_ALIASES = {
    "affect": "affects",
    "affected_by": "affects",
    "cause": "causes",
    "caused_by": "causes",
    "causes": "causes",
    "collaborate_with": "collaborates_with",
    "compared_to": "compared_with",
    "contains": "contains",
    "depend_on": "depends_on",
    "degrade": "degrades",
    "described_by": "described_in",
    "evidence_for": "evidenced_by",
    "follow": "follows",
    "influence": "influences",
    "lead_to": "leads_to",
    "measure": "measures",
    "optimize": "optimizes",
    "part_of": "part_of",
    "precede": "precedes",
    "produce": "produces",
    "publish_by": "published_by",
    "require": "requires",
    "result_in": "results_in",
    "study": "studies",
    "support": "supports",
    "use": "uses",
}


@dataclass(frozen=True)
class DirectedEdge:
    """A normalized relationship record suitable for directed traversal."""

    source: str
    target: str
    relation_type: str
    directionality: RelationDirectionality
    relation_importance: float
    chain_role: str
    weight: float
    description: str
    source_ids: tuple[str, ...]
    file_paths: tuple[str, ...]


@dataclass(frozen=True)
class DirectedPath:
    """An ordered, cycle-free chain assembled from normalized semantic edges."""

    nodes: tuple[str, ...]
    edges: tuple[DirectedEdge, ...]
    score: float
    source_ids: tuple[str, ...]
    file_paths: tuple[str, ...]

    @property
    def path_id(self) -> str:
        """Stable, human-readable identifier useful for diagnostics and context."""

        return " -> ".join(self.nodes)


NeighborProvider = Callable[
    [Sequence[str]], Awaitable[Mapping[str, Iterable[Mapping[str, Any]]]]
]

_HOP_PENALTIES = {
    1: 0.0,
    2: 0.15,
    3: 0.35,
}


def _slugify(value: object, default: str = "") -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    text = text.replace("-", "_").replace(" ", "_")
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or default


def _first_text(record: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _text_values(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, Iterable):
        return tuple(str(item) for item in value if str(item).strip())
    return (str(value),)


def _clamped_float(value: object, default: float, *, minimum: float = 0.0) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(1.0, normalized))


def _non_negative_float(value: object, default: float) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, normalized)


def normalize_directionality(value: object) -> RelationDirectionality:
    """Map extraction variants and missing legacy data to stable values."""

    directionality = _slugify(value, "unknown")
    if directionality in {"directed", "outgoing", "forward"}:
        return "directed"
    if directionality in {
        "undirected",
        "bidirectional",
        "both",
        "mutual",
        "symmetric",
    }:
        return "undirected"
    return "unknown"


def normalize_relation_type(value: object, *, keywords: object = None) -> str:
    """Return a canonical predicate, using keywords for old relationship rows."""

    candidates = (value, keywords)
    for candidate in candidates:
        for relation_part in re.split(r"[,;|]", str(candidate or "")):
            relation_type = _slugify(relation_part)
            if relation_type:
                return _RELATION_TYPE_ALIASES.get(relation_type, relation_type)
    return "related_to"


def normalize_directed_edge(record: Mapping[str, Any]) -> DirectedEdge | None:
    """Normalize a raw graph relationship without reinterpreting its direction.

    ``semantic_src_id`` and ``semantic_tgt_id`` preserve the extractor's order
    even where the current storage key was normalized alphabetically. Older
    edges naturally fall back to their storage source and target fields.
    """

    source = _first_text(record, "semantic_src_id", "src_id", "source")
    target = _first_text(record, "semantic_tgt_id", "tgt_id", "target")
    if not source or not target:
        return None

    return DirectedEdge(
        source=source,
        target=target,
        relation_type=normalize_relation_type(
            record.get("relation_type"), keywords=record.get("keywords")
        ),
        directionality=normalize_directionality(record.get("directionality")),
        relation_importance=_clamped_float(
            record.get("relation_importance"), 0.5
        ),
        chain_role=_slugify(record.get("chain_role"), "other"),
        weight=_non_negative_float(record.get("weight"), 1.0),
        description=_first_text(record, "description"),
        source_ids=_text_values(record.get("source_id") or record.get("source_ids")),
        file_paths=_text_values(record.get("file_path") or record.get("file_paths")),
    )


def is_meaningful_directed_edge(edge: DirectedEdge) -> bool:
    """Exclude generic association edges from causal and process chains."""

    return edge.relation_type not in _GENERIC_RELATION_TYPES


def edge_matches_traversal(
    edge: DirectedEdge,
    *,
    anchor: str,
    direction: EdgeTraversalDirection,
) -> bool:
    """Check whether an edge can be traversed from an anchor in *direction*.

    Unknown and undirected legacy edges remain available in both directions.
    They receive a lower score later, so re-indexed directed edges win when
    both describe the same path.
    """

    normalized_anchor = anchor.casefold().strip()
    at_source = edge.source.casefold().strip() == normalized_anchor
    at_target = edge.target.casefold().strip() == normalized_anchor
    if not at_source and not at_target:
        return False
    if direction == "both" or edge.directionality != "directed":
        return True
    if direction == "out":
        return at_source
    return at_target


def score_directed_edge(edge: DirectedEdge, route: RetrievalRoute) -> float:
    """Rank semantic edges before a future path-expansion stage.

    Importance remains the main signal. Directed extraction receives the
    highest reliability; old unknown edges are retained with a smaller score.
    A small bonus makes predicates requested by the query route deterministic
    tie-break winners without overwhelming the extraction confidence.
    """

    predicate_bonus = (
        0.1
        if route.target_relation_types
        and edge.relation_type in route.target_relation_types
        else 0.0
    )
    return (
        edge.relation_importance * _DIRECTION_RELIABILITY[edge.directionality]
        + predicate_bonus
    )


def select_directed_edges(
    records: Iterable[Mapping[str, Any]],
    *,
    anchor: str,
    route: RetrievalRoute,
    query_param: QueryParam,
    apply_fanout: bool = True,
) -> list[DirectedEdge]:
    """Normalize, filter, and rank relationship records for one anchor.

    This helper intentionally performs no graph access. A later Neo4j query
    will provide the bounded candidate records; ``chain_fanout`` then caps the
    locally retained candidates per anchor.
    """

    selected: list[DirectedEdge] = []
    target_types = set(route.target_relation_types)

    for record in records:
        edge = normalize_directed_edge(record)
        if edge is None or not is_meaningful_directed_edge(edge):
            continue
        if edge.relation_importance < query_param.min_relation_importance:
            continue
        if target_types and edge.relation_type not in target_types:
            continue
        if not edge_matches_traversal(
            edge, anchor=anchor, direction=route.edge_direction
        ):
            continue
        selected.append(edge)

    sorted_edges = sorted(
        selected,
        key=lambda edge: (
            -score_directed_edge(edge, route),
            edge.source.casefold(),
            edge.target.casefold(),
            edge.relation_type,
        ),
    )
    return sorted_edges[: query_param.chain_fanout] if apply_fanout else sorted_edges


def _other_endpoint(
    edge: DirectedEdge,
    *,
    current_node: str,
    direction: EdgeTraversalDirection,
) -> str | None:
    """Return the next semantic node when traversing an already matched edge."""

    normalized_current = current_node.casefold().strip()
    at_source = edge.source.casefold().strip() == normalized_current
    at_target = edge.target.casefold().strip() == normalized_current
    if not at_source and not at_target:
        return None

    if edge.directionality != "directed" or direction == "both":
        return edge.target if at_source else edge.source
    if direction == "out" and at_source:
        return edge.target
    if direction == "in" and at_target:
        return edge.source
    return None


def _append_unique(existing: tuple[str, ...], additions: Iterable[str]) -> tuple[str, ...]:
    """Merge citations while preserving their first-seen order."""

    values = list(existing)
    known = set(existing)
    for addition in additions:
        if addition and addition not in known:
            values.append(addition)
            known.add(addition)
    return tuple(values)


def _score_path(edges: tuple[DirectedEdge, ...], route: RetrievalRoute) -> float:
    """Prefer strong short chains without excluding useful two-hop evidence."""

    if not edges:
        return 0.0
    edge_score = sum(score_directed_edge(edge, route) for edge in edges) / len(edges)
    hop_penalty = _HOP_PENALTIES.get(len(edges), _HOP_PENALTIES[3])
    return edge_score - hop_penalty


def _path_key(path: DirectedPath) -> tuple[tuple[str, ...], tuple[tuple[str, str, str], ...]]:
    """Keep direction and predicate when de-duplicating otherwise similar paths."""

    return (
        tuple(node.casefold() for node in path.nodes),
        tuple(
            (
                edge.source.casefold(),
                edge.target.casefold(),
                edge.relation_type,
            )
            for edge in path.edges
        ),
    )


def _sort_paths(paths: Iterable[DirectedPath]) -> list[DirectedPath]:
    return sorted(
        paths,
        key=lambda path: (
            -path.score,
            -len(path.edges),
            tuple(node.casefold() for node in path.nodes),
        ),
    )


def _deduplicate_paths(paths: Iterable[DirectedPath]) -> list[DirectedPath]:
    best_by_key: dict[tuple[tuple[str, ...], tuple[tuple[str, str, str], ...]], DirectedPath] = {}
    for path in paths:
        key = _path_key(path)
        previous = best_by_key.get(key)
        if previous is None or path.score > previous.score:
            best_by_key[key] = path
    return _sort_paths(best_by_key.values())


def _unique_anchors(anchors: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for anchor in anchors:
        normalized = anchor.casefold().strip()
        if normalized and normalized not in seen:
            result.append(anchor.strip())
            seen.add(normalized)
    return tuple(result)


async def find_directed_paths(
    anchors: Sequence[str],
    fetch_edges: NeighborProvider,
    *,
    route: RetrievalRoute,
    query_param: QueryParam,
) -> list[DirectedPath]:
    """Expand semantic paths with a bounded, beam-pruned breadth-first search.

    ``fetch_edges`` receives the unique frontier nodes for each level in one
    batched call. It deliberately hides graph storage details from this engine.
    The caller must only invoke this for a routed directed query; the guard also
    makes a normal strategy a zero-cost no-op.
    """

    if not route.use_directed_paths:
        return []

    initial_anchors = _unique_anchors(anchors)
    if not initial_anchors:
        return []

    frontier = [
        DirectedPath(
            nodes=(anchor,),
            edges=(),
            score=0.0,
            source_ids=(),
            file_paths=(),
        )
        for anchor in initial_anchors
    ]
    discovered: list[DirectedPath] = []

    for _ in range(query_param.hop_depth):
        frontier_nodes = tuple(
            sorted({path.nodes[-1] for path in frontier}, key=str.casefold)
        )
        if not frontier_nodes:
            break

        records_by_node = await fetch_edges(frontier_nodes)
        next_frontier: list[DirectedPath] = []

        for path in frontier:
            current_node = path.nodes[-1]
            records = records_by_node.get(current_node, ())
            expanded_edges = 0
            for edge in select_directed_edges(
                records,
                anchor=current_node,
                route=route,
                query_param=query_param,
                apply_fanout=False,
            ):
                next_node = _other_endpoint(
                    edge,
                    current_node=current_node,
                    direction=route.edge_direction,
                )
                if next_node is None:
                    continue
                if next_node.casefold() in {
                    node.casefold() for node in path.nodes
                }:
                    continue

                edges = path.edges + (edge,)
                next_frontier.append(
                    DirectedPath(
                        nodes=path.nodes + (next_node,),
                        edges=edges,
                        score=_score_path(edges, route),
                        source_ids=_append_unique(path.source_ids, edge.source_ids),
                        file_paths=_append_unique(path.file_paths, edge.file_paths),
                    )
                )
                expanded_edges += 1
                if expanded_edges >= query_param.chain_fanout:
                    break

        if not next_frontier:
            break

        frontier = _deduplicate_paths(next_frontier)[: query_param.chain_top_k]
        discovered.extend(frontier)

    return _deduplicate_paths(discovered)[: query_param.chain_top_k]
