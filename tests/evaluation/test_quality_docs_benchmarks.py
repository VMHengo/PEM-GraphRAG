"""Audit the paper-based gold data and its compatibility with the live runner."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import unicodedata

import pytest

from lightrag.adaptive_retrieval import route_retrieval_query
from lightrag.evaluation.live_benchmark import (
    _directed_query_param,
    benchmark_document_preflight,
    list_benchmarks,
    load_benchmark_file,
    score_graph_cases,
    term_matches,
)
from lightrag.evaluation.semantic_matching import path_match, relation_match


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "evaluation" / "benchmarks"
PDFS = ROOT / "test_documents" / "quality_docs"
BENCHMARKS = [
    load_benchmark_file(DATA / f"pem_quality_docs_{suffix}.json")
    for suffix in ("core", "multihop")
]
SOURCES = {source["id"]: source for source in BENCHMARKS[0]["document_scope"]}


def _normal_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"[-\u00ad]\s*\n\s*", "", text)
    return " ".join(re.findall(r"\w+", text))


def test_benchmarks_are_discoverable_and_cover_the_exact_local_corpus(monkeypatch):
    monkeypatch.setenv("EVALUATION_BENCHMARK_DIR", str(DATA))
    refs = {ref.id: ref for ref in list_benchmarks()}
    assert len(SOURCES) == 10
    assert refs["pem_quality_docs_core"].case_count == 30
    assert refs["pem_quality_docs_multihop"].case_count == 18

    files = [source["file"] for source in SOURCES.values()]
    for benchmark in BENCHMARKS:
        assert {source["file"] for source in benchmark["document_scope"]} == set(files)
        assert benchmark_document_preflight(benchmark, files)["compatible"]
        assert not benchmark_document_preflight(benchmark, files[1:])["compatible"]


@pytest.mark.parametrize("benchmark", BENCHMARKS, ids=lambda item: item["id"])
def test_gold_cases_have_resolvable_evidence_and_scientific_review_guidance(benchmark):
    cases = benchmark["cases"]
    assert len({case["id"] for case in cases}) == len(cases)
    source_counts = Counter()
    for case in cases:
        assert case["question"].strip()
        assert case["hl_keywords"] and case["ll_keywords"]
        assert case["expected_entities"] and case["expected_relations"]
        assert case["must_include"] and case["expected_documents"]
        assert len(case["expected_answer"]) >= 150
        assert case["unacceptable_claims"]
        evidence = {span["id"]: span for span in case["evidence"]}
        assert len(evidence) == len(case["evidence"])
        for span in evidence.values():
            source = SOURCES[span["document"]]
            assert 1 <= span["page"] <= source["pdf_pages"]
            assert span["anchor"] and span["section"] and span["support"]
        source_counts.update({span["document"] for span in evidence.values()})
        for relation in case["expected_relations"]:
            assert relation["source"] != relation["target"]
            assert relation["directionality"] == "directed"
            assert set(relation["evidence_ids"]) <= evidence.keys()
            assert relation["evidence_ids"]
            assert all(
                0 <= score <= 1
                for score in relation["accepted_relation_types"].values()
            )
        for document in case["expected_documents"]:
            assert any(
                term_matches(document, SOURCES[span["document"]]["file"])
                for span in evidence.values()
            ), (case["id"], document)
    assert set(source_counts) == set(SOURCES)
    if benchmark["benchmark_tier"] == "core":
        assert set(source_counts.values()) == {3}
        assert not any(case.get("expected_directed_paths") for case in cases)


def test_directed_gold_is_connected_evidenced_and_compatible_with_all_strategies():
    cases = BENCHMARKS[1]["cases"]
    assert sum(case["expected_edge_direction"] == "in" for case in cases) >= 5
    assert sum(len(case["expected_documents"]) == 2 for case in cases) == 2
    assert {case["hop_depth"] for case in cases} == {2, 3}
    for case in cases:
        for strategy in ("normal", "directed", "combined", "auto"):
            param = _directed_query_param(case, BENCHMARKS[1], strategy)
            param.__post_init__()
            route = route_retrieval_query(case["question"], param)
            assert route.edge_direction == case["expected_edge_direction"], case["id"]
            assert route.effective_strategy == (
                "combined" if strategy == "auto" else strategy
            )
        for path in case["expected_directed_paths"]:
            nodes = path.get("traversal_nodes") or path["nodes"]
            assert (
                2 <= len(path["relation_types"]) == len(nodes) - 1 <= case["hop_depth"]
            )
            assert len(set(nodes)) == len(nodes)
            assert len(path["accepted_relation_types"]) == len(path["relation_types"])
            assert set(path["relation_types"]) <= set(route.target_relation_types)
            assert path["require_citations"] is True
            for document in path["source_documents"]:
                assert any(
                    term_matches(document, expected)
                    for expected in case["expected_documents"]
                )
            for index, predicate in enumerate(path["relation_types"]):
                source, target = nodes[index : index + 2]
                if case["expected_edge_direction"] == "in":
                    source, target = target, source
                gold_edge = {
                    "source": source,
                    "target": target,
                    "relation_type": predicate,
                    "directionality": "directed",
                }
                assert any(
                    relation_match(relation, gold_edge)["exact"]
                    for relation in case["expected_relations"]
                ), (case["id"], gold_edge)


@pytest.mark.parametrize("case", BENCHMARKS[1]["cases"], ids=lambda item: item["id"])
def test_gold_paths_and_declared_aliases_receive_full_semantic_credit(case):
    for path in case["expected_directed_paths"]:
        nodes = path.get("traversal_nodes") or path["nodes"]
        for use_aliases in (False, True):
            actual_nodes = [
                (path.get("node_aliases", {}).get(str(i)) or [node])[0]
                if use_aliases
                else node
                for i, node in enumerate(nodes)
            ]
            edges = []
            for i, predicate in enumerate(path["relation_types"]):
                source, target = actual_nodes[i : i + 2]
                if case["expected_edge_direction"] == "in":
                    source, target = target, source
                edges.append(
                    {"source": source, "target": target, "relation_type": predicate}
                )
            actual = {
                "nodes": actual_nodes,
                "edges": edges,
                "file_paths": path["source_documents"],
                "reference_ids": ["source-chunk-1"],
            }
            match = path_match(
                path, actual, traversal_direction=case["expected_edge_direction"]
            )
            assert match["score"] == 1, (case["id"], use_aliases, match)


def test_real_gold_accepts_reviewed_predicates_but_prefers_correct_endpoints():
    relation = BENCHMARKS[0]["cases"][0]["expected_relations"][0]
    edge = {
        "source": "Melted Separator",
        "target": "Short Circuit",
        "relation_type": "leads_to",
        "directionality": "directed",
    }
    assert relation_match(relation, edge)["score"] == 1
    reversed_edge = {**edge, "source": edge["target"], "target": edge["source"]}
    assert relation_match(relation, reversed_edge)["score"] < 1


@pytest.mark.parametrize("benchmark", BENCHMARKS, ids=lambda item: item["id"])
def test_existing_graph_scorer_accepts_the_complete_gold_without_api_calls(benchmark):
    node_names = set()
    edges = []
    for case in benchmark["cases"]:
        node_names.update(case["expected_entities"])
        for relation in case["expected_relations"]:
            node_names.update((relation["source"], relation["target"]))
            edges.append(
                {
                    "source": relation["source"],
                    "target": relation["target"],
                    "relation_type": relation["relation_type"],
                    "directionality": "directed",
                    "relation_importance": 0.8,
                    "chain_role": "causal",
                }
            )
    _, summary = score_graph_cases(
        benchmark, [{"entity_id": name} for name in node_names], edges
    )
    assert summary["entity_score"] == 100
    assert summary["relation_score"] == 100


@pytest.mark.parametrize("source_id", list(SOURCES))
def test_evidence_anchors_exist_on_declared_pages_of_the_fingerprinted_pdfs(source_id):
    source = SOURCES[source_id]
    path = PDFS / source["file"]
    if not path.exists():
        pytest.skip("Local reference PDF is not distributed with the repository")
    pypdf = pytest.importorskip("pypdf")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == source["sha256"]
    reader = pypdf.PdfReader(path)
    assert len(reader.pages) == source["pdf_pages"]
    pages = {}
    for benchmark in BENCHMARKS:
        for case in benchmark["cases"]:
            for span in case["evidence"]:
                if span["document"] != source_id:
                    continue
                page = span["page"]
                if page not in pages:
                    pages[page] = _normal_text(
                        reader.pages[page - 1].extract_text() or ""
                    )
                assert _normal_text(span["anchor"]) in pages[page], (
                    case["id"],
                    source_id,
                    page,
                    span["anchor"],
                )


def test_json_files_have_no_duplicate_keys():
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            assert key not in result, f"Duplicate benchmark key: {key}"
            result[key] = value
        return result

    for suffix in ("core", "multihop"):
        json.loads(
            (DATA / f"pem_quality_docs_{suffix}.json").read_text(encoding="utf-8"),
            object_pairs_hook=unique_pairs,
        )
