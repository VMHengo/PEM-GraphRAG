"""Check reviewed forbidden edges in an isolated prompt-experiment artifact."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def _name(value: object) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _predicate(value: object) -> str:
    return "_".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _labels(value: object, aliases: list[str] | None = None) -> set[str]:
    if isinstance(value, dict):
        names = [value.get("name"), *(value.get("aliases") or [])]
    else:
        names = [value]
    return {_name(name) for name in [*names, *(aliases or [])] if _name(name)}


def _full_credit_types(relation: dict[str, Any], key: str) -> set[str]:
    accepted = relation.get(key) or {}
    if isinstance(accepted, dict):
        return {
            _predicate(name)
            for name, score in accepted.items()
            if score is True or isinstance(score, (int, float)) and score >= 1
        }
    if isinstance(accepted, list):
        return {_predicate(name) for name in accepted}
    return set()


def _matches_positive(relation: dict[str, Any], assertion: dict[str, str]) -> bool:
    if relation.get("directionality") and assertion.get("directionality") != relation["directionality"]:
        return False
    source = _name(assertion["source"])
    target = _name(assertion["target"])
    expected_sources = _labels(relation["source"], relation.get("source_aliases"))
    expected_targets = _labels(relation["target"], relation.get("target_aliases"))
    predicate = _predicate(assertion["relation_type"])
    direct_types = {
        _predicate(relation["relation_type"]),
        *_full_credit_types(relation, "accepted_relation_types"),
    }
    return (
        source in expected_sources
        and target in expected_targets
        and predicate in direct_types
    ) or (
        target in expected_sources
        and source in expected_targets
        and predicate in _full_credit_types(relation, "accepted_inverse_relation_types")
    )


def _assertions(document: dict[str, Any]) -> list[dict[str, str]]:
    assertions: list[dict[str, str]] = []
    for chunk in document.get("chunk_results", []):
        for edge in chunk.get("edges", []):
            for record in edge.get("records", []):
                assertions.append(
                    {
                        "source": str(record.get("semantic_src_id") or edge.get("source") or ""),
                        "relation_type": str(record.get("relation_type") or ""),
                        "target": str(record.get("semantic_tgt_id") or edge.get("target") or ""),
                        "source_id": str(record.get("source_id") or ""),
                        "directionality": str(record.get("directionality") or ""),
                    }
                )
    return assertions


def _entities(document: dict[str, Any]) -> set[str]:
    return {
        _name(node.get("entity_id"))
        for chunk in document.get("chunk_results", [])
        for node in chunk.get("nodes", [])
        if node.get("entity_id")
    }


def inspect_artifact(
    benchmark: dict[str, Any], artifact: dict[str, Any]
) -> dict[str, Any]:
    """Match only declared negative tuples within their own selected document."""

    source_files = {
        item["id"]: item["file"] for item in benchmark["document_scope"]
    }
    documents: dict[str, dict[str, Any]] = {}
    for document in artifact.get("documents", []):
        filename = Path(str(document.get("file_path") or "")).name
        if filename in documents:
            raise ValueError(f"Duplicate selected source filename: {filename}")
        documents[filename] = document

    cases = []
    violations = []
    for case in benchmark["cases"]:
        filename = source_files[case["source_document"]]
        if filename not in documents:
            raise ValueError(f"Missing selected source document: {filename}")
        assertions = _assertions(documents[filename])
        entities = _entities(documents[filename])
        expected_entities = case.get("expected_entities", [])
        expected_relations = case.get("expected_relations", [])
        missing_entities = [
            value for value in expected_entities if not entities.intersection(_labels(value))
        ]
        missing_relations = [
            relation
            for relation in expected_relations
            if not any(_matches_positive(relation, assertion) for assertion in assertions)
        ]
        cases.append(
            {
                "id": case["id"],
                "file": filename,
                "assertions": len(assertions),
                "entities_found": len(expected_entities) - len(missing_entities),
                "entities_expected": len(expected_entities),
                "relations_found": len(expected_relations) - len(missing_relations),
                "relations_expected": len(expected_relations),
                "missing_entities": missing_entities,
                "missing_relations": missing_relations,
                "forbidden_checks": len(case.get("forbidden_relations", [])),
            }
        )
        for forbidden in case.get("forbidden_relations", []):
            accepted_types = {
                _predicate(value)
                for value in [
                    forbidden["relation_type"],
                    *forbidden.get("relation_types", []),
                ]
            }
            for assertion in assertions:
                if (
                    _name(assertion["source"]) == _name(forbidden["source"])
                    and _name(assertion["target"]) == _name(forbidden["target"])
                    and _predicate(assertion["relation_type"]) in accepted_types
                ):
                    violations.append(
                        {
                            "case": case["id"],
                            "reason": forbidden["reason"],
                            "assertion": assertion,
                        }
                    )
    return {"cases": cases, "violations": violations}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=Path("evaluation/benchmarks/pem_extraction_stress_v1.json"),
    )
    args = parser.parse_args()
    benchmark = json.loads(args.benchmark.read_text(encoding="utf-8"))
    artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
    report = inspect_artifact(benchmark, artifact)
    for case in report["cases"]:
        print(
            f"{case['id']}: entities {case['entities_found']}/{case['entities_expected']}, "
            f"relations {case['relations_found']}/{case['relations_expected']}, "
            f"{case['assertions']} extracted assertions, "
            f"{case['forbidden_checks']} forbidden checks"
        )
        for entity in case["missing_entities"]:
            name = entity.get("name") if isinstance(entity, dict) else entity
            print(f"  missing entity: {name}")
        for relation in case["missing_relations"]:
            print(
                f"  missing relation: {relation['source']} --"
                f"{relation['relation_type']}--> {relation['target']}"
            )
    print(f"Forbidden-edge violations: {len(report['violations'])}")
    for item in report["violations"]:
        assertion = item["assertion"]
        print(
            f"  {item['case']}: {assertion['source']} --"
            f"{assertion['relation_type']}--> {assertion['target']} "
            f"[{assertion['source_id']}] ({item['reason']})"
        )
    if report["violations"] or any(
        case["missing_entities"] or case["missing_relations"]
        for case in report["cases"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
