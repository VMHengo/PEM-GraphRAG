import json
from pathlib import Path


FIXTURE_DIR = Path(__file__).with_name("fixtures")


def test_pem_directed_phase0_fixtures_cover_required_query_categories():
    docs = json.loads(
        (FIXTURE_DIR / "pem_directed_phase0_documents.json").read_text(
            encoding="utf-8"
        )
    )
    queries = json.loads(
        (FIXTURE_DIR / "pem_directed_phase0_queries.json").read_text(
            encoding="utf-8"
        )
    )

    assert {doc["category"] for doc in docs} >= {
        "production_chain",
        "causal_chain",
        "root_cause",
    }
    assert {query["category"] for query in queries} >= {
        "production_chain",
        "causal_chain",
        "root_cause",
    }


def test_pem_directed_phase0_query_relations_have_direction_metadata():
    queries = json.loads(
        (FIXTURE_DIR / "pem_directed_phase0_queries.json").read_text(
            encoding="utf-8"
        )
    )

    assert queries
    for query in queries:
        assert query["expected_entities"], query["id"]
        assert query["expected_relations"], query["id"]
        for relation in query["expected_relations"]:
            assert relation["source"], query["id"]
            assert relation["target"], query["id"]
            assert relation["relation_type"], query["id"]
            assert relation["directionality"] == "directed", query["id"]
            assert relation["chain_role"], query["id"]


def test_pem_directed_phase0_fixtures_include_multihop_root_cause_case():
    queries = json.loads(
        (FIXTURE_DIR / "pem_directed_phase0_queries.json").read_text(
            encoding="utf-8"
        )
    )

    multihop_root_cause_queries = [
        query
        for query in queries
        if query["category"] == "root_cause" and query["requires_multihop"]
    ]

    assert multihop_root_cause_queries
    assert any(
        "upstream" in query["query"].lower()
        for query in multihop_root_cause_queries
    )
