"""Read-only audit of the local ontology sources and recorded merge artifacts."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

from rdflib import BNode, Graph, OWL, RDF
from rdflib.compare import isomorphic
from rdflib.namespace import DCTERMS

from ontology.build_merged import detect_class_conflicts, label_coverage


ROOT_SOURCES = {
    "battery-testing-ontology (BTO)": "bto.ttl",
    "domain-battery": "battery.ttl",
    "domain-electrochemistry": "electrochemistry.ttl",
    "chameo": "chameo.ttl",
    "chemical-substance": "chemical-substance.ttl",
    "EMMO core": "1.0.2.ttl",
    "BattINFO": "battinfo.ttl",
}
REPORT_COUNT_KEYS = {
    "triples": "triple_count",
    "classes": "class_count",
    "object_properties": "object_property_count",
    "data_properties": "data_property_count",
    "annotation_properties": "annotation_property_count",
    "generic_rdf_properties": "generic_rdf_property_count",
    "named_individuals": "individual_count",
}


def _license_id(value: str) -> str:
    text = value.lower()
    if "creativecommons.org/licenses/by/4.0" in text or "cc by 4.0" in text:
        return "CC BY 4.0"
    if "apache.org/licenses/license-2.0" in text or "apache-2.0" in text:
        return "Apache-2.0"
    return value


def _ontology_metadata(graph: Graph) -> dict[str, list[str]]:
    subjects = set(graph.subjects(RDF.type, OWL.Ontology))
    return {
        "version_info": sorted({str(v) for s in subjects for v in graph.objects(s, OWL.versionInfo)}),
        "version_iri": sorted({str(v) for s in subjects for v in graph.objects(s, OWL.versionIRI)}),
        "licenses": sorted({_license_id(str(v)) for s in subjects for v in graph.objects(s, DCTERMS.license)}),
    }


def _expected_version(source: dict[str, Any]) -> str | None:
    if source.get("used_version"):
        return str(source["used_version"])
    if source.get("owl_versionInfo"):
        return str(source["owl_versionInfo"])
    if source.get("resolved_version_iri"):
        return str(source["resolved_version_iri"]).rstrip("/").split("/")[-2]
    return None


def _term_counts(graph: Graph) -> dict[str, int]:
    return {
        "triples": len(graph),
        "classes": len(set(graph.subjects(RDF.type, OWL.Class))),
        "object_properties": len(set(graph.subjects(RDF.type, OWL.ObjectProperty))),
        "data_properties": len(set(graph.subjects(RDF.type, OWL.DatatypeProperty))),
        "annotation_properties": len(set(graph.subjects(RDF.type, OWL.AnnotationProperty))),
        "generic_rdf_properties": len(set(graph.subjects(RDF.type, RDF.Property))),
        "named_individuals": len(set(graph.subjects(RDF.type, OWL.NamedIndividual))),
    }


def _conflicts_by_iri(values: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["iri"]: {key: value for key, value in item.items() if key != "iri"} for item in values}


def _structural_signature(graph: Graph) -> tuple[Counter, Counter]:
    """Compare grounded triples and local blank-node structure independent of IDs."""

    grounded = Counter()
    neighborhoods: dict[BNode, list[tuple[str, str, str, str]]] = defaultdict(list)
    for subject, predicate, obj in graph:
        if not isinstance(subject, BNode) and not isinstance(obj, BNode):
            grounded[(subject, predicate, obj)] += 1
            continue
        shape = (
            "_" if isinstance(subject, BNode) else subject.n3(),
            predicate.n3(),
            "_" if isinstance(obj, BNode) else obj.n3(),
        )
        if isinstance(subject, BNode):
            neighborhoods[subject].append(("subject", *shape))
        if isinstance(obj, BNode):
            neighborhoods[obj].append(("object", *shape))
    return grounded, Counter(tuple(sorted(parts)) for parts in neighborhoods.values())


def _grounded_triples(graph: Graph) -> set[tuple]:
    return {
        (subject, predicate, obj)
        for subject, predicate, obj in graph
        if not isinstance(subject, BNode) and not isinstance(obj, BNode)
    }


def audit(
    root: Path,
    *,
    deep: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Inspect source closure and artifacts without changing any files."""

    result: dict[str, Any] = {
        "ok": False,
        "errors": [],
        "warnings": [],
        "source_files": {},
        "root_metadata": {},
        "counts": {},
        "merged_structure_match": None,
        "merged_isomorphic": None,
        "grounded_diff": None,
    }
    root = Path(root)
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        recorded = json.loads((root / "merge_report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        result["errors"].append(f"Cannot read manifest or merge report: {exc}")
        return result

    bto_dir = root / "sources" / "bto"
    paths = list(bto_dir.glob("*.ttl")) + [
        root / "sources" / "battinfo.ttl",
        root / "sources" / "battinfo-records-placeholder-vocab.ttl",
    ]
    actual = {path.name: path for path in paths if path.is_file()}
    if len(actual) != len([path for path in paths if path.is_file()]):
        result["errors"].append("Duplicate source filenames; merge_report uses basenames as identifiers")
    listed = recorded.get("files_parsed", [])
    expected = set(listed)
    if len(expected) != len(listed):
        result["errors"].append("Duplicate filenames in merge_report.files_parsed")
    missing = sorted(expected - actual.keys())
    extra = sorted(actual.keys() - expected)
    if missing:
        result["errors"].append(f"Missing listed source files: {', '.join(missing)}")
    if extra:
        result["errors"].append(f"Unlisted source files: {', '.join(extra)}")
    if recorded.get("files_failed"):
        result["errors"].append("Recorded merge contains failed source files")
    manifest_count = manifest.get("counts", {}).get("files_merged")
    if manifest_count != len(expected):
        result["errors"].append(f"Manifest files_merged={manifest_count}, report lists {len(expected)}")
    result["source_files"] = {
        "listed": len(expected),
        "present": len(actual),
        "missing": missing,
        "extra": extra,
    }

    graphs: dict[str, Graph] = {}
    union = Graph()
    for name in sorted(expected & actual.keys()):
        graph = Graph()
        try:
            graph.parse(actual[name], format="turtle")
        except Exception as exc:  # RDF parser errors vary by rdflib release.
            result["errors"].append(f"Cannot parse {name}: {exc}")
            continue
        graphs[name] = graph
        union += graph
    if progress:
        progress(f"Parsed {len(graphs)} source files")

    license_data = manifest.get("licenses", {})
    expected_licenses = license_data.get("source_license_declarations")
    historical_license = _license_id(str(license_data.get("all_sources", "")))
    for source_name, filename in ROOT_SOURCES.items():
        graph = graphs.get(filename)
        if graph is None:
            result["errors"].append(f"Missing root ontology file: {filename}")
            continue
        metadata = _ontology_metadata(graph)
        result["root_metadata"][source_name] = metadata
        source = manifest.get("sources", {}).get(source_name, {})
        expected_version = _expected_version(source)
        if not expected_version:
            result["warnings"].append(f"No pinned version for {source_name} in manifest")
        elif expected_version not in metadata["version_info"] and not any(
            f"/{expected_version}/" in iri for iri in metadata["version_iri"]
        ):
            result["errors"].append(
                f"Version mismatch for {source_name}: expected {expected_version}, "
                f"found {metadata['version_info']} / {metadata['version_iri']}"
            )
        expected_license = (
            expected_licenses.get(source_name)
            if isinstance(expected_licenses, dict)
            else historical_license
        )
        if not expected_license:
            result["errors"].append(f"No source license declaration for {source_name} in manifest")
        elif expected_license not in metadata["licenses"]:
            result["errors"].append(
                f"License mismatch for {source_name}: expected {expected_license}, "
                f"found {metadata['licenses']}"
            )

    if len(graphs) != len(expected):
        result["warnings"].append("Skipping merge comparison because not all listed sources parsed")
    else:
        counts = _term_counts(union)
        result["counts"] = counts
        if progress:
            progress("Counted merged source graph")
        for key, report_key in REPORT_COUNT_KEYS.items():
            if counts[key] != recorded.get(report_key):
                result["errors"].append(f"Merge report {report_key}={recorded.get(report_key)}, actual={counts[key]}")
            if counts[key] != manifest.get("counts", {}).get(key):
                result["errors"].append(
                    f"Manifest {key}={manifest.get('counts', {}).get(key)}, actual={counts[key]}"
                )
        coverage = label_coverage(union)
        if coverage != recorded.get("label_coverage"):
            result["errors"].append("Merge report label_coverage differs from source graph")
        for key, value in coverage.items():
            if key in manifest.get("label_coverage", {}) and value != manifest["label_coverage"][key]:
                result["errors"].append(f"Manifest label_coverage.{key} differs: actual={value}")

        labels, subclasses = detect_class_conflicts(graphs)
        if progress:
            progress("Compared class conflicts")
        for label_kind, rows in labels.items():
            if _conflicts_by_iri(rows) != _conflicts_by_iri(recorded.get("label_conflicts", {}).get(label_kind, [])):
                result["errors"].append(f"Merge report {label_kind} conflicts differ from sources")
        if _conflicts_by_iri(subclasses) != _conflicts_by_iri(recorded.get("subclass_conflicts", [])):
            result["errors"].append("Merge report subclass conflicts differ from sources")

        merged_path = root / "merged" / "merged.ttl"
        try:
            merged = Graph().parse(merged_path, format="turtle")
            if progress:
                progress("Parsed stored merged graph")
            result["merged_structure_match"] = (
                len(union) == len(merged)
                and _structural_signature(union) == _structural_signature(merged)
            )
            source_grounded = _grounded_triples(union)
            artifact_grounded = _grounded_triples(merged)
            result["grounded_diff"] = {
                "source_only_count": len(source_grounded - artifact_grounded),
                "artifact_only_count": len(artifact_grounded - source_grounded),
                "source_only_examples": sorted(
                    (tuple(map(str, triple)) for triple in source_grounded - artifact_grounded)
                )[:5],
                "artifact_only_examples": sorted(
                    (tuple(map(str, triple)) for triple in artifact_grounded - source_grounded)
                )[:5],
            }
            if progress:
                progress("Compared grounded triples and blank-node neighborhoods")
            if not result["merged_structure_match"]:
                result["errors"].append("Stored merged.ttl structure differs from current source closure")
            if deep:
                result["merged_isomorphic"] = isomorphic(union, merged)
                if progress:
                    progress("Compared exact RDF graph isomorphism")
                if not result["merged_isomorphic"]:
                    result["errors"].append("Stored merged.ttl is not RDF-isomorphic to current source closure")
        except Exception as exc:  # RDF parser errors vary by rdflib release.
            result["errors"].append(f"Cannot read merged.ttl: {exc}")

    for missing_note in ("NOTES.md", "map.md"):
        if not (root / missing_note).exists():
            result["warnings"].append(f"Historical reference not present: ontology/{missing_note}")
    original_bto_count = manifest.get("sources", {}).get("battery-testing-ontology (BTO)", {}).get("files_fetched")
    current_bto_count = len(list(bto_dir.glob("*.ttl")))
    if original_bto_count != current_bto_count:
        result["warnings"].append(
            f"BTO files_fetched={original_bto_count} is historical; current mixed closure has "
            f"{current_bto_count} BTO-directory files"
        )
    result["ok"] = not result["errors"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--json", action="store_true", help="Print the complete audit as JSON")
    parser.add_argument("--deep", action="store_true", help="Also check exact RDF isomorphism (slow)")
    parser.add_argument("--verbose", action="store_true", help="Show audit progress on stderr")
    args = parser.parse_args()
    started = time.monotonic()

    def log_progress(message: str) -> None:
        print(f"[{time.monotonic() - started:.1f}s] {message}", file=sys.stderr)

    progress = log_progress if args.verbose else None
    report = audit(args.root, deep=args.deep, progress=progress)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Ontology audit: {'PASS' if report['ok'] else 'FAIL'}")
        print(f"Sources: {report['source_files']}; counts: {report['counts']}")
        print(f"Stored merge structure matches sources: {report['merged_structure_match']}")
        if report["grounded_diff"]:
            diff = report["grounded_diff"]
            print(
                "Grounded triple differences: "
                f"source-only={diff['source_only_count']}, "
                f"artifact-only={diff['artifact_only_count']} (examples: --json)"
            )
        if args.deep:
            print(f"Exact RDF isomorphism: {report['merged_isomorphic']}")
        for key in ("errors", "warnings"):
            for message in report[key]:
                print(f"{key[:-1].upper()}: {message}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
