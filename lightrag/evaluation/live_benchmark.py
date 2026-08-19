"""Live benchmark helpers for PEM GraphRAG quality checks.

The live benchmark runner scores the current LightRAG graph and, when
requested, the current query pipeline against explicit benchmark cases.  It is
designed for admin/dev use from the WebUI and avoids provider-specific graph
queries so it can run on Neo4j, NetworkX, and other storage backends that
implement the standard graph interface.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from lightrag.base import QueryParam
from lightrag.utils import logger


BenchmarkMode = Literal["graph", "retrieval", "full"]


@dataclass(frozen=True)
class BenchmarkRef:
    id: str
    name: str
    description: str
    path: Path
    case_count: int


_WORD_RE = re.compile(r"[a-z0-9]+")


def canonical_text(value: Any) -> str:
    return " ".join(_WORD_RE.findall(str(value or "").lower()))


def term_matches(expected: Any, actual: Any) -> bool:
    expected_canonical = canonical_text(expected)
    actual_canonical = canonical_text(actual)
    if not expected_canonical or not actual_canonical:
        return False
    return (
        expected_canonical == actual_canonical
        or expected_canonical in actual_canonical
        or actual_canonical in expected_canonical
    )


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _default_benchmark_dirs(working_dir: str | None = None) -> list[Path]:
    repo_root = Path.cwd()
    package_root = Path(__file__).resolve().parents[2]
    candidates: list[Path] = []

    env_dir = os.getenv("EVALUATION_BENCHMARK_DIR")
    if env_dir:
        candidates.append(Path(env_dir))

    if working_dir:
        data_root = Path(working_dir).expanduser().resolve().parent
        candidates.append(data_root / "evaluation" / "benchmarks")

    candidates.extend(
        [
            repo_root / "evaluation" / "benchmarks",
            package_root / "evaluation" / "benchmarks",
            Path(__file__).resolve().parent / "benchmarks",
        ]
    )

    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved not in seen:
            unique.append(resolved)
            seen.add(resolved)
    return unique


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _benchmark_id_from_path(path: Path) -> str:
    return path.stem


def load_benchmark_file(path: Path) -> dict[str, Any]:
    benchmark = _load_json(path)
    benchmark.setdefault("id", _benchmark_id_from_path(path))
    cases = benchmark.get("cases")
    if not isinstance(cases, list):
        raise ValueError(f"{path} must contain a cases list")
    return benchmark


def list_benchmarks(working_dir: str | None = None) -> list[BenchmarkRef]:
    refs: dict[str, BenchmarkRef] = {}
    for directory in _default_benchmark_dirs(working_dir):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                benchmark = load_benchmark_file(path)
            except Exception as exc:
                logger.warning("Skipping invalid benchmark file %s: %s", path, exc)
                continue
            benchmark_id = str(benchmark.get("id") or _benchmark_id_from_path(path))
            refs.setdefault(
                benchmark_id,
                BenchmarkRef(
                    id=benchmark_id,
                    name=str(benchmark.get("name") or benchmark_id),
                    description=str(benchmark.get("description") or ""),
                    path=path,
                    case_count=len(_as_list(benchmark.get("cases"))),
                ),
            )
    return sorted(refs.values(), key=lambda item: item.id)


def load_benchmark(benchmark_id: str, working_dir: str | None = None) -> dict[str, Any]:
    safe_id = Path(benchmark_id).name
    for ref in list_benchmarks(working_dir):
        if ref.id == safe_id:
            benchmark = load_benchmark_file(ref.path)
            benchmark["path"] = str(ref.path)
            return benchmark
    raise FileNotFoundError(f"Benchmark '{benchmark_id}' was not found")


def _node_name(node: dict[str, Any]) -> str:
    for key in ("entity_id", "id", "name", "Name"):
        value = node.get(key)
        if value:
            return str(value)
    return ""


def _edge_source(edge: dict[str, Any]) -> str:
    return str(edge.get("semantic_src_id") or edge.get("source") or "")


def _edge_target(edge: dict[str, Any]) -> str:
    return str(edge.get("semantic_tgt_id") or edge.get("target") or "")


def _edge_relation_type(edge: dict[str, Any]) -> str:
    return canonical_text(edge.get("relation_type") or edge.get("keywords") or "")


def _edge_directionality(edge: dict[str, Any]) -> str:
    return canonical_text(edge.get("directionality") or "unknown")


def _edge_description(edge: dict[str, Any]) -> str:
    return str(edge.get("description") or "")


def _find_entity(expected: Any, nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    for node in nodes:
        if term_matches(expected, _node_name(node)):
            return node
    return None


def _find_relation(
    expected: dict[str, Any],
    edges: list[dict[str, Any]],
) -> dict[str, Any] | None:
    expected_source = expected.get("source")
    expected_target = expected.get("target")
    expected_type = canonical_text(expected.get("relation_type"))
    expected_directionality = canonical_text(expected.get("directionality"))

    for edge in edges:
        source_match = (
            not expected_source or term_matches(expected_source, _edge_source(edge))
        )
        target_match = (
            not expected_target or term_matches(expected_target, _edge_target(edge))
        )
        type_match = (
            not expected_type or expected_type == _edge_relation_type(edge)
        )
        direction_match = (
            not expected_directionality
            or expected_directionality == _edge_directionality(edge)
        )
        if source_match and target_match and type_match and direction_match:
            return edge
    return None


def _metadata_coverage(edges: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(edges)
    if total == 0:
        return {
            "total_edges": 0,
            "directionality": 0.0,
            "relation_type": 0.0,
            "relation_importance": 0.0,
            "chain_role": 0.0,
            "specific_relation_type": 0.0,
        }

    generic_types = {
        "",
        "related to",
        "associated with",
        "mentions",
        "co occurs with",
        "cooccurs with",
        "related",
    }
    with_directionality = 0
    with_relation_type = 0
    with_importance = 0
    with_chain_role = 0
    specific_types = 0

    for edge in edges:
        directionality = canonical_text(edge.get("directionality"))
        relation_type = _edge_relation_type(edge)
        chain_role = canonical_text(edge.get("chain_role"))
        importance = edge.get("relation_importance")

        if directionality and directionality != "unknown":
            with_directionality += 1
        if relation_type:
            with_relation_type += 1
        if importance is not None:
            with_importance += 1
        if chain_role and chain_role != "other":
            with_chain_role += 1
        if relation_type not in generic_types:
            specific_types += 1

    return {
        "total_edges": total,
        "directionality": with_directionality / total,
        "relation_type": with_relation_type / total,
        "relation_importance": with_importance / total,
        "chain_role": with_chain_role / total,
        "specific_relation_type": specific_types / total,
    }


def _format_percent(value: float) -> float:
    return round(value * 100, 2)


def score_graph_cases(
    benchmark: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    results: list[dict[str, Any]] = []
    entity_scores: list[float] = []
    relation_scores: list[float] = []

    for case in _as_list(benchmark.get("cases")):
        case_id = str(case.get("id") or case.get("question") or "case")
        expected_entities = _as_list(case.get("expected_entities"))
        expected_relations = _as_list(case.get("expected_relations"))

        entity_checks: list[dict[str, Any]] = []
        relation_checks: list[dict[str, Any]] = []

        for entity in expected_entities:
            found = _find_entity(entity, nodes)
            entity_checks.append(
                {
                    "expected": str(entity),
                    "passed": found is not None,
                    "matched": _node_name(found) if found else None,
                }
            )

        for relation in expected_relations:
            if not isinstance(relation, dict):
                continue
            found = _find_relation(relation, edges)
            relation_checks.append(
                {
                    "expected": relation,
                    "passed": found is not None,
                    "matched": {
                        "source": _edge_source(found),
                        "relation_type": found.get("relation_type"),
                        "target": _edge_target(found),
                        "directionality": found.get("directionality"),
                        "relation_importance": found.get("relation_importance"),
                        "chain_role": found.get("chain_role"),
                        "description": _edge_description(found),
                    }
                    if found
                    else None,
                }
            )

        entity_score = (
            sum(1 for check in entity_checks if check["passed"]) / len(entity_checks)
            if entity_checks
            else None
        )
        relation_score = (
            sum(1 for check in relation_checks if check["passed"])
            / len(relation_checks)
            if relation_checks
            else None
        )

        if entity_score is not None:
            entity_scores.append(entity_score)
        if relation_score is not None:
            relation_scores.append(relation_score)

        results.append(
            {
                "id": case_id,
                "question": str(case.get("question") or ""),
                "entity_score": _format_percent(entity_score)
                if entity_score is not None
                else None,
                "relation_score": _format_percent(relation_score)
                if relation_score is not None
                else None,
                "entity_checks": entity_checks,
                "relation_checks": relation_checks,
            }
        )

    summary = {
        "entity_score": _format_percent(sum(entity_scores) / len(entity_scores))
        if entity_scores
        else None,
        "relation_score": _format_percent(sum(relation_scores) / len(relation_scores))
        if relation_scores
        else None,
        "metadata_coverage": {
            key: _format_percent(value) if isinstance(value, float) else value
            for key, value in _metadata_coverage(edges).items()
        },
    }
    return results, summary


def _contains_all_terms(text: str, terms: list[Any]) -> list[dict[str, Any]]:
    text_canonical = canonical_text(text)
    checks: list[dict[str, Any]] = []
    for term in terms:
        term_canonical = canonical_text(term)
        passed = bool(term_canonical and term_canonical in text_canonical)
        checks.append({"expected": str(term), "passed": passed})
    return checks


def _reference_matches(expected: Any, references: list[dict[str, Any]]) -> bool:
    for ref in references:
        haystack = " ".join(
            str(ref.get(key) or "")
            for key in ("file_path", "title", "source_url", "download_url", "url")
        )
        if term_matches(expected, haystack):
            return True
    return False


async def score_query_cases(
    rag: Any,
    benchmark: dict[str, Any],
    generate_answers: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    results: list[dict[str, Any]] = []
    content_scores: list[float] = []
    reference_scores: list[float] = []
    successful_queries = 0

    for case in _as_list(benchmark.get("cases")):
        question = str(case.get("question") or "").strip()
        if not question:
            continue

        mode = str(case.get("mode") or benchmark.get("default_mode") or "mix")
        if mode not in {"local", "global", "hybrid", "naive", "mix", "bypass"}:
            mode = "mix"

        param = QueryParam(
            mode=mode,  # type: ignore[arg-type]
            stream=False,
            include_references=True,
            only_need_context=not generate_answers,
            response_type=str(case.get("response_type") or "Multiple Paragraphs"),
        )
        if case.get("top_k") is not None:
            param.top_k = int(case["top_k"])
        if case.get("chunk_top_k") is not None:
            param.chunk_top_k = int(case["chunk_top_k"])
        if isinstance(case.get("hl_keywords"), list):
            param.hl_keywords = [str(item) for item in case["hl_keywords"]]
        if isinstance(case.get("ll_keywords"), list):
            param.ll_keywords = [str(item) for item in case["ll_keywords"]]

        query_result = await rag.aquery_llm(question, param=param)
        status = query_result.get("status", "success")
        data = query_result.get("data") or {}
        llm_response = query_result.get("llm_response") or {}
        answer = str(llm_response.get("content") or "")
        references = _as_list(data.get("references"))
        chunks = _as_list(data.get("chunks"))
        context_text = "\n".join(str(chunk.get("content") or "") for chunk in chunks)
        scored_text = answer if generate_answers else context_text

        must_include_checks = _contains_all_terms(
            scored_text, _as_list(case.get("must_include"))
        )
        expected_documents = _as_list(case.get("expected_documents"))
        reference_checks = [
            {"expected": str(document), "passed": _reference_matches(document, references)}
            for document in expected_documents
        ]

        content_score = (
            sum(1 for check in must_include_checks if check["passed"])
            / len(must_include_checks)
            if must_include_checks
            else None
        )
        reference_score = (
            sum(1 for check in reference_checks if check["passed"])
            / len(reference_checks)
            if reference_checks
            else None
        )

        if status == "success":
            successful_queries += 1
        if content_score is not None:
            content_scores.append(content_score)
        if reference_score is not None:
            reference_scores.append(reference_score)

        results.append(
            {
                "id": str(case.get("id") or question),
                "question": question,
                "mode": mode,
                "status": status,
                "answer_preview": scored_text[:1200],
                "reference_count": len(references),
                "content_score": _format_percent(content_score)
                if content_score is not None
                else None,
                "reference_score": _format_percent(reference_score)
                if reference_score is not None
                else None,
                "must_include_checks": must_include_checks,
                "reference_checks": reference_checks,
            }
        )

    summary = {
        "queries": len(results),
        "successful_queries": successful_queries,
        "content_score": _format_percent(sum(content_scores) / len(content_scores))
        if content_scores
        else None,
        "reference_score": _format_percent(sum(reference_scores) / len(reference_scores))
        if reference_scores
        else None,
    }
    return results, summary


def _average_available(scores: list[tuple[float | None, float]]) -> float | None:
    weighted_sum = 0.0
    total_weight = 0.0
    for score, weight in scores:
        if score is None:
            continue
        weighted_sum += score * weight
        total_weight += weight
    if total_weight == 0:
        return None
    return weighted_sum / total_weight


def _failed_checks(
    graph_results: list[dict[str, Any]],
    query_results: list[dict[str, Any]],
) -> list[str]:
    failures: list[str] = []
    for case in graph_results:
        for check in case.get("entity_checks", []):
            if not check.get("passed"):
                failures.append(
                    f"{case['id']}: missing entity '{check.get('expected')}'"
                )
        for check in case.get("relation_checks", []):
            if not check.get("passed"):
                rel = check.get("expected") or {}
                failures.append(
                    f"{case['id']}: missing relation "
                    f"{rel.get('source')} -> {rel.get('relation_type')} -> {rel.get('target')}"
                )
    for case in query_results:
        if case.get("status") != "success":
            failures.append(f"{case['id']}: query status {case.get('status')}")
        for check in case.get("must_include_checks", []):
            if not check.get("passed"):
                failures.append(
                    f"{case['id']}: answer/context missing '{check.get('expected')}'"
                )
        for check in case.get("reference_checks", []):
            if not check.get("passed"):
                failures.append(
                    f"{case['id']}: missing source '{check.get('expected')}'"
                )
    return failures


def _result_output_path(rag: Any, benchmark_id: str) -> Path:
    root = Path(getattr(rag, "working_dir", "./rag_storage"))
    runs_dir = root / "evaluation_runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return runs_dir / f"{stamp}_{benchmark_id}.json"


async def run_live_benchmark(
    rag: Any,
    benchmark_id: str,
    mode: BenchmarkMode = "retrieval",
    save_result: bool = True,
) -> dict[str, Any]:
    benchmark = load_benchmark(benchmark_id, getattr(rag, "working_dir", None))
    run_queries = mode in {"retrieval", "full"}
    generate_answers = mode == "full"

    nodes = await rag.chunk_entity_relation_graph.get_all_nodes()
    edges = await rag.chunk_entity_relation_graph.get_all_edges()
    graph_results, graph_summary = score_graph_cases(benchmark, nodes, edges)

    query_results: list[dict[str, Any]] = []
    query_summary: dict[str, Any] = {
        "queries": 0,
        "successful_queries": 0,
        "content_score": None,
        "reference_score": None,
    }
    if run_queries:
        query_results, query_summary = await score_query_cases(
            rag, benchmark, generate_answers=generate_answers
        )

    metadata = graph_summary["metadata_coverage"]
    metadata_score = _average_available(
        [
            (_safe_float(metadata.get("directionality")) / 100, 1),
            (_safe_float(metadata.get("relation_type")) / 100, 1),
            (_safe_float(metadata.get("relation_importance")) / 100, 1),
            (_safe_float(metadata.get("chain_role")) / 100, 1),
            (_safe_float(metadata.get("specific_relation_type")) / 100, 1),
        ]
    )

    graph_score = _average_available(
        [
            (
                _safe_float(graph_summary.get("entity_score")) / 100
                if graph_summary.get("entity_score") is not None
                else None,
                1,
            ),
            (
                _safe_float(graph_summary.get("relation_score")) / 100
                if graph_summary.get("relation_score") is not None
                else None,
                2,
            ),
        ]
    )
    retrieval_score = _average_available(
        [
            (
                _safe_float(query_summary.get("content_score")) / 100
                if query_summary.get("content_score") is not None
                else None,
                1,
            ),
            (
                _safe_float(query_summary.get("reference_score")) / 100
                if query_summary.get("reference_score") is not None
                else None,
                1,
            ),
        ]
    )

    overall = _average_available(
        [
            (graph_score, 45),
            (metadata_score, 25),
            (retrieval_score, 30 if run_queries else 0),
        ]
    )

    result = {
        "benchmark": {
            "id": benchmark["id"],
            "name": benchmark.get("name"),
            "description": benchmark.get("description"),
            "path": benchmark.get("path"),
            "case_count": len(_as_list(benchmark.get("cases"))),
        },
        "run": {
            "mode": mode,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "query_generation_enabled": generate_answers,
            "query_checks_enabled": run_queries,
        },
        "scores": {
            "overall": _format_percent(overall) if overall is not None else None,
            "graph": _format_percent(graph_score) if graph_score is not None else None,
            "metadata": _format_percent(metadata_score)
            if metadata_score is not None
            else None,
            "retrieval": _format_percent(retrieval_score)
            if retrieval_score is not None
            else None,
        },
        "summary": {
            "nodes": len(nodes),
            "edges": len(edges),
            "graph": graph_summary,
            "query": query_summary,
        },
        "cases": {
            "graph": graph_results,
            "query": query_results,
        },
        "failed_checks": _failed_checks(graph_results, query_results),
    }

    if save_result:
        output_path = _result_output_path(rag, benchmark["id"])
        output_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        result["run"]["saved_to"] = str(output_path)

    return result
