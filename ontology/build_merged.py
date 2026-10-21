"""Build the union graph for Ticket 06 (ontology merge).

Loads the vendored EMMO/CHAMEO/domain-battery/domain-electrochemistry/
chemical-substance/BTO closure (from ontology/sources/bto/) plus the BattINFO
stub file, merges them into one rdflib.Graph, detects version and IRI
conflicts, and writes merged.ttl plus merge_report.json. By default these are
the existing ontology/merged/merged.ttl and ontology/merge_report.json paths;
``--output-dir`` writes both files to an isolated directory instead. The
provenance manifest is maintained separately and is never updated.

BATTINFO_RECORDS_FILE is a separate, explicitly non-canonical source: BattINFO's
own IDENTIFIER_POLICY.md section 14 documents its `battinfo:` (slash-namespace)
terms as placeholders standing in for concepts not yet added upstream to
domain-battery/domain-electrochemistry, meant to shrink over time as those
upstream releases add the real terms. They are software-record-layer plumbing,
not domain ontology content in the sense the rest of this graph is. Kept in a
separate source file (not silently folded into battinfo.ttl) so downstream
consumers (Ticket 07) can filter on the https://w3id.org/battinfo/ namespace if
they want to exclude them from the candidate entity-type set.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from rdflib import Graph, OWL, RDF, RDFS
from rdflib.namespace import SKOS

SOURCES_DIR = Path(__file__).parent / "sources"
BTO_DIR = SOURCES_DIR / "bto"
MERGED_DIR = Path(__file__).parent / "merged"
MANIFEST_PATH = Path(__file__).parent / "manifest.json"

BTO_FILES = sorted(BTO_DIR.glob("*.ttl"))
BATTINFO_FILE = SOURCES_DIR / "battinfo.ttl"
BATTINFO_RECORDS_FILE = SOURCES_DIR / "battinfo-records-placeholder-vocab.ttl"


def output_directory(value: str) -> Path:
    """Return a usable output directory path for argparse."""
    path = Path(value).expanduser()
    if path.exists() and not path.is_dir():
        raise argparse.ArgumentTypeError(f"not a directory: {path}")
    if path.resolve() in {MERGED_DIR.resolve(), Path(__file__).parent.resolve()}:
        raise argparse.ArgumentTypeError("--output-dir must not be a default artifact directory")
    if any((path / name).exists() for name in ("merged.ttl", "merge_report.json")):
        raise argparse.ArgumentTypeError("--output-dir already contains merge artifacts")
    return path


def load_all_graphs():
    """Parse each source file into its own graph, keyed by filename.

    Loading separately (instead of one shared Graph.parse per file) lets us
    detect which file a triple came from, needed for the IRI-conflict check.
    """
    per_file = {}
    failed = []
    for path in list(BTO_FILES) + [BATTINFO_FILE, BATTINFO_RECORDS_FILE]:
        g = Graph()
        try:
            g.parse(str(path), format="turtle")
            per_file[path.name] = g
        except Exception as exc:  # noqa: BLE001 - documented, not swallowed
            failed.append((path.name, str(exc)))
    return per_file, failed


def detect_class_conflicts(per_file):
    """Find IRIs declared as owl:Class in more than one file with a differing
    label or a different set of rdfs:subClassOf targets.

    Labels are checked under BOTH rdfs:label and skos:prefLabel. EMMO carries
    its primary labels in skos:prefLabel (4460 of 4611 classes) and only a
    subset in rdfs:label (2684) - an rdfs:label-only check silently misses most
    of the label surface and reports a false "no conflicts" result. Ticket 06's
    first pass had exactly that defect; see NOTES.md 2026-09-06 correction.
    """
    label_by_iri = {
        "rdfs:label": defaultdict(dict),
        "skos:prefLabel": defaultdict(dict),
    }
    label_predicates = {"rdfs:label": RDFS.label, "skos:prefLabel": SKOS.prefLabel}
    superclasses_by_iri = defaultdict(dict)  # iri -> {file: {superclass iris}}

    for fname, g in per_file.items():
        for cls in g.subjects(RDF.type, OWL.Class):
            for key, pred in label_predicates.items():
                labels = {str(o) for o in g.objects(cls, pred)}
                if labels:
                    label_by_iri[key][str(cls)][fname] = labels
            # skip blank-node restrictions, keep only named superclasses
            supers = {
                str(o) for o in g.objects(cls, RDFS.subClassOf) if o.__class__.__name__ == "URIRef"
            }
            if supers:
                superclasses_by_iri[str(cls)][fname] = supers

    label_conflicts = {}
    for key, by_iri in label_by_iri.items():
        found = []
        for iri, by_file in by_iri.items():
            distinct_label_sets = {frozenset(v) for v in by_file.values()}
            if len(distinct_label_sets) > 1:
                found.append({"iri": iri, "labels_by_file": {k: sorted(v) for k, v in by_file.items()}})
        label_conflicts[key] = found

    subclass_conflicts = []
    for iri, by_file in superclasses_by_iri.items():
        distinct_super_sets = {frozenset(v) for v in by_file.values()}
        if len(distinct_super_sets) > 1:
            subclass_conflicts.append({"iri": iri, "superclasses_by_file": {k: sorted(v) for k, v in by_file.items()}})

    return label_conflicts, subclass_conflicts


def label_coverage(union):
    """How much of the class surface actually carries a human-readable label.

    Ticket 07 derives the candidate entity-type set from these classes, so an
    unlabelled class is unusable there without extra work - the count belongs
    in the manifest rather than being discovered later.
    """
    classes = set(union.subjects(RDF.type, OWL.Class))
    with_rdfs = {c for c in classes if (c, RDFS.label, None) in union}
    with_skos = {c for c in classes if (c, SKOS.prefLabel, None) in union}
    return {
        "classes_total": len(classes),
        "with_rdfs_label": len(with_rdfs),
        "with_skos_preflabel": len(with_skos),
        "with_any_label": len(with_rdfs | with_skos),
        "without_any_label": len(classes - with_rdfs - with_skos),
        "skos_altlabel_triples": len(list(union.triples((None, SKOS.altLabel, None)))),
    }


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=output_directory,
        help="Write merged.ttl and merge_report.json to this directory",
    )
    args = parser.parse_args(argv)

    if args.output_dir is None:
        merged_path = MERGED_DIR / "merged.ttl"
        report_path = Path(__file__).parent / "merge_report.json"
    else:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        merged_path = args.output_dir / "merged.ttl"
        report_path = args.output_dir / "merge_report.json"

    per_file, failed = load_all_graphs()

    print(f"Parsed {len(per_file)} files, {len(failed)} failed.")
    for fname, err in failed:
        print(f"  FAILED: {fname}: {err}", file=sys.stderr)

    label_conflicts, subclass_conflicts = detect_class_conflicts(per_file)

    union = Graph()
    for fname, g in per_file.items():
        for triple in g:
            union.add(triple)

    merged_path.parent.mkdir(parents=True, exist_ok=True)
    union.serialize(destination=str(merged_path), format="turtle")

    n_classes = len(set(union.subjects(RDF.type, OWL.Class)))
    n_object_properties = len(set(union.subjects(RDF.type, OWL.ObjectProperty)))
    n_data_properties = len(set(union.subjects(RDF.type, OWL.DatatypeProperty)))
    n_annotation_properties = len(set(union.subjects(RDF.type, OWL.AnnotationProperty)))
    n_individuals = len(set(union.subjects(RDF.type, OWL.NamedIndividual)))
    # rdf:Property (untyped as Object/Data/Annotation) - this is how
    # battinfo-records-placeholder-vocab.ttl types its 53 placeholder
    # properties, so it doesn't show up in any of the three OWL buckets above.
    n_generic_properties = len(set(union.subjects(RDF.type, RDF.Property)))
    n_triples = len(union)

    report = {
        "files_parsed": sorted(per_file.keys()),
        "files_failed": failed,
        "triple_count": n_triples,
        "class_count": n_classes,
        "object_property_count": n_object_properties,
        "data_property_count": n_data_properties,
        "annotation_property_count": n_annotation_properties,
        "generic_rdf_property_count": n_generic_properties,
        "individual_count": n_individuals,
        "label_coverage": label_coverage(union),
        "label_conflicts": label_conflicts,
        "subclass_conflicts": subclass_conflicts,
    }

    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(
        {k: v for k, v in report.items() if k not in ("files_parsed",)},
        indent=2, ensure_ascii=False,
    )[:3000])


if __name__ == "__main__":
    main()
