"""Review diagnostics and short, unverified source excerpts."""

from lightrag_mcp.evidence import propose_relation_context
from lightrag_mcp.exploration import format_exploration


def test_context_includes_neighboring_sentences_and_locates_candidate():
    content = (
        "Earlier conditions matter. Electrode Calendering reduces Cathode Porosity. "
        "The next step depends on the electrolyte. Unrelated fourth sentence."
    )
    context = propose_relation_context(content, "Electrode Calendering", "Cathode Porosity")
    assert context is not None
    assert "Earlier conditions matter." in context["text"]
    assert "The next step depends on the electrolyte." in context["text"]
    assert "Unrelated fourth sentence." not in context["text"]
    assert context["text"][context["match_start"]:context["match_end"]] == (
        "Electrode Calendering reduces Cathode Porosity."
    )
    assert propose_relation_context(content, "Missing", "Cathode Porosity") is None


def test_exploration_reports_filter_reasons_and_short_context():
    valid = {
        "nodes": ["Electrode Calendering", "Cathode Porosity", "Lithium Plating"],
        "edges": [
            {"source": "Electrode Calendering", "target": "Cathode Porosity", "relation_type": "affects", "directionality": "directed", "source_ids": ["c1"]},
            {"source": "Cathode Porosity", "target": "Lithium Plating", "relation_type": "causes", "directionality": "directed", "source_ids": ["c2"]},
        ],
    }
    same_domain = {
        "nodes": ["Electrode Calendering", "Cathode Porosity", "Electrode Drying Process"],
        "edges": [valid["edges"][0], {**valid["edges"][1], "target": "Electrode Drying Process"}],
    }
    payload = {
        "data": {"chunks": [
            {"chunk_id": "c1", "file_path": "paper.pdf", "content": "Earlier conditions matter. Electrode Calendering affects Cathode Porosity. The cell was measured."},
            {"chunk_id": "c2", "file_path": "paper.pdf", "content": "Cathode Porosity causes Lithium Plating."},
        ]},
        "metadata": {"directed_paths": {"status": "completed", "paths": [valid, same_domain]}},
    }
    result = format_exploration(payload, start="Electrode Calendering")
    assert result["paths_examined"] == 2
    assert result["candidate_count"] == 1
    assert result["excluded_paths"] == {"same_domain": 1}
    excerpt = result["connections"][0]["path"][0]["sources"][0]["context_excerpt"]
    assert excerpt["status"] == "candidate_mention_only"
    assert "The cell was measured." in excerpt["text"]
