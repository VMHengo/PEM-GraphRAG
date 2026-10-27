from typing import Any

import pytest

from lightrag.kg.neo4j_impl import Neo4JStorage


class _Result:
    def __init__(self):
        self.consumed = False

    def __aiter__(self):
        async def rows():
            yield {
                "name": "Mixing Heat",
                "found_paths": 251,
                "distinct_targets": 7,
                "example_targets": ["Capacity Fade"],
            }

        return rows()

    async def consume(self):
        self.consumed = True


class _Session:
    def __init__(self, driver):
        self.driver = driver

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def run(self, query: str, **params: Any):
        self.driver.query = query
        self.driver.params = params
        return self.driver.result


class _Driver:
    def __init__(self):
        self.result = _Result()
        self.options = None
        self.query = ""
        self.params = {}

    def session(self, **options):
        self.options = options
        return _Session(self)


@pytest.mark.asyncio
@pytest.mark.offline
async def test_recommendations_are_bounded_semantic_and_read_only():
    driver = _Driver()
    storage = Neo4JStorage("test", {}, None, workspace="pem`staging")
    storage._driver = driver
    storage._DATABASE = "neo4j"

    rows = await storage.get_review_start_recommendations(4)

    assert rows == [
        {
            "name": "Mixing Heat",
            "path_count": 250,
            "distinct_targets": 7,
            "example_targets": ["Capacity Fade"],
            "truncated": True,
        }
    ]
    assert driver.options == {"database": "neo4j", "default_access_mode": "READ"}
    assert "(n4:`pem``staging`)" in driver.query
    assert driver.query.count("LIMIT 251") == 4
    assert "semantic_src_id" in driver.query
    assert "semantic_tgt_id" in driver.query
    assert driver.params["min_importance"] == 0.45
    assert driver.params["limit"] == 20
    assert driver.result.consumed


@pytest.mark.asyncio
@pytest.mark.offline
async def test_recommendation_depth_is_validated():
    storage = Neo4JStorage("test", {}, None, workspace="staging")
    with pytest.raises(ValueError):
        await storage.get_review_start_recommendations(7)
