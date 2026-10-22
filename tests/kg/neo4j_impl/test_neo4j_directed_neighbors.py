from typing import Any

import pytest

import lightrag.kg.neo4j_impl as neo4j_impl
from lightrag.kg.neo4j_impl import Neo4JStorage
from lightrag.relation_assertions import serialize_relation_assertions


class _FakeResult:
    def __init__(self, records: list[dict[str, Any]]):
        self._records = records
        self._index = 0
        self.consumed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._records):
            raise StopAsyncIteration
        record = self._records[self._index]
        self._index += 1
        return record

    async def consume(self):
        self.consumed = True


class _FakeSession:
    def __init__(self, driver: "_FakeDriver"):
        self._driver = driver

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def run(self, query: str, **parameters: Any):
        self._driver.query = query
        self._driver.parameters = parameters
        return self._driver.result


class _FakeDriver:
    def __init__(self, records: list[dict[str, Any]]):
        self.result = _FakeResult(records)
        self.query = ""
        self.parameters: dict[str, Any] = {}
        self.session_calls: list[dict[str, Any]] = []

    def session(self, **kwargs: Any):
        self.session_calls.append(kwargs)
        return _FakeSession(self)


def _storage(driver: _FakeDriver, workspace: str = "pem`staging") -> Neo4JStorage:
    storage = Neo4JStorage(
        namespace="test",
        global_config={},
        embedding_func=None,
        workspace=workspace,
    )
    storage._driver = driver
    storage._DATABASE = "neo4j"
    return storage


@pytest.mark.asyncio
@pytest.mark.offline
async def test_directed_neighbor_provider_returns_semantic_metadata_and_fallbacks():
    driver = _FakeDriver(
        [
            {
                "requested_id": "Defect X",
                "candidates": [
                    {
                        "properties": {
                            "semantic_src_id": "Uneven Coating",
                            "semantic_tgt_id": "Defect X",
                            "relation_type": "causes",
                            "directionality": "directed",
                            "relation_importance": 0.91,
                            "chain_role": "root_cause",
                            "source_id": "chunk-123",
                            "file_path": "coating.pdf",
                        },
                        "physical_src_id": "Defect X",
                        "physical_tgt_id": "Uneven Coating",
                    }
                ],
            },
            {"requested_id": "No Edge", "candidates": []},
        ]
    )
    storage = _storage(driver)

    edges_by_node = await storage.get_directed_neighbor_edges_batch(
        ["Defect X", "Defect X", "No Edge"], candidate_limit_per_node=25
    )

    assert list(edges_by_node) == ["Defect X", "No Edge"]
    edge = edges_by_node["Defect X"][0]
    assert edge["semantic_src_id"] == "Uneven Coating"
    assert edge["semantic_tgt_id"] == "Defect X"
    assert edge["src_id"] == "Defect X"
    assert edge["tgt_id"] == "Uneven Coating"
    assert edge["physical_src_id"] == "Defect X"
    assert edge["physical_tgt_id"] == "Uneven Coating"
    assert edges_by_node["No Edge"] == []
    assert driver.parameters == {
        "node_ids": ["Defect X", "No Edge"],
        "candidate_limit_per_node": 25,
        "target_relation_types": [],
        "target_chain_roles": [],
        "expand_assertions": False,
    }
    assert "UNWIND $node_ids" in driver.query
    assert "(anchor:`pem``staging` {entity_id: requested_id})" in driver.query
    assert "[r:DIRECTED]-(neighbor:`pem``staging`)" in driver.query
    assert "LIMIT $candidate_limit_per_node" in driver.query
    assert "CALL {" in driver.query
    assert "query_relevance DESC" in driver.query
    assert driver.session_calls == [
        {"database": "neo4j", "default_access_mode": "READ"}
    ]
    assert driver.result.consumed is True


@pytest.mark.asyncio
@pytest.mark.offline
async def test_directed_neighbor_provider_preserves_existing_endpoint_properties():
    driver = _FakeDriver(
        [
            {
                "requested_id": "Anchor",
                "candidates": [
                    {
                        "properties": {
                            "src_id": "Stored Source",
                            "tgt_id": "Stored Target",
                        },
                        "physical_src_id": "Physical Source",
                        "physical_tgt_id": "Physical Target",
                    }
                ],
            }
        ]
    )

    edges_by_node = await _storage(driver).get_directed_neighbor_edges_batch(
        ["Anchor"]
    )

    edge = edges_by_node["Anchor"][0]
    assert edge["src_id"] == "Stored Source"
    assert edge["tgt_id"] == "Stored Target"
    assert edge["physical_src_id"] == "Physical Source"
    assert edge["physical_tgt_id"] == "Physical Target"


@pytest.mark.asyncio
@pytest.mark.offline
async def test_directed_neighbor_provider_short_circuits_empty_input():
    driver = _FakeDriver([])

    edges_by_node = await _storage(driver).get_directed_neighbor_edges_batch([])

    assert edges_by_node == {}
    assert driver.session_calls == []


@pytest.mark.asyncio
@pytest.mark.offline
@pytest.mark.parametrize("candidate_limit_per_node", [0, 501, True, "20"])
async def test_directed_neighbor_provider_validates_candidate_limit(
    candidate_limit_per_node: object,
):
    driver = _FakeDriver([])

    with pytest.raises(ValueError, match="candidate_limit_per_node"):
        await _storage(driver).get_directed_neighbor_edges_batch(
            ["Anchor"], candidate_limit_per_node=candidate_limit_per_node
        )

    assert driver.session_calls == []


@pytest.mark.asyncio
@pytest.mark.offline
async def test_directed_neighbor_provider_rejects_non_string_node_ids():
    driver = _FakeDriver([])

    with pytest.raises(ValueError, match="node_ids"):
        await _storage(driver).get_directed_neighbor_edges_batch(["Anchor", 7])

    assert driver.session_calls == []


@pytest.mark.asyncio
@pytest.mark.offline
@pytest.mark.parametrize(
    "target_relation_types",
    ["causes", ["causes", 7], [f"relation-{index}" for index in range(51)]],
)
async def test_directed_neighbor_provider_validates_target_relation_types(
    target_relation_types: object,
):
    driver = _FakeDriver([])

    with pytest.raises(ValueError, match="target_relation_types"):
        await _storage(driver).get_directed_neighbor_edges_batch(
            ["Anchor"], target_relation_types=target_relation_types
        )

    assert driver.session_calls == []


@pytest.mark.asyncio
@pytest.mark.offline
async def test_assertion_expansion_is_explicit_and_preserves_each_direction(monkeypatch):
    assertions = [
        {
            "semantic_src_id": "A", "semantic_tgt_id": "B",
            "relation_type": "causes", "directionality": "directed",
            "source_id": "chunk-a", "ontology_iri": "urn:causes",
        },
        {
            "semantic_src_id": "B", "semantic_tgt_id": "A",
            "relation_type": "influences", "directionality": "directed",
            "source_id": "chunk-b", "ontology_iri": "",
        },
    ]
    candidate = {
        "properties": {
            "relation_type": "causes",
            "relation_assertions_json": serialize_relation_assertions(assertions),
        },
        "physical_src_id": "A", "physical_tgt_id": "B",
    }
    driver = _FakeDriver([{"requested_id": "A", "candidates": [candidate]}])
    monkeypatch.delenv("ONTOLOGY_ASSERTION_RETRIEVAL_ENABLED", raising=False)
    baseline = await _storage(driver).get_directed_neighbor_edges_batch(["A"])
    assert len(baseline["A"]) == 1

    driver = _FakeDriver([{"requested_id": "A", "candidates": [candidate]}])
    monkeypatch.setenv("ONTOLOGY_ASSERTION_RETRIEVAL_ENABLED", "true")
    expanded = await _storage(driver).get_directed_neighbor_edges_batch(["A"])
    assert {(edge["semantic_src_id"], edge["relation_type"], edge["semantic_tgt_id"])
            for edge in expanded["A"]} == {
        ("A", "causes", "B"), ("B", "influences", "A")
    }
    assert next(edge for edge in expanded["A"] if edge["relation_type"] == "influences")[
        "ontology_iri"
    ] == ""


@pytest.mark.asyncio
@pytest.mark.offline
async def test_query_relevant_assertion_is_ranked_before_high_degree_pair_cap(monkeypatch):
    candidate_limit = 25
    assertions = [
        {
            "semantic_src_id": "Relevant Cause",
            "semantic_tgt_id": "Defect X",
            "relation_type": "causes",
            "directionality": "directed",
            "source_id": "chunk-relevant",
        }
    ]
    relevant_candidate = {
        "properties": {
            "relation_type": "related_to",
            "relation_importance": 0.1,
            "relation_assertions_json": serialize_relation_assertions(assertions),
        },
        "physical_src_id": "Defect X",
        "physical_tgt_id": "Relevant Cause",
    }
    high_degree_candidates = [
        {
            "properties": {
                "relation_type": "related_to",
                "relation_importance": 1.0 - index / 1000,
            },
            "physical_src_id": "Defect X",
            "physical_tgt_id": f"Generic Neighbor {index:03d}",
        }
        for index in range(300)
    ]
    # Neo4j returns the query-ranked bounded slice. The relevant pair started
    # beyond the physical cap in importance order but is promoted by its
    # serialized assertion predicate.
    bounded_candidates = [
        relevant_candidate,
        *high_degree_candidates[: candidate_limit - 1],
    ]
    driver = _FakeDriver(
        [{"requested_id": "Defect X", "candidates": bounded_candidates}]
    )
    monkeypatch.setenv("ONTOLOGY_ASSERTION_RETRIEVAL_ENABLED", "true")
    clock = iter((10.0, 10.025))
    latency_logs: list[tuple[str, tuple[Any, ...]]] = []
    monkeypatch.setattr(neo4j_impl, "perf_counter", lambda: next(clock))
    monkeypatch.setattr(
        neo4j_impl.logger,
        "info",
        lambda message, *args: latency_logs.append((message, args)),
    )

    edges_by_node = await _storage(driver).get_directed_neighbor_edges_batch(
        ["Defect X"],
        candidate_limit_per_node=candidate_limit,
        target_relation_types=[" Causes ", "causes"],
    )

    assert any(
        edge.get("relation_type") == "causes"
        and edge.get("source_id") == "chunk-relevant"
        for edge in edges_by_node["Defect X"]
    )
    assert len(driver.parameters["target_relation_types"]) == 1
    assert driver.parameters["target_relation_types"] == ["causes"]
    assert driver.parameters["target_chain_roles"] == []
    assert len(bounded_candidates) == candidate_limit
    assert "query_relevance DESC" in driver.query
    assert driver.query.index("query_relevance DESC") < driver.query.index(
        "LIMIT $candidate_limit_per_node"
    ) < driver.query.index("collect(candidate)")
    assert driver.parameters["expand_assertions"] is True
    assert "r.relation_assertions_json" in driver.query
    assert latency_logs[0][1][-1] == 25
