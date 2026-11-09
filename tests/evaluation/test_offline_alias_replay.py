import pytest

from scripts.offline_alias_replay import render_review, replay


ALIASES = {"version": 1, "concepts": [{"canonical": "Temperature Prediction", "aliases": ["Temperature Predictions"]}]}


def edge(identifier, source, target, relation="causes", **extra):
    return {
        "id": identifier, "semantic_src_id": source, "semantic_tgt_id": target,
        "directionality": "directed", "relation_type": relation,
        "source_id": f"chunk-{identifier}", **extra,
    }


def test_alias_connects_semantic_hops_and_preserves_sources():
    result = replay({"edges": [
        edge("1", "Model", "Temperature Prediction"),
        edge("2", "Temperature Predictions", "Capacity Fade"),
    ]}, ALIASES)
    assert result["baseline_path_count"] == 0
    assert result["additional_path_count"] == 1
    assert result["causal_additional_count"] == 1
    path = result["additional_paths"][0]
    assert path["original_nodes"] == ["Model", "Temperature Prediction", "Capacity Fade"]
    assert [hop["source_id"] for hop in path["hops"]] == ["chunk-1", "chunk-2"]


def test_wltc_converging_edges_are_not_a_directed_path():
    result = replay({"edges": [
        edge("1", "Model", "Temperature Prediction", "produces"),
        edge("2", "WLTC", "Temperature Predictions", "measures"),
    ]}, ALIASES)
    assert result["additional_path_count"] == 0


def test_state_and_distinct_quantity_are_not_auto_merged():
    result = replay({"edges": [
        edge("1", "Cooling", "Decreased Temperature"),
        edge("2", "Temperature", "Capacity Fade"),
        edge("3", "Temperature Rise Rate", "Heat"),
    ]}, ALIASES)
    assert result["additional_path_count"] == 0


def test_projected_cycle_is_rejected():
    result = replay({"edges": [
        edge("1", "Temperature Prediction", "X"),
        edge("2", "X", "Temperature Predictions"),
    ]}, ALIASES)
    assert result["additional_path_count"] == 0


def test_existing_and_duplicate_paths_not_counted_as_new():
    result = replay({"edges": [
        edge("1", "A", "B"), edge("2", "B", "C"),
        edge("3", "A", "B", directionality="undirected"),
    ]}, ALIASES)
    assert result["baseline_path_count"] == 1
    assert result["additional_path_count"] == 0


def test_duplicate_ids_rejected():
    with pytest.raises(ValueError, match="Duplicate edge id"):
        replay({"edges": [edge("same", "A", "B"), edge("same", "B", "C")]}, ALIASES)


def test_mixed_path_and_review_keep_original_sources():
    result = replay({"edges": [
        edge("1", "Model", "Temperature Prediction", "produces"),
        edge("2", "Temperature Predictions", "Capacity Fade", "affects"),
    ]}, ALIASES)
    assert result["mixed_additional_count"] == 1
    assert result["causal_additional_count"] == 0
    report = render_review(result)
    assert "Model --[produces]--> Temperature Prediction" in report
    assert "chunk-2" in report


def test_lexical_leads_require_causal_neighbors_on_both_sides():
    result = replay({"edges": [
        edge("1", "Heat", "Battery Model"),
        edge("2", "Battery Models", "Failure"),
        edge("3", "Heat", "Temperature Rise Rate"),
        edge("4", "Temperature Rise Rates", "Failure", "studies"),
        edge("5", "Heat", "Higher Temperature"),
        edge("6", "Temperature", "Failure"),
    ]}, ALIASES)
    pairs = {(item["left"], item["right"]) for item in result["suggested_aliases"]}
    assert ("Battery Model", "Battery Models") in pairs
    assert ("Temperature Rise Rate", "Temperature Rise Rates") not in pairs
    assert not any("Higher Temperature" in pair for pair in pairs)
