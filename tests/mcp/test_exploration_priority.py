"""Curated subject distance orders review, without changing evidence gates."""

from lightrag.evaluation.human_review import select_review_candidates
from lightrag_mcp.exploration import _taxonomy, classify_subject, domain_distance, format_exploration


def test_every_subject_area_has_a_bounded_curated_position():
    taxonomy = _taxonomy()
    assert set(taxonomy["domain_positions"]) == set(taxonomy["domains"])
    assert all(
        len(position) == 2 and all(0 <= coordinate <= 1 for coordinate in position)
        for position in taxonomy["domain_positions"].values()
    )


def _path(target: str) -> dict:
    return {
        "nodes": ["Mixing Heat", "Intermediate", target],
        "edges": [
            {
                "source": "Mixing Heat", "target": "Intermediate",
                "relation_type": "affects", "directionality": "directed",
                "source_ids": ["c1"],
            },
            {
                "source": "Intermediate", "target": target,
                "relation_type": "causes", "directionality": "directed",
                "source_ids": ["c2"],
            },
        ],
    }


def test_curated_map_orders_far_near_same_and_unknown_targets():
    payload = {
        "data": {"chunks": [
            {"chunk_id": "c1", "content": "Mixing heat affects an intermediate state."},
            {"chunk_id": "c2", "content": "The intermediate state causes an outcome."},
        ]},
        "metadata": {"directed_paths": {"paths": [
            _path("Unmapped Variable"), _path("Temperature"),
            _path("Electrode Calendering"), _path("Capacity Fade"),
        ]}},
    }
    result = format_exploration(payload, start="Mixing Heat", limit=20)
    cases = result["connections"]
    assert [case["to"] for case in cases] == [
        "Capacity Fade", "Electrode Calendering", "Temperature", "Unmapped Variable"
    ]
    assert [case["review_priority"] for case in cases] == [
        "cross_domain", "cross_domain", "same_domain", "unclassified"
    ]
    assert result["candidate_count"] == 4
    assert result["excluded_paths"] == {}
    assert all(case["taxonomy_version"] == result["taxonomy_version"] for case in cases)
    assert cases[-1]["domain_distance"] is None


def test_multilabel_terms_use_nearest_domain_pair():
    plating = classify_subject("Lithium Plating")["domains"]
    gas = classify_subject("Gas Generation")["domains"]
    distance, _, _ = domain_distance(plating, gas)
    assert distance == 0
    assert domain_distance(plating, ["Unknown domain"]) == (None, None, None)
    assert classify_subject("Mixing Heat")["domains"] == ["Eigenschaften und Transport"]
    assert classify_subject("Temperature")["domains"] == ["Eigenschaften und Transport"]


def test_final_session_selection_orders_across_seeds_by_distance():
    def item(start: str, target: str, distance: float | None) -> dict:
        return {
            "from": start, "to": target, "hops": 2, "path": [{}, {}],
            "domain_distance": distance,
        }

    selected = select_review_candidates([
        {"connections": [item("A", "Near", 0.1), item("A", "Unknown", None)]},
        {"connections": [item("B", "Far", 0.8), item("B", "Same", 0)]},
    ], limit=20)
    assert [case["to"] for case in selected] == ["Far", "Near", "Same", "Unknown"]
