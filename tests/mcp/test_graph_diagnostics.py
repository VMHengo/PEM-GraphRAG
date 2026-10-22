from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from neo4j import Query

from lightrag_mcp.graph_diagnostics import (
    MAX_CHAIN_LIMIT,
    MAX_ENTITY_LIMIT,
    MAX_OUTPUT_LIST_ITEMS,
    MAX_OUTPUT_STRING_LENGTH,
    MAX_RELATIONSHIP_LIMIT,
    QUERY_TIMEOUT_SECONDS,
    inspect_chain,
    inspect_entity,
    inspect_relationships,
)


def _driver_with_records(*record_batches):
    results = []
    for records in record_batches:
        result = MagicMock()
        result.data = AsyncMock(return_value=records)
        result.consume = AsyncMock()
        results.append(result)

    session = MagicMock()
    session.run = AsyncMock(side_effect=results)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)

    driver = MagicMock()
    driver.session.return_value = context
    return driver, session, results


def _executed_query(session, index=-1):
    query, parameters = session.run.await_args_list[index].args
    assert isinstance(query, Query)
    assert query.timeout == QUERY_TIMEOUT_SECONDS
    return query.text, parameters


@pytest.mark.asyncio
async def test_inspect_entity_uses_parameterized_read_only_bounded_query():
    entity = {
        "entity_id": "CELL",
        "entity_type": "COMPONENT",
        "description": "Battery cell",
        "source_id": "chunk-1",
        "file_path": "cell.pdf",
        "labels": ["base"],
    }
    relationship = {
        "inspected_entity": "CELL",
        "neighbor_entity": "ANODE",
        "semantic_src_id": "ANODE",
        "semantic_tgt_id": "CELL",
        "source_id": "chunk-2",
        "file_path": "cell.pdf",
    }
    driver, session, results = _driver_with_records(
        [entity],
        [relationship],
    )

    output = await inspect_entity(driver, "neo4j", " CELL ", 4)

    cypher, parameters = _executed_query(session, 0)
    assert parameters == {"name": "CELL", "limit": 4}
    assert "CELL" not in cypher
    assert "LIMIT $limit" in cypher
    assert "source_id" in cypher and "file_path" in cypher
    neighbor_cypher, neighbor_parameters = _executed_query(session, 1)
    assert neighbor_parameters == {"name": "CELL", "limit": 4}
    assert "-[relationship:DIRECTED]-" in neighbor_cypher
    assert "LIMIT $limit" in neighbor_cypher
    assert "semantic_src_id" in neighbor_cypher
    assert driver.session.call_count == 2
    driver.session.assert_called_with(database="neo4j", default_access_mode="READ")
    for result in results:
        result.consume.assert_awaited_once()
    assert output["count"] == 1
    assert output["entities"][0]["source_id"] == "chunk-1"
    assert output["relationship_count"] == 1
    assert output["relationships"] == [relationship]
    json.dumps(output)


@pytest.mark.asyncio
async def test_inspect_relationships_returns_semantic_direction_and_provenance():
    record = {
        "inspected_entity": "COATING",
        "neighbor_entity": "CRACK",
        "physical_src_id": "CRACK",
        "physical_tgt_id": "COATING",
        "semantic_src_id": "COATING",
        "semantic_tgt_id": "CRACK",
        "directionality": "directed",
        "semantic_direction": "outgoing",
        "relation_type": "causes",
        "source_id": "chunk-2",
        "file_path": "defects.pdf",
    }
    driver, session, _ = _driver_with_records([record])

    output = await inspect_relationships(driver, "neo4j", "COATING", "defects.pdf", 7)

    cypher, parameters = _executed_query(session)
    assert parameters == {
        "entity": "COATING",
        "document": "defects.pdf",
        "limit": 7,
    }
    assert "COATING" not in cypher and "defects.pdf" not in cypher
    assert "semantic_src_id" in cypher
    assert "semantic_tgt_id" in cypher
    assert "semantic_direction" in cypher
    assert "source_id" in cypher and "file_path" in cypher
    assert "LIMIT $limit" in cypher
    assert output["relationships"] == [record]
    json.dumps(output)


@pytest.mark.asyncio
async def test_inspect_chain_selects_one_of_three_fixed_hop_queries():
    driver, session, _ = _driver_with_records(
        [{"hop_count": 3, "entities": [], "relationships": []}]
    )

    output = await inspect_chain(driver, "neo4j", "ANODE", "CELL", 3, 2)

    cypher, parameters = _executed_query(session)
    assert parameters == {"start": "ANODE", "end": "CELL", "limit": 2}
    assert "ANODE" not in cypher and "CELL" not in cypher
    assert ":DIRECTED*1..3" in cypher
    assert "LIMIT $limit" in cypher
    assert "semantic_src_id" in cypher and "semantic_tgt_id" in cypher
    assert "source_id" in cypher and "file_path" in cypher
    assert output["max_hops"] == 3
    assert output["count"] == 1
    json.dumps(output)


@pytest.mark.parametrize(
    ("call", "maximum"),
    [
        (
            lambda driver, value: inspect_entity(driver, "neo4j", "CELL", value),
            MAX_ENTITY_LIMIT,
        ),
        (
            lambda driver, value: inspect_relationships(
                driver, "neo4j", "CELL", None, value
            ),
            MAX_RELATIONSHIP_LIMIT,
        ),
        (
            lambda driver, value: inspect_chain(
                driver, "neo4j", "ANODE", "CELL", 2, value
            ),
            MAX_CHAIN_LIMIT,
        ),
    ],
)
@pytest.mark.asyncio
async def test_row_limits_are_validated_before_using_driver(call, maximum):
    driver = MagicMock()

    with pytest.raises(ValueError, match="limit"):
        await call(driver, maximum + 1)

    driver.session.assert_not_called()


@pytest.mark.asyncio
async def test_chain_rejects_more_than_three_hops_before_using_driver():
    driver = MagicMock()

    with pytest.raises(ValueError, match="max_hops"):
        await inspect_chain(driver, "neo4j", "ANODE", "CELL", 4, 1)

    driver.session.assert_not_called()


@pytest.mark.asyncio
async def test_relationship_filter_rejects_oversized_document():
    driver = MagicMock()

    with pytest.raises(ValueError, match="document"):
        await inspect_relationships(driver, "neo4j", "CELL", "x" * 201, 1)

    driver.session.assert_not_called()


@pytest.mark.asyncio
async def test_output_truncates_strings_and_lists_and_drops_sensitive_keys():
    oversized = "x" * (MAX_OUTPUT_STRING_LENGTH + 100)
    record = {
        "description": oversized,
        "relation_assertions_json": oversized,
        "debug_values": list(range(MAX_OUTPUT_LIST_ITEMS + 10)),
        "password": "database-password",
        "authorization": "Bearer private-token",
        "NEO4J_PASSWORD": "another-password",
        "nested": {"secret": "private", "source_id": "chunk-1"},
    }
    driver, _, _ = _driver_with_records([record, {"description": "extra row"}])

    output = await inspect_relationships(driver, "neo4j", "CELL", None, 1)
    serialized = json.dumps(output)
    returned = output["relationships"][0]

    assert output["count"] == 1
    assert len(output["relationships"]) == 1
    assert len(returned["description"]) == MAX_OUTPUT_STRING_LENGTH
    assert returned["description"].endswith("...[truncated]")
    assert len(returned["relation_assertions_json"]) == MAX_OUTPUT_STRING_LENGTH
    assert len(returned["debug_values"]) == MAX_OUTPUT_LIST_ITEMS
    assert returned["nested"] == {"source_id": "chunk-1"}
    assert "database-password" not in serialized
    assert "private-token" not in serialized
    assert "another-password" not in serialized
    assert '"password"' not in serialized
    assert '"authorization"' not in serialized
