"""Review text matching must not confuse a match with relation verification."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from lightrag.evidence_quotes import locate_exact_quote
from lightrag.operate import _process_json_extraction_result
from lightrag.relation_assertions import (
    parse_relation_assertions,
    serialize_relation_assertions,
)
from lightrag.directed_retrieval import normalize_directed_edge
from lightrag_mcp.evidence import (
    locate_exact_quote as gateway_locate_exact_quote,
    propose_relation_context,
)


def test_mcp_evidence_imports_without_lightrag_core():
    root = Path(__file__).resolve().parents[2]
    script = (
        "import builtins, sys; "
        f"sys.path.insert(0, {str(root)!r}); "
        "original = builtins.__import__; "
        "builtins.__import__ = lambda name, *args, **kwargs: "
        "(_ for _ in ()).throw(ImportError(name)) if name == 'lightrag' "
        "or name.startswith('lightrag.') else original(name, *args, **kwargs); "
        "import lightrag_mcp.evidence"
    )
    result = subprocess.run(
        [sys.executable, "-S", "-c", script], capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_core_and_gateway_quote_matching_agree():
    content = "Mixing heat\nbecomes important under high-rate cycling."
    quote = "Mixing heat becomes important under high–rate cycling."
    assert gateway_locate_exact_quote(content, quote) == locate_exact_quote(content, quote)


def test_exact_quote_survives_pdf_line_wrapping_and_dash_variants():
    content = "Before. Mixing heat\nbecomes important in high–rate cycling. After."
    found = locate_exact_quote(
        content, "Mixing heat becomes important in high-rate cycling."
    )
    assert found is not None
    assert content[found["start"] : found["end"]] == found["text"]
    assert "heat\nbecomes" in found["text"]


def test_legacy_description_is_located_without_both_canonical_labels():
    content = (
        "Earlier result. Capacity fade at high temperatures\n"
        "is strongly dependent on the EC electrolyte. Later result."
    )
    context = propose_relation_context(
        content,
        "Cell Temperature",
        "Capacity Fade",
        description="Capacity fade at high temperatures is strongly dependent on the EC electrolyte.",
    )
    assert context is not None
    assert context["status"] == "exact_text_match"
    assert "Capacity fade at high temperatures\n" in context["text"]
    assert context["text"][context["match_start"] : context["match_end"]].startswith(
        "Capacity fade at high temperatures"
    )


def test_co_mention_remains_unverified_and_does_not_span_footnotes():
    content = "Cathode\nPorosity affects ionic transport resistance.\n\nAppendix text."
    context = propose_relation_context(
        content, "Cathode Porosity", "Ionic Transport Resistance"
    )
    assert context is not None
    assert context["status"] == "candidate_mention_only"
    assert "Appendix text" not in context["text"]


def test_paraphrase_returns_related_text_without_claiming_support():
    content = "Capacity fade at high temperatures is strongly dependent on the EC electrolyte."
    context = propose_relation_context(
        content,
        "Cell Temperature",
        "Capacity Fade",
        description="Temperature increases capacity fade during storage.",
    )
    assert context is not None
    assert context["status"] == "candidate_related_text"
    assert "Capacity fade at high temperatures" in context["text"]


@pytest.mark.asyncio
@pytest.mark.offline
async def test_parser_accepts_only_quotes_found_in_the_source_chunk():
    relationship = {
        "source": "Mixing Heat",
        "target": "Temperature",
        "description": "Mixing heat affects temperature.",
        "relation_type": "affects",
        "directionality": "directed",
    }
    content = "Mixing heat\naffects temperature during charging."
    payload = {
        "entities": [],
        "relationships": [
            {
                **relationship,
                "evidence_quote": "Mixing heat affects temperature during charging.",
            },
        ],
    }
    _, edges = await _process_json_extraction_result(
        json.dumps(payload), "chunk-1", 1, "paper.pdf", content
    )
    assert edges[("Mixing Heat", "Temperature")][0]["evidence"] == content

    payload["relationships"][0]["evidence_quote"] = "Temperature always doubles."
    _, edges = await _process_json_extraction_result(
        json.dumps(payload), "chunk-1", 1, "paper.pdf", content
    )
    assert "evidence" not in edges[("Mixing Heat", "Temperature")][0]


def test_assertion_quote_survives_storage_and_directed_edge_normalization():
    assertion = {
        "semantic_src_id": "Mixing Heat",
        "semantic_tgt_id": "Temperature",
        "relation_type": "affects",
        "directionality": "directed",
        "source_id": "chunk-1",
        "evidence": "Mixing heat affects temperature.",
    }
    stored = serialize_relation_assertions([assertion], "Mixing Heat", "Temperature")
    [loaded] = parse_relation_assertions(
        {"relation_assertions_json": stored}, "Mixing Heat", "Temperature"
    )
    edge = normalize_directed_edge(loaded)
    assert edge is not None
    assert edge.evidence == assertion["evidence"]
    assert edge.source_ids == ("chunk-1",)
