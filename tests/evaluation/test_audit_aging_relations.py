from scripts.audit_aging_relations import audit_zero_relations


def test_audit_distinguishes_parsed_match_from_missing_assertion():
    result = {
        "benchmark": {"id": "aging"},
        "cases": {
            "graph": [
                {
                    "id": "heat",
                    "relation_checks": [
                        {
                            "score": 0,
                            "expected": {
                                "source": "Total Heat",
                                "target": "Irreversible Heat",
                                "relation_type": "contains",
                                "directionality": "directed",
                                "accepted_inverse_relation_types": {"part_of": 1},
                            },
                        },
                        {
                            "score": 0,
                            "expected": {
                                "source": "Irreversible Heat",
                                "target": "Cell Failure",
                                "relation_type": "causes",
                                "directionality": "directed",
                            },
                        },
                    ],
                }
            ]
        },
    }
    artifact = {
        "documents": [
            {
                "chunk_results": [
                    {
                        "nodes": [
                            {
                                "records": [
                                    {"entity_name": "Total Heat"},
                                    {"entity_name": "Irreversible Heat"},
                                ]
                            }
                        ],
                        "edges": [
                            {
                                "records": [
                                    {
                                        "semantic_src_id": "Irreversible Heat",
                                        "semantic_tgt_id": "Total Heat",
                                        "relation_type": "part_of",
                                        "directionality": "directed",
                                    }
                                ]
                            }
                        ],
                    }
                ]
            }
        ]
    }

    report = audit_zero_relations(result, artifact)

    assert report["zero_checks"] == 2
    assert report["categories"] == {
        "parsed_full_match_graph_or_scoring_miss": 1,
        "parsed_endpoint_absent_or_gold_mismatch": 1,
    }
    assert report["rows"][0]["nearby_artifact_assertions"][0] == {
        "source": "Irreversible Heat",
        "relation_type": "part_of",
        "target": "Total Heat",
        "source_id": None,
        "proximity": 2.0,
    }
