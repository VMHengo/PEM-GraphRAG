"""Offline ontology-aware edge diagnostics for evaluation benchmarks.

This module is deliberately separate from the live benchmark scorer. It reads
the versioned PEM mapping as plain JSON and never changes retrieval or graph
scores. Ambiguous mapping candidates are not treated as equivalences.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


_DEFAULT_MAPPING = (
    Path(__file__).resolve().parents[2] / "ontology" / "pem_mapping_v1.json"
)
_MAPPED_STATUSES = frozenset({"mapped"})
_FULL_CREDIT = frozenset(
    {"raw_exact", "mapped_iri_exact", "alias_equivalent", "inverse_equivalent"}
)


def _normalize_label(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text)
    text = text.casefold().translate(
        {0xE4: "ae", 0xF6: "oe", 0xFC: "ue", 0xDF: "ss"}
    )
    return re.sub(r"[^\w]+", "_", text).strip("_")


def _edge_value(edge: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = edge.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return ""


def _edge_parts(edge: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        _edge_value(edge, "semantic_src_id", "source", "src_id"),
        _edge_value(edge, "relation_type", "predicate", "label"),
        _edge_value(edge, "semantic_tgt_id", "target", "tgt_id"),
        _edge_value(edge, "relation_iri", "predicate_iri", "ontology_iri", "iri"),
    )


def _load_mapping(mapping: Mapping[str, Any] | str | Path | None) -> dict[str, Any]:
    if mapping is None:
        loaded = json.loads(_DEFAULT_MAPPING.read_text(encoding="utf-8"))
    elif isinstance(mapping, Mapping):
        loaded = dict(mapping)
    else:
        loaded = json.loads(Path(mapping).read_text(encoding="utf-8"))
    if loaded.get("schema_version") != 1:
        raise ValueError("Unsupported ontology mapping schema; expected schema_version 1")
    if not isinstance(loaded.get("relations"), list):
        raise ValueError("Ontology mapping must contain a relations list")
    return loaded


class _MappingIndex:
    def __init__(self, mapping: Mapping[str, Any]):
        self.mapping_version = str(mapping.get("mapping_version") or "")
        self.rows: dict[str, Mapping[str, Any]] = {}
        self.labels: dict[str, set[str]] = {}
        self.inverse_labels: dict[str, set[str]] = {}
        self.iris: dict[str, set[str]] = {}
        self.inverse_iris: dict[str, set[str]] = {}

        for item in mapping["relations"]:
            if not isinstance(item, Mapping):
                continue
            label = str(item.get("label") or "")
            key = _normalize_label(label)
            if not key or item.get("status") not in _MAPPED_STATUSES or not item.get("iri"):
                continue
            self.rows[key] = item
            for candidate in (label, item.get("preferred_label"), *(item.get("aliases") or [])):
                self._add(self.labels, candidate, key)
            self._add(self.iris, item.get("iri"), key)
            inverse = item.get("inverse")
            if isinstance(inverse, Mapping) and inverse.get("swap_endpoints") is True:
                self._add(self.inverse_labels, inverse.get("label"), key)
                self._add(self.inverse_iris, inverse.get("iri"), key)

        self.hierarchy_pairs = self._hierarchy_pairs(mapping)

    @staticmethod
    def _add(index: dict[str, set[str]], value: object, key: str) -> None:
        normalized = _normalize_label(value)
        if normalized:
            index.setdefault(normalized, set()).add(key)

    @staticmethod
    def _unique(index: Mapping[str, set[str]], value: object) -> str | None:
        matches = index.get(_normalize_label(value), set())
        return next(iter(matches)) if len(matches) == 1 else None

    def direct_key(self, label: str, iri: str = "") -> str | None:
        return self._unique(self.iris, iri) if iri else self._unique(self.labels, label)

    def inverse_key(self, label: str, iri: str = "") -> str | None:
        return (
            self._unique(self.inverse_iris, iri)
            if iri
            else self._unique(self.inverse_labels, label)
        )

    def iri_key(self, iri: str) -> str | None:
        return self._unique(self.iris, iri) or self._unique(self.inverse_iris, iri)

    def is_mapped(self, label: str, iri: str = "") -> bool:
        return (
            self.direct_key(label, iri) is not None
            or self.inverse_key(label, iri) is not None
        )

    def _hierarchy_pairs(self, mapping: Mapping[str, Any]) -> set[frozenset[str]]:
        pairs: set[frozenset[str]] = set()
        top_level = []
        for field in ("hierarchy", "reviewed_hierarchy", "relation_hierarchy"):
            value = mapping.get(field)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                top_level.extend(value)
        for item in top_level:
            if not isinstance(item, Mapping) or item.get("reviewed") is not True:
                continue
            left = item.get("narrower") or item.get("child") or item.get("source")
            right = item.get("broader") or item.get("parent") or item.get("target")
            self._add_hierarchy_pair(pairs, left, right)

        for row_key, row in self.rows.items():
            entries = row.get("hierarchy") or row.get("reviewed_hierarchy") or []
            if isinstance(entries, Mapping):
                entries = [entries]
            if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
                continue
            for item in entries:
                if not isinstance(item, Mapping) or item.get("reviewed") is not True:
                    continue
                other = item.get("relation") or item.get("label") or item.get("iri")
                other_key = self.direct_key(str(other or ""), str(item.get("iri") or ""))
                if other_key and other_key != row_key:
                    pairs.add(frozenset((row_key, other_key)))
        return pairs

    def _add_hierarchy_pair(
        self, pairs: set[frozenset[str]], left: object, right: object
    ) -> None:
        left_key = self.direct_key(str(left or ""))
        right_key = self.direct_key(str(right or ""))
        if left_key and right_key and left_key != right_key:
            pairs.add(frozenset((left_key, right_key)))


def _pair_diagnostic(
    expected: Mapping[str, Any], given: Mapping[str, Any], index: _MappingIndex
) -> tuple[int, str, float] | None:
    exp_source, exp_label, exp_target, exp_iri = _edge_parts(expected)
    got_source, got_label, got_target, got_iri = _edge_parts(given)
    same_endpoints = exp_source == got_source and exp_target == got_target

    if same_endpoints and exp_label == got_label and exp_label:
        return (5, "raw_exact", 1.0)
    if same_endpoints and exp_iri and exp_iri == got_iri:
        if index.iri_key(exp_iri):
            return (4, "mapped_iri_exact", 1.0)

    exp_direct = index.direct_key(exp_label, exp_iri)
    got_direct = index.direct_key(got_label, got_iri)
    if same_endpoints and exp_direct and exp_direct == got_direct:
        return (3, "alias_equivalent", 1.0)

    swapped_endpoints = exp_source == got_target and exp_target == got_source
    exp_inverse = index.inverse_key(exp_label, exp_iri)
    got_inverse = index.inverse_key(got_label, got_iri)
    inverse_equivalent = (
        exp_direct and got_inverse == exp_direct
    ) or (got_direct and exp_inverse == got_direct)
    if swapped_endpoints and inverse_equivalent:
        return (2, "inverse_equivalent", 1.0)

    if (
        same_endpoints
        and exp_direct
        and got_direct
        and frozenset((exp_direct, got_direct)) in index.hierarchy_pairs
    ):
        return (1, "hierarchy_partial", 0.5)
    return None


def _rate(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


def score_ontology_edges(
    expected_edges: list[dict[str, Any]],
    given_edges: list[dict[str, Any]],
    mapping: Mapping[str, Any] | str | Path | None = None,
) -> dict[str, Any]:
    """Score expected and given edges without changing baseline benchmark scores.

    Edges use ``source``, ``relation_type`` and ``target`` keys. The legacy
    endpoint key variants accepted by the graph scorer are also supported.
    Explicit relation IRIs may be supplied as ``relation_iri``,
    ``predicate_iri``, ``ontology_iri`` or ``iri``.
    """

    if not isinstance(expected_edges, list) or not isinstance(given_edges, list):
        raise TypeError("expected_edges and given_edges must be lists of dictionaries")
    if not all(isinstance(edge, dict) for edge in [*expected_edges, *given_edges]):
        raise TypeError("Every expected and given edge must be a dictionary")

    loaded_mapping = _load_mapping(mapping)
    index = _MappingIndex(loaded_mapping)
    candidates: list[tuple[int, int, int, str, float]] = []
    for expected_index, expected in enumerate(expected_edges):
        for given_index, given in enumerate(given_edges):
            match = _pair_diagnostic(expected, given, index)
            if match:
                rank, match_type, score = match
                candidates.append((rank, expected_index, given_index, match_type, score))

    matched_expected: dict[int, tuple[int, str, float]] = {}
    matched_given: set[int] = set()
    for _, expected_index, given_index, match_type, score in sorted(
        candidates, key=lambda item: (-item[0], item[1], item[2])
    ):
        if expected_index in matched_expected or given_index in matched_given:
            continue
        matched_expected[expected_index] = (given_index, match_type, score)
        matched_given.add(given_index)

    cases: list[dict[str, Any]] = []
    match_counts = {
        "raw_exact": 0,
        "mapped_iri_exact": 0,
        "alias_equivalent": 0,
        "inverse_equivalent": 0,
        "hierarchy_partial": 0,
    }
    for position, expected in enumerate(expected_edges):
        match = matched_expected.get(position)
        match_type = match[1] if match else "missing"
        score = match[2] if match else 0.0
        if match:
            match_counts[match_type] += 1
        case_id = expected.get("case_id", expected.get("id", position))
        cases.append(
            {
                "case_id": case_id,
                "expected": expected,
                "given": given_edges[match[0]] if match else None,
                "match_type": match_type,
                "score": score,
                "full_credit": match_type in _FULL_CREDIT,
                "diagnostics": {
                    name: match_type == name for name in match_counts
                },
                "expected_mapped": index.is_mapped(
                    _edge_parts(expected)[1], _edge_parts(expected)[3]
                ),
            }
        )

    expected_unmapped = sum(
        not index.is_mapped(_edge_parts(edge)[1], _edge_parts(edge)[3])
        for edge in expected_edges
    )
    given_unmapped = sum(
        not index.is_mapped(_edge_parts(edge)[1], _edge_parts(edge)[3])
        for edge in given_edges
    )
    false_positives = [
        edge for position, edge in enumerate(given_edges) if position not in matched_given
    ]
    score_sum = sum(case["score"] for case in cases)
    return {
        "mapping_version": index.mapping_version,
        "cases": cases,
        "false_positives": false_positives,
        "summary": {
            "expected_count": len(expected_edges),
            "given_count": len(given_edges),
            "matched_count": len(matched_expected),
            "mean_diagnostic_score": (
                round(score_sum / len(cases), 4) if cases else 0.0
            ),
            **{f"{name}_count": count for name, count in match_counts.items()},
            **{
                f"{name}_rate": _rate(count, len(expected_edges))
                for name, count in match_counts.items()
            },
            "expected_unmapped_count": expected_unmapped,
            "expected_unmapped_rate": _rate(expected_unmapped, len(expected_edges)),
            "given_unmapped_count": given_unmapped,
            "given_unmapped_rate": _rate(given_unmapped, len(given_edges)),
            "false_positive_count": len(false_positives),
            "false_positive_rate": _rate(len(false_positives), len(given_edges)),
        },
    }

