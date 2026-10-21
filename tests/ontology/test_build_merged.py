"""Focused tests for isolated ontology merge output."""

import json

import pytest
from rdflib import Graph, OWL, RDF, RDFS, Literal, URIRef

from ontology import build_merged


def test_output_dir_writes_both_artifacts_without_touching_defaults(monkeypatch, tmp_path):
    first = Graph()
    first_class = URIRef("https://example.org/First")
    first.add((first_class, RDF.type, OWL.Class))
    first.add((first_class, RDFS.label, Literal("First")))

    second = Graph()
    second_class = URIRef("https://example.org/Second")
    second.add((second_class, RDF.type, OWL.Class))
    second.add((second_class, RDFS.subClassOf, first_class))

    baseline_root = tmp_path / "baseline"
    monkeypatch.setattr(build_merged, "MERGED_DIR", baseline_root / "merged")
    monkeypatch.setattr(build_merged, "__file__", str(baseline_root / "build_merged.py"))
    monkeypatch.setattr(
        build_merged,
        "load_all_graphs",
        lambda: ({"first.ttl": first, "second.ttl": second}, []),
    )

    output_dir = tmp_path / "isolated" / "result"
    build_merged.main(["--output-dir", str(output_dir)])

    merged_path = output_dir / "merged.ttl"
    report_path = output_dir / "merge_report.json"
    merged = Graph().parse(merged_path, format="turtle")
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert set(merged) == set(first) | set(second)
    assert report["files_parsed"] == ["first.ttl", "second.ttl"]
    assert report["files_failed"] == []
    assert report["triple_count"] == 4
    assert report["class_count"] == 2
    assert report["label_coverage"] == {
        "classes_total": 2,
        "with_rdfs_label": 1,
        "with_skos_preflabel": 0,
        "with_any_label": 1,
        "without_any_label": 1,
        "skos_altlabel_triples": 0,
    }
    assert not baseline_root.exists()


def test_output_dir_rejects_existing_file_before_loading(monkeypatch, tmp_path):
    output_file = tmp_path / "not-a-directory"
    output_file.write_text("sentinel", encoding="utf-8")
    monkeypatch.setattr(
        build_merged,
        "load_all_graphs",
        lambda: pytest.fail("sources must not load for an invalid output directory"),
    )

    with pytest.raises(SystemExit) as exc_info:
        build_merged.main(["--output-dir", str(output_file)])

    assert exc_info.value.code == 2
    assert output_file.read_text(encoding="utf-8") == "sentinel"


@pytest.mark.parametrize("target", ["root", "merged"])
def test_output_dir_rejects_default_artifact_directories(monkeypatch, tmp_path, target):
    baseline_root = tmp_path / "baseline"
    monkeypatch.setattr(build_merged, "MERGED_DIR", baseline_root / "merged")
    monkeypatch.setattr(build_merged, "__file__", str(baseline_root / "build_merged.py"))
    monkeypatch.setattr(
        build_merged,
        "load_all_graphs",
        lambda: pytest.fail("sources must not load for a baseline output directory"),
    )

    output_dir = baseline_root if target == "root" else baseline_root / "merged"
    with pytest.raises(SystemExit) as exc_info:
        build_merged.main(["--output-dir", str(output_dir)])

    assert exc_info.value.code == 2
    assert not baseline_root.exists()


def test_output_dir_does_not_overwrite_existing_artifact(monkeypatch, tmp_path):
    output_dir = tmp_path / "isolated"
    output_dir.mkdir()
    sentinel = output_dir / "merged.ttl"
    sentinel.write_text("sentinel", encoding="utf-8")
    monkeypatch.setattr(
        build_merged,
        "load_all_graphs",
        lambda: pytest.fail("sources must not load for an occupied output directory"),
    )

    with pytest.raises(SystemExit) as exc_info:
        build_merged.main(["--output-dir", str(output_dir)])

    assert exc_info.value.code == 2
    assert sentinel.read_text(encoding="utf-8") == "sentinel"
