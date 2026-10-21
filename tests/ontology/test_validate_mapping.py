"""Curated mapping stays tied to the pinned graph and its actual semantics."""

import copy
import json
import pytest
from rdflib import Graph

from ontology.validate_mapping import ROOT, audit, validate_mapping


@pytest.fixture(scope="module")
def inputs():
    mapping = json.loads((ROOT / "pem_mapping_v1.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    graph = Graph().parse(ROOT / "merged" / "merged.ttl", format="turtle")
    return mapping, graph, manifest, ROOT / "sources" / "bto"


def test_pinned_mapping_valid_and_audit_read_only(inputs):
    mapping, graph, manifest, source_root = inputs
    files = [ROOT / "pem_mapping_v1.json", ROOT / "merged" / "merged.ttl"]
    before = {path: path.stat().st_mtime_ns for path in files}
    assert validate_mapping(mapping, graph, manifest, source_root) == []
    assert audit() == []
    assert {path: path.stat().st_mtime_ns for path in files} == before


def test_examples_preserve_direction_and_uncertainty(inputs):
    mapping = inputs[0]
    relations = {row["label"]: row for row in mapping["relations"]}
    assert relations["causes"]["status"] == "mapped"
    assert relations["causes"]["inverse"]["swap_endpoints"] is True
    assert relations["produces"]["status"] == "conditional"
    assert relations["produces"]["domain_hint"] == "Process"
    assert relations["part_of"]["inverse"]["iri"] == relations["contains"]["iri"]
    assert relations["contains"]["inverse"]["iri"] == relations["part_of"]["iri"]
    assert relations["precedes"]["status"] == "ambiguous"
    assert relations["affects"]["status"] == "ambiguous"
    assert relations["uses"]["iri"] is None


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda m: m["source_versions"].update({"EMMO core": "9.9"}), "Source version drift"),
        (lambda m: m["relations"][0].update({"iri": "https://example.org/missing"}), "IRI is not a pinned"),
        (lambda m: m["relations"][0]["inverse"].update({"swap_endpoints": False}), "inverse must swap endpoints"),
        (lambda m: m["relations"][0]["inverse"].update({"iri": "https://example.org/wrong"}), "inverse not asserted"),
        (lambda m: m["relations"][4].update({"iri": "https://example.org/unsupported"}), "unresolved mapping must not have"),
        (lambda m: m["entity_types"][0].update({"source_file": "missing.ttl"}), "source file missing"),
        (lambda m: m["relations"][5].update({"condition": ""}), "conditional mapping lacks condition"),
    ],
)
def test_mapping_rejects_drift_and_invalid_semantics(inputs, mutate, expected):
    mapping = copy.deepcopy(inputs[0])
    mutate(mapping)
    assert any(expected in error for error in validate_mapping(mapping, *inputs[1:]))


def test_placeholder_cannot_become_domain_mapping(inputs):
    mapping = copy.deepcopy(inputs[0])
    method = next(row for row in mapping["entity_types"] if row["label"] == "Method")
    method.update(
        status="mapped",
        iri="https://w3id.org/battinfo/method",
        source_file="battinfo.ttl",
        source_ontology="BattINFO",
        preferred_label="Method",
    )
    errors = validate_mapping(mapping, *inputs[1:])
    assert any("record placeholder" in error for error in errors)
