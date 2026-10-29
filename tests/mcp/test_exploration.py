import json

from lightrag_mcp import exploration
from lightrag_mcp.exploration import (
    classify_domain,
    classify_subject,
    format_exploration,
)


def _path(*, relation="causes", source_ids=("chunk-1", "chunk-2")):
    return {
        "nodes": ["Electrode Calendering", "Cathode Porosity", "Lithium Plating"],
        "edges": [
            {
                "source": "Electrode Calendering",
                "target": "Cathode Porosity",
                "relation_type": relation,
                "directionality": "directed",
                "source_ids": [source_ids[0]],
            },
            {
                "source": "Cathode Porosity",
                "target": "Lithium Plating",
                "relation_type": "leads_to",
                "directionality": "directed",
                "source_ids": [source_ids[1]],
            },
        ],
    }


def _payload(paths):
    return {
        "data": {
            "chunks": [
                {
                    "chunk_id": "chunk-1",
                    "file_path": "a.pdf",
                    "content": "First passage",
                },
                {
                    "chunk_id": "chunk-2",
                    "file_path": "b.pdf",
                    "content": "Second passage",
                },
            ],
            "references": [
                {"file_path": "a.pdf", "source_url": "https://example.org/a"}
            ],
        },
        "metadata": {"directed_paths": {"status": "completed", "paths": paths}},
    }


def test_classify_domain_is_provisional_and_unknown_stays_unknown():
    assert classify_domain("Electrode Calendering") == "Fertigung"
    assert classify_domain("Cathode Porosity") == "Eigenschaften und Transport"
    assert classify_domain("Lithium Plating") == "Degradation und Alterung"
    assert classify_domain("Unmapped Technical Term") is None


def test_subject_taxonomy_is_multilabel_and_exact():
    subject = classify_subject("Lithium Plating")
    assert subject["domains"] == [
        "Degradation und Alterung",
        "Zellqualitaet und Sicherheit",
    ]
    assert subject["status"] == "provisional"
    assert classify_subject("Lithium Plating Risk")["status"] == "provisional_keyword"
    assert classify_subject("Unmapped Technical Term")["status"] == "unknown"
    fallback = classify_subject("Aged Electrode Resistance")
    assert fallback["status"] == "provisional_keyword"
    assert fallback["domains"] == [
        "Eigenschaften und Transport",
        "Materialien und Komponenten",
    ]


def test_subject_resolution_respects_source_scope_and_ambiguity(tmp_path, monkeypatch):
    taxonomy = {
        "version": "test",
        "review_status": "provisional",
        "concepts": [
            {"id": "global", "aliases": ["Formation"], "domains": ["Fertigung"]},
            {
                "id": "paper-specific",
                "aliases": ["Formation"],
                "domains": ["Degradation und Alterung"],
                "source_files": ["paper.pdf"],
            },
            {"id": "ambiguous-a", "aliases": ["Cell"], "domains": ["Fertigung"]},
            {"id": "ambiguous-b", "aliases": ["Cell"], "domains": ["Diagnostik"]},
        ],
    }
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(taxonomy), encoding="utf-8")
    monkeypatch.setattr(exploration, "TAXONOMY_PATH", path)
    exploration._taxonomy.cache_clear()
    try:
        assert classify_subject("Formation")["concept_id"] == "global"
        assert (
            classify_subject("Formation", source_files=("/docs/paper.pdf",))[
                "concept_id"
            ]
            == "paper-specific"
        )
        assert classify_subject("Cell")["status"] == "ambiguous"
    finally:
        exploration._taxonomy.cache_clear()


def test_exploration_keeps_indirect_hops_and_each_source():
    result = format_exploration(_payload([_path()]), start="Electrode Calendering")
    assert len(result["connections"]) == 1
    connection = result["connections"][0]
    assert connection["status"] == "unreviewed_indirect_connection"
    assert connection["hops"] == 2
    assert connection["path"][0]["sources"][0]["chunk_excerpt"] == "First passage"
    assert connection["path"][0]["sources"][0]["url"] == "https://example.org/a"
    assert connection["path"][1]["sources"][0]["chunk_id"] == "chunk-2"


def test_exploration_keeps_pdf_page_anchor_and_exact_evidence_quote():
    payload = _payload([_path()])
    payload["data"]["chunks"][0]["pdf_location"] = {
        "page": 2, "pages": [2], "status": "chunk_text_match"
    }
    payload["metadata"]["directed_paths"]["paths"][0]["edges"][0]["evidence"] = (
        "Electrode calendering decreased cathode porosity."
    )
    source = format_exploration(payload, start="Electrode Calendering")["connections"][0]["path"][0]["sources"][0]
    assert source["pdf_location"]["page"] == 2
    assert source["evidence_quote"] == "Electrode calendering decreased cathode porosity."


def test_exploration_exposes_candidate_span_without_claiming_support():
    payload = _payload([_path()])
    payload["data"]["chunks"][0]["content"] = (
        "Electrode Calendering reduces Cathode Porosity. Other text."
    )
    result = format_exploration(payload, start="Electrode Calendering")
    source = result["connections"][0]["path"][0]["sources"][0]
    assert (
        source["candidate_span"]["text"]
        == "Electrode Calendering reduces Cathode Porosity."
    )
    assert source["candidate_span"]["status"] == "candidate_mention_only"


def test_exploration_rejects_unsupported_or_unresolved_edges():
    reversed_path = _path()
    reversed_path["edges"][0]["source"] = "Cathode Porosity"
    undirected_path = _path()
    undirected_path["edges"][0]["directionality"] = "undirected"
    result = format_exploration(
        _payload(
            [
                _path(relation="does_not_cause"),
                _path(source_ids=("missing", "chunk-2")),
                reversed_path,
                undirected_path,
            ]
        ),
        start="Electrode Calendering",
    )
    assert result["connections"] == []


def test_exploration_requires_exact_start_and_marks_same_domain():
    payload = _payload([_path()])
    assert format_exploration(payload, start="Different Process")["connections"] == []
    same_domain = _path()
    same_domain["nodes"][-1] = "Electrode Drying Process"
    same_domain["edges"][-1]["target"] = "Electrode Drying Process"
    result = format_exploration(_payload([same_domain]), start="Electrode Calendering")
    assert result["connections"][0]["review_priority"] == "same_domain"
    assert result["connections"][0]["domain_distance"] == 0.0


def test_layout_coordinates_do_not_affect_exploration():
    payload = _payload([_path()])
    original = format_exploration(payload, start="Electrode Calendering")
    payload["data"]["entities"] = [
        {"entity_name": "Electrode Calendering", "x": 100000, "y": -4},
        {"entity_name": "Lithium Plating", "x": 100001, "y": -4},
    ]
    moved = format_exploration(payload, start="Electrode Calendering")
    assert moved["connections"] == original["connections"]


def test_exploration_deduplicates_targets_and_reports_missing_domain():
    result = format_exploration(
        _payload([_path(), _path()]), start="Electrode Calendering", limit=20
    )
    assert result["candidate_count"] == 1
    assert len(result["connections"]) == 1
    unknown = format_exploration(_payload([]), start="Unmapped Technical Term")
    assert (
        unknown["empty_reason"]
        == "No directed, source-resolved 2-4-hop path survived the filters."
    )


def test_exploration_suggests_retrieved_node_names_for_retry():
    payload = _payload([])
    payload["data"]["entities"] = [{"entity_name": "Electrode Calendering"}]
    result = format_exploration(payload, start="Calendering")
    assert result["suggested_start_nodes"] == ["Electrode Calendering"]
