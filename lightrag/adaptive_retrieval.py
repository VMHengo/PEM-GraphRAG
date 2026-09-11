"""Deterministic planning for adaptive directed retrieval.

This module only classifies a query and returns a retrieval plan. It does not
call an LLM, access storage, or change the existing LightRAG retrieval flow.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal
import unicodedata

from lightrag.base import QueryParam

QueryType = Literal[
    "general",
    "root_cause",
    "causal_chain",
    "production_chain",
    "dependency_chain",
    "provenance_chain",
    "comparison_or_association",
]
RetrievalStrategy = Literal["normal", "directed", "combined"]
EdgeDirection = Literal["both", "in", "out"]

CAUSAL_RELATIONS = (
    "causes",
    "affects",
    "influences",
    "leads_to",
    "results_in",
    "degrades",
)
PRODUCTION_RELATIONS = (
    "precedes",
    "follows",
    "produces",
    "uses",
    "contains",
    "part_of",
    "influences",
)
DEPENDENCY_RELATIONS = (
    "depends_on",
    "requires",
    "uses",
    "contains",
    "part_of",
)
PROVENANCE_RELATIONS = (
    "published_by",
    "authored_by",
    "evidenced_by",
    "described_in",
)


@dataclass(frozen=True)
class RetrievalRoute:
    """A side-effect-free decision for a future retrieval execution layer."""

    query_type: QueryType
    effective_strategy: RetrievalStrategy
    use_normal_retrieval: bool
    use_directed_paths: bool
    edge_direction: EdgeDirection
    target_relation_types: tuple[str, ...]
    matched_rule: str


@dataclass(frozen=True)
class _RoutingRule:
    name: str
    query_type: QueryType
    direction: EdgeDirection
    relation_types: tuple[str, ...]
    patterns: tuple[re.Pattern[str], ...]


def _compile_patterns(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern) for pattern in patterns)


_ROOT_CAUSE_RULE = _RoutingRule(
    name="root_cause",
    query_type="root_cause",
    direction="in",
    relation_types=CAUSAL_RELATIONS,
    patterns=_compile_patterns(
        r"\broot\s+cause\b",
        r"\bwhat\s+causes?\b",
        r"\bwhich\s+(?:factors?|causes?)\b",
        r"\bwhere\s+does\b.*\bcome\s+from\b",
        r"\bwelche\s+ursachen?\b",
        r"\bwodurch\b.*\bverursacht\b",
        r"\bwoher\s+kommt\b",
        r"\bzur[üu]ckzuf[üu]hren\s+auf\b",
    ),
)
_CAUSAL_CHAIN_RULE = _RoutingRule(
    name="causal_chain",
    query_type="causal_chain",
    direction="out",
    relation_types=CAUSAL_RELATIONS,
    patterns=_compile_patterns(
        r"\bwhat\s+does\b.*\bcause\b",
        r"\bwhat\s+can\b.*\blead\s+to\b",
        r"\b(?:results?\s+in|leads?\s+to|effects?\s+of|consequences?\s+of)\b",
        r"\bf(?:\u00fchrt|uhrt)\s+zu\b",
        r"\b(?:wozu|zu\s+welchen\s+(?:folgen|auswirkungen|fehlern))\s+f[üu]hrt\b",
        r"\b(?:welche\s+folgen|welche\s+auswirkungen)\b",
    ),
)
_PRODUCTION_CHAIN_RULE = _RoutingRule(
    name="production_chain",
    query_type="production_chain",
    direction="out",
    relation_types=PRODUCTION_RELATIONS,
    patterns=_compile_patterns(
        r"\b(?:production|process)\s+chain\b",
        r"\bmanufacturing\s+(?:steps?|process)\b",
        r"\b(?:produktions|prozess|herstellungs)kette\b",
        r"\b(?:fertigungs|herstellungs)schritte\b",
        r"\bherstellungsprozess\b",
    ),
)
_DEPENDENCY_RULE = _RoutingRule(
    name="dependency_chain",
    query_type="dependency_chain",
    direction="out",
    relation_types=DEPENDENCY_RELATIONS,
    patterns=_compile_patterns(
        r"\b(?:depends?\s+on|requires?|input\s+materials?)\b",
        r"\bwovon\s+h[aä]ngt\b",
        r"\babh[aä]ngig\s+von\b",
        r"\b(?:ben[öo]tigt|voraussetzung(?:en)?)\b",
    ),
)
_PROVENANCE_RULE = _RoutingRule(
    name="provenance_chain",
    query_type="provenance_chain",
    direction="both",
    relation_types=PROVENANCE_RELATIONS,
    patterns=_compile_patterns(
        r"\b(?:published\s+by|authored\s+by|document\s+source)\b",
        r"\b(?:ver[öo]ffentlicht\s+von|autor(?:in)?(?:en)?|dokumentquelle)\b",
        r"\bvon\s+wem\b.*\bver[öo]ffentlicht\b",
        r"\bwhich\s+documents?\b.*\b(?:source|author|publisher)\b",
    ),
)
_COMPARISON_RULE = _RoutingRule(
    name="comparison_or_association",
    query_type="comparison_or_association",
    direction="both",
    relation_types=(),
    patterns=_compile_patterns(
        r"\b(?:vergleich|unterschied(?:e)?\s+zwischen)\b",
        r"\b(?:similar(?:ity)?|compared\s+with|difference\s+between)\b",
    ),
)

# Priority avoids treating a root-cause question containing "lead to" as a
# downstream question.
_ROUTING_RULES = (
    _ROOT_CAUSE_RULE,
    _CAUSAL_CHAIN_RULE,
    _PRODUCTION_CHAIN_RULE,
    _DEPENDENCY_RULE,
    _PROVENANCE_RULE,
    _COMPARISON_RULE,
)
_CHAIN_QUERY_TYPES = {
    "root_cause",
    "causal_chain",
    "production_chain",
    "dependency_chain",
    "provenance_chain",
}


def _normalize_query(query: str) -> str:
    normalized = unicodedata.normalize("NFKC", query).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def _classify_query(query: str) -> tuple[_RoutingRule | None, str]:
    normalized_query = _normalize_query(query)
    for rule in _ROUTING_RULES:
        if any(pattern.search(normalized_query) for pattern in rule.patterns):
            return rule, normalized_query
    return None, normalized_query


def _effective_strategy(
    query_type: QueryType, requested_strategy: str
) -> RetrievalStrategy:
    if requested_strategy == "auto":
        return "combined" if query_type in _CHAIN_QUERY_TYPES else "normal"
    if requested_strategy in {"normal", "directed", "combined"}:
        return requested_strategy
    raise ValueError(f"Unsupported retrieval strategy: {requested_strategy}")


def route_retrieval_query(query: str, query_param: QueryParam) -> RetrievalRoute:
    """Classify *query* and return a bounded plan for future retrieval layers.

    ``QueryParam`` remains unchanged. An explicit ``in`` or ``out`` direction
    takes precedence over the inferred direction. The default ``both`` lets an
    automatically routed chain query select the direction implied by its rule.
    """
    rule, normalized_query = _classify_query(query)
    query_type: QueryType = rule.query_type if rule else "general"
    inferred_direction: EdgeDirection = rule.direction if rule else "both"
    relation_types = rule.relation_types if rule else ()
    matched_rule = rule.name if rule else "general"

    strategy = _effective_strategy(query_type, query_param.retrieval_strategy)
    direction: EdgeDirection = (
        query_param.edge_direction
        if query_param.edge_direction in {"in", "out"}
        else inferred_direction
    )

    # A blank query is not a chain query even if future callers bypass Pydantic.
    if not normalized_query:
        query_type = "general"
        relation_types = ()
        matched_rule = "general"
        direction = "both"
        strategy = _effective_strategy(query_type, query_param.retrieval_strategy)

    return RetrievalRoute(
        query_type=query_type,
        effective_strategy=strategy,
        use_normal_retrieval=strategy in {"normal", "combined"},
        use_directed_paths=strategy in {"directed", "combined"},
        edge_direction=direction,
        target_relation_types=relation_types,
        matched_rule=matched_rule,
    )
