import gzip
import json

from scripts.audit_extraction_cache_terms import inspect


def test_cache_audit_distinguishes_model_omission_from_parser_loss(tmp_path):
    cache = tmp_path / "cache.json.gz"
    artifact = tmp_path / "artifact.json"
    with gzip.open(cache, "wt", encoding="utf-8") as stream:
        json.dump({
            "one": {"return": json.dumps({
                "entities": [{"name": "Local Potential Change"}],
                "relationships": [],
            }), "original_prompt": "private source text"},
            "two": {"return": json.dumps({"entities": [], "relationships": []})},
        }, stream)
    artifact.write_text(json.dumps({
        "documents": [{"chunk_results": [{"nodes": [], "edges": []}]}]
    }), encoding="utf-8")

    report = inspect(cache, artifact, ["Local Potential Change", "Electrode Spacing Change"])

    assert report["cache_records"] == 2
    assert report["terms"]["Local Potential Change"] == {
        "raw_text_mentions": 1,
        "raw_structured_endpoint": True,
        "parsed_structured_endpoint": False,
        "raw_endpoint_contains": True,
        "parsed_endpoint_contains": False,
        "raw_matching_endpoints": ["local potential change"],
        "parsed_matching_endpoints": [],
        "parsed_matching_edges": [],
    }
    assert report["terms"]["Electrode Spacing Change"]["raw_structured_endpoint"] is False
    assert "private source text" not in json.dumps(report)
