"""Offline tests for bounded Cypher Explorer execution and serialization."""

from typing import Any

import pytest

from lightrag.graph_cypher import ReadOnlyCypherError, validate_read_only_cypher
from lightrag.kg.neo4j_impl import Neo4JStorage


class _FakeNode(dict):
    def __init__(self, node_id: int, **properties: Any):
        super().__init__(properties)
        self.id = node_id
        self.labels = {"base"}


class _FakeRelationship(dict):
    def __init__(self, relation_id: int, start_node: _FakeNode, end_node: _FakeNode, **properties: Any):
        super().__init__(properties)
        self.id = relation_id
        self.type = "DIRECTED"
        self.start_node = start_node
        self.end_node = end_node


class _FakeResult:
    def __init__(self, records: list[dict[str, Any]]):
        self._records = records
        self.consumed = False

    def keys(self):
        return list(self._records[0]) if self._records else ["source", "edge", "target"]

    async def fetch(self, count: int):
        return self._records[:count]

    async def consume(self):
        self.consumed = True


class _FakeTransaction:
    def __init__(self, driver: "_FakeDriver"):
        self._driver = driver

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def run(self, query: str, parameters: dict[str, Any]):
        self._driver.query = query
        self._driver.parameters = parameters
        return self._driver.result


class _FakeSession:
    def __init__(self, driver: "_FakeDriver"):
        self._driver = driver

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def begin_transaction(self, **kwargs: Any):
        self._driver.transaction_options = kwargs
        return _FakeTransaction(self._driver)


class _FakeDriver:
    def __init__(self, records: list[dict[str, Any]]):
        self.result = _FakeResult(records)
        self.query = ""
        self.parameters: dict[str, Any] = {}
        self.session_options: dict[str, Any] = {}
        self.transaction_options: dict[str, Any] = {}

    def session(self, **kwargs: Any):
        self.session_options = kwargs
        return _FakeSession(self)


def _storage(driver: _FakeDriver) -> Neo4JStorage:
    storage = Neo4JStorage(
        namespace="test",
        global_config={},
        embedding_func=None,
        workspace="base",
    )
    storage._driver = driver
    storage._DATABASE = "neo4j"
    return storage


def test_readonly_validator_accepts_read_query_and_appends_limit():
    query = validate_read_only_cypher("MATCH (n) RETURN n", max_records=20)

    assert query.endswith("LIMIT $__lightrag_cypher_limit")


@pytest.mark.parametrize(
    "query",
    [
        "CREATE (n) RETURN n",
        "MATCH (n) DELETE n RETURN n",
        "MATCH (n) RETURN n; MATCH (m) RETURN m",
        "MATCH (n) CALL db.labels() YIELD label RETURN label",
        "MATCH (n) RETURN n LIMIT $limit",
    ],
)
def test_readonly_validator_rejects_unsafe_or_unbounded_forms(query: str):
    with pytest.raises(ReadOnlyCypherError):
        validate_read_only_cypher(query, max_records=20)


def test_readonly_validator_ignores_keywords_inside_string_literals_and_comments():
    query = validate_read_only_cypher(
        "MATCH (n) WHERE n.entity_id = 'create' // DELETE is a comment\nRETURN n",
        max_records=20,
    )

    assert "LIMIT $__lightrag_cypher_limit" in query


@pytest.mark.asyncio
@pytest.mark.offline
async def test_cypher_explorer_serializes_semantic_relation_direction():
    semantic_source = _FakeNode(1, entity_id="Cause")
    semantic_target = _FakeNode(2, entity_id="Effect")
    relationship = _FakeRelationship(
        7,
        semantic_target,
        semantic_source,
        semantic_src_id="Cause",
        semantic_tgt_id="Effect",
        relation_type="causes",
        relation_importance=0.91,
    )
    driver = _FakeDriver(
        [{"source": semantic_source, "edge": relationship, "target": semantic_target}]
    )

    result = await _storage(driver).execute_readonly_cypher(
        "MATCH (source)-[edge:DIRECTED]-(target) RETURN source, edge, target",
        max_records=20,
    )

    assert result["columns"] == ["source", "edge", "target"]
    assert result["rows"][0]["values"] == {
        "source": "Cause",
        "edge": "causes",
        "target": "Effect",
    }
    assert result["edges"] == [
        {
            "id": "7",
            "type": "DIRECTED",
            "source": "1",
            "target": "2",
            "properties": {
                "semantic_src_id": "Cause",
                "semantic_tgt_id": "Effect",
                "relation_type": "causes",
                "relation_importance": 0.91,
            },
        }
    ]
    assert driver.parameters["__lightrag_cypher_limit"] == 20
    assert driver.session_options == {"database": "neo4j", "default_access_mode": "READ"}
    assert driver.transaction_options == {"timeout": 5.0}
    assert driver.result.consumed is True
