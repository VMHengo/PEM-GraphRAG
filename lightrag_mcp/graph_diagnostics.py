"""Bounded, read-only Neo4j queries for developer graph diagnostics."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from neo4j import Query


QUERY_TIMEOUT_SECONDS = 5.0
MAX_ENTITY_LIMIT = 20
MAX_RELATIONSHIP_LIMIT = 30
MAX_CHAIN_LIMIT = 10
MAX_CHAIN_HOPS = 3
MAX_OUTPUT_STRING_LENGTH = 4_000
MAX_OUTPUT_LIST_ITEMS = 50

_TRUNCATION_MARKER = "...[truncated]"
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "auth",
        "authorization",
        "client_secret",
        "credentials",
        "neo4j_password",
        "neo4j_uri",
        "neo4j_username",
        "password",
        "passwd",
        "refresh_token",
        "secret",
        "token",
        "access_token",
        "uri",
        "username",
    }
)

_ENTITY_QUERY = """
MATCH (entity {entity_id: $name})
RETURN entity.entity_id AS entity_id,
       entity.entity_type AS entity_type,
       entity.description AS description,
       entity.source_id AS source_id,
       entity.file_path AS file_path,
       labels(entity) AS labels
ORDER BY entity.entity_id
LIMIT $limit
"""

_ENTITY_NEIGHBORS_QUERY = """
MATCH (entity {entity_id: $name})-[relationship:DIRECTED]-(neighbor)
RETURN entity.entity_id AS inspected_entity,
       neighbor.entity_id AS neighbor_entity,
       startNode(relationship).entity_id AS physical_src_id,
       endNode(relationship).entity_id AS physical_tgt_id,
       coalesce(relationship.semantic_src_id,
                startNode(relationship).entity_id) AS semantic_src_id,
       coalesce(relationship.semantic_tgt_id,
                endNode(relationship).entity_id) AS semantic_tgt_id,
       coalesce(relationship.directionality, 'unknown') AS directionality,
       relationship.relation_type AS relation_type,
       relationship.description AS description,
       relationship.source_id AS source_id,
       relationship.file_path AS file_path
LIMIT $limit
"""

_RELATIONSHIPS_QUERY = """
MATCH (entity {entity_id: $entity})-[relationship:DIRECTED]-(neighbor)
WHERE $document IS NULL
   OR toLower(coalesce(relationship.file_path, '')) CONTAINS toLower($document)
RETURN entity.entity_id AS inspected_entity,
       neighbor.entity_id AS neighbor_entity,
       startNode(relationship).entity_id AS physical_src_id,
       endNode(relationship).entity_id AS physical_tgt_id,
       coalesce(relationship.semantic_src_id,
                startNode(relationship).entity_id) AS semantic_src_id,
       coalesce(relationship.semantic_tgt_id,
                endNode(relationship).entity_id) AS semantic_tgt_id,
       coalesce(relationship.directionality, 'unknown') AS directionality,
       CASE
           WHEN coalesce(relationship.semantic_src_id,
                         startNode(relationship).entity_id) = entity.entity_id
               THEN 'outgoing'
           WHEN coalesce(relationship.semantic_tgt_id,
                         endNode(relationship).entity_id) = entity.entity_id
               THEN 'incoming'
           ELSE 'unknown'
       END AS semantic_direction,
       relationship.relation_type AS relation_type,
       relationship.description AS description,
       relationship.source_id AS source_id,
       relationship.file_path AS file_path,
       relationship.relation_assertions_json AS relation_assertions_json
ORDER BY neighbor.entity_id, relation_type, semantic_src_id, semantic_tgt_id
LIMIT $limit
"""

# LIMIT bounds returned rows, not candidate expansion. The server-side query
# timeout is the execution guard for dense graphs.
_CHAIN_QUERY_1 = """
MATCH (source {entity_id: $start}), (target {entity_id: $end})
MATCH path = (source)-[:DIRECTED*1..1]-(target)
WITH path
LIMIT $limit
RETURN length(path) AS hop_count,
       [node IN nodes(path) | {
           entity_id: node.entity_id,
           entity_type: node.entity_type,
           description: node.description,
           source_id: node.source_id,
           file_path: node.file_path
       }] AS entities,
       [relationship IN relationships(path) | {
           physical_src_id: startNode(relationship).entity_id,
           physical_tgt_id: endNode(relationship).entity_id,
           semantic_src_id: coalesce(relationship.semantic_src_id,
                                     startNode(relationship).entity_id),
           semantic_tgt_id: coalesce(relationship.semantic_tgt_id,
                                     endNode(relationship).entity_id),
           directionality: coalesce(relationship.directionality, 'unknown'),
           relation_type: relationship.relation_type,
           description: relationship.description,
           source_id: relationship.source_id,
           file_path: relationship.file_path,
           relation_assertions_json: relationship.relation_assertions_json
       }] AS relationships
"""

_CHAIN_QUERY_2 = _CHAIN_QUERY_1.replace("*1..1", "*1..2")
_CHAIN_QUERY_3 = _CHAIN_QUERY_1.replace("*1..1", "*1..3")
_CHAIN_QUERIES = {1: _CHAIN_QUERY_1, 2: _CHAIN_QUERY_2, 3: _CHAIN_QUERY_3}


def _bounded_int(value: int, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


def _bounded_text(
    value: str | None,
    name: str,
    maximum: int,
    *,
    optional: bool = False,
) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{name} must be at most {maximum} characters")
    return normalized


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        if len(value) <= MAX_OUTPUT_STRING_LENGTH:
            return value
        retained_length = MAX_OUTPUT_STRING_LENGTH - len(_TRUNCATION_MARKER)
        return value[:retained_length] + _TRUNCATION_MARKER
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in value.items()
            if str(key).lower() not in _SENSITIVE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value[:MAX_OUTPUT_LIST_ITEMS]]
    if hasattr(value, "iso_format"):
        return _json_value(value.iso_format())
    if hasattr(value, "isoformat"):
        return _json_value(value.isoformat())
    return _json_value(str(value))


async def _read_records(
    driver: Any,
    database: str,
    cypher: str,
    parameters: dict[str, Any],
) -> list[dict[str, Any]]:
    async def execute() -> list[dict[str, Any]]:
        result = None
        query = Query(cypher, timeout=QUERY_TIMEOUT_SECONDS)
        async with driver.session(
            database=database,
            default_access_mode="READ",
        ) as session:
            try:
                result = await session.run(query, parameters)
                records = await result.data()
                row_limit = parameters["limit"]
                return [_json_value(record) for record in records[:row_limit]]
            finally:
                if result is not None:
                    await result.consume()

    return await asyncio.wait_for(execute(), timeout=QUERY_TIMEOUT_SECONDS + 1.0)


async def inspect_entity(driver, database, name, limit):
    """Return bounded entity matches and their immediate relationships."""

    checked_database = _bounded_text(database, "database", 128)
    checked_name = _bounded_text(name, "name", 160)
    checked_limit = _bounded_int(limit, "limit", MAX_ENTITY_LIMIT)
    entities = await _read_records(
        driver,
        checked_database,
        _ENTITY_QUERY,
        {"name": checked_name, "limit": checked_limit},
    )
    relationships = await _read_records(
        driver,
        checked_database,
        _ENTITY_NEIGHBORS_QUERY,
        {"name": checked_name, "limit": checked_limit},
    )
    return {
        "name": checked_name,
        "count": len(entities),
        "entities": entities,
        "relationship_count": len(relationships),
        "relationships": relationships,
    }


async def inspect_relationships(driver, database, entity, document, limit):
    """Return bounded incident relationships with semantic direction metadata."""

    checked_database = _bounded_text(database, "database", 128)
    checked_entity = _bounded_text(entity, "entity", 160)
    checked_document = _bounded_text(document, "document", 200, optional=True)
    checked_limit = _bounded_int(limit, "limit", MAX_RELATIONSHIP_LIMIT)
    relationships = await _read_records(
        driver,
        checked_database,
        _RELATIONSHIPS_QUERY,
        {
            "entity": checked_entity,
            "document": checked_document,
            "limit": checked_limit,
        },
    )
    return {
        "entity": checked_entity,
        "document": checked_document,
        "count": len(relationships),
        "relationships": relationships,
    }


async def inspect_chain(driver, database, start, end, max_hops, limit):
    """Return bounded paths of at most three hops between exact entity IDs."""

    checked_database = _bounded_text(database, "database", 128)
    checked_start = _bounded_text(start, "start", 160)
    checked_end = _bounded_text(end, "end", 160)
    checked_hops = _bounded_int(max_hops, "max_hops", MAX_CHAIN_HOPS)
    checked_limit = _bounded_int(limit, "limit", MAX_CHAIN_LIMIT)
    chains = await _read_records(
        driver,
        checked_database,
        _CHAIN_QUERIES[checked_hops],
        {"start": checked_start, "end": checked_end, "limit": checked_limit},
    )
    return {
        "start": checked_start,
        "end": checked_end,
        "max_hops": checked_hops,
        "count": len(chains),
        "chains": chains,
    }
