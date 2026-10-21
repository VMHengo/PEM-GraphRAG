"""Regression tests for the read-only ontology source audit."""

import json
import hashlib
from pathlib import Path

from rdflib import Graph, URIRef

from ontology.build_merged import detect_class_conflicts, label_coverage
from ontology.validate_sources import ROOT_SOURCES, _term_counts, audit


def _write_fixture(root: Path) -> Path:
    bto = root / "sources" / "bto"
    bto.mkdir(parents=True)
    (root / "merged").mkdir()
    sources = {}
    licenses = {}
    for source_name, filename in ROOT_SOURCES.items():
        path = root / "sources" / filename if source_name == "BattINFO" else bto / filename
        license_id = "Apache-2.0" if source_name == "BattINFO" else "CC BY 4.0"
        license_url = (
            "https://www.apache.org/licenses/LICENSE-2.0"
            if source_name == "BattINFO"
            else "https://creativecommons.org/licenses/by/4.0/legalcode"
        )
        path.write_text(
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "@prefix dcterms: <http://purl.org/dc/terms/> .\n"
            f"<https://example.org/{path.stem}> a owl:Ontology ; "
            f'owl:versionInfo "1.0" ; dcterms:license <{license_url}> .\n'
            f"<https://example.org/{path.stem}/class> a owl:Class .\n",
            encoding="utf-8",
        )
        sources[source_name] = {"used_version": "1.0"}
        licenses[source_name] = license_id
    placeholder = root / "sources" / "battinfo-records-placeholder-vocab.ttl"
    placeholder.write_text("<https://example.org/record> <https://example.org/key> <https://example.org/value> .\n")

    per_file = {}
    union = Graph()
    for path in sorted(bto.glob("*.ttl")) + [root / "sources" / "battinfo.ttl", placeholder]:
        graph = Graph().parse(path, format="turtle")
        per_file[path.name] = graph
        union += graph
    labels, subclasses = detect_class_conflicts(per_file)
    counts = _term_counts(union)
    report = {
        "files_parsed": sorted(per_file),
        "files_failed": [],
        **{key: counts[source_key] for source_key, key in {
            "triples": "triple_count",
            "classes": "class_count",
            "object_properties": "object_property_count",
            "data_properties": "data_property_count",
            "annotation_properties": "annotation_property_count",
            "generic_rdf_properties": "generic_rdf_property_count",
            "named_individuals": "individual_count",
        }.items()},
        "label_coverage": label_coverage(union),
        "label_conflicts": labels,
        "subclass_conflicts": subclasses,
    }
    manifest = {
        "sources": sources,
        "counts": {**counts, "files_merged": len(per_file)},
        "label_coverage": report["label_coverage"],
        "licenses": {"source_license_declarations": licenses},
        "source_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(bto.glob("*.ttl")) + [root / "sources" / "battinfo.ttl", placeholder]
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "merge_report.json").write_text(json.dumps(report), encoding="utf-8")
    union.serialize(destination=root / "merged" / "merged.ttl", format="turtle")
    return root


def test_audit_matches_sources_without_changing_artifacts(tmp_path):
    root = _write_fixture(tmp_path / "ontology")
    artifacts = [root / "manifest.json", root / "merge_report.json", root / "merged" / "merged.ttl"]
    before = {path: path.read_bytes() for path in artifacts}

    result = audit(root)

    assert result["ok"], result["errors"]
    assert result["merged_structure_match"] is True
    assert result["merged_isomorphic"] is None
    assert result["source_files"]["listed"] == 8
    assert {path: path.read_bytes() for path in artifacts} == before


def test_audit_reports_missing_source(tmp_path):
    root = _write_fixture(tmp_path / "ontology")
    (root / "sources" / "bto" / "battery.ttl").unlink()

    result = audit(root)

    assert not result["ok"]
    assert result["source_files"]["missing"] == ["battery.ttl"]
    assert any("Missing listed source files" in error for error in result["errors"])


def test_audit_reports_changed_source_hash_even_if_rdf_is_unchanged(tmp_path):
    root = _write_fixture(tmp_path / "ontology")
    source = root / "sources" / "bto" / "battery.ttl"
    source.write_text(source.read_text(encoding="utf-8") + "# changed comment\n", encoding="utf-8")

    result = audit(root)

    assert not result["ok"]
    assert any("SHA-256 mismatch for battery.ttl" in error for error in result["errors"])
    assert result["merged_structure_match"] is True


def test_audit_reports_license_and_count_mismatches(tmp_path):
    root = _write_fixture(tmp_path / "ontology")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["licenses"]["source_license_declarations"]["BattINFO"] = "CC BY 4.0"
    manifest["counts"]["classes"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = audit(root)

    assert not result["ok"]
    assert any("License mismatch for BattINFO" in error for error in result["errors"])
    assert any("Manifest classes" in error for error in result["errors"])


def test_audit_detects_historical_blanket_license_and_version_mismatch(tmp_path):
    root = _write_fixture(tmp_path / "ontology")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["licenses"] = {"all_sources": "CC BY 4.0"}
    manifest["sources"]["BattINFO"]["used_version"] = "2.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = audit(root)

    assert not result["ok"]
    assert any("License mismatch for BattINFO" in error for error in result["errors"])
    assert any("Version mismatch for BattINFO" in error for error in result["errors"])


def test_audit_reports_drift_in_stored_merge(tmp_path):
    root = _write_fixture(tmp_path / "ontology")
    merged_path = root / "merged" / "merged.ttl"
    merged = Graph().parse(merged_path, format="turtle")
    merged.add((
        URIRef("https://example.org/extra"),
        URIRef("https://example.org/predicate"),
        URIRef("https://example.org/value"),
    ))
    merged.serialize(destination=merged_path, format="turtle")

    result = audit(root)

    assert not result["ok"]
    assert result["merged_structure_match"] is False
    assert result["grounded_diff"]["artifact_only_count"] == 1
    assert any("structure differs" in error for error in result["errors"])
