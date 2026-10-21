"""Read-only checks for the curated PEM-to-ontology mapping."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS


ROOT = Path(__file__).resolve().parent
ENTITY_TYPES = {
    "ResearchField", "Concept", "Method", "Process", "Artifact",
    "Material", "Organization", "Content", "Data", "Other",
}
RELATION_LABELS = {
    "causes", "affects", "influences", "results_in", "precedes",
    "produces", "uses", "part_of", "contains",
    "leads_to", "follows", "degrades", "increases", "decreases",
    "depends_on", "requires", "used_for", "occurs_in", "optimizes",
    "supports", "studies", "measures", "published_by", "authored_by",
    "evidenced_by", "described_in", "collaborates_with", "compared_with",
    "similar_to", "related_to", "associated_with",
}
MAPPED_STATES = {"mapped", "conditional"}


def validate_mapping(
    mapping: dict, graph: Graph, manifest: dict, sources_root: Path
) -> list[str]:
    """Return validation errors without modifying the mapping or source graph."""

    errors: list[str] = []
    if mapping.get("schema_version") != 1:
        errors.append("Unsupported mapping schema_version")
    if not mapping.get("mapping_version"):
        errors.append("Missing mapping_version")

    for source, version in mapping.get("source_versions", {}).items():
        current = manifest.get("sources", {}).get(source, {}).get("used_version")
        if current != version:
            errors.append(f"Source version drift: {source}: {version} != {current}")
    if not mapping.get("compatibility"):
        errors.append("Missing mixed-version compatibility statement")

    source_cache: dict[str, Graph] = {}
    for section, expected, rdf_type in (
        ("entity_types", ENTITY_TYPES, OWL.Class),
        ("relations", RELATION_LABELS, OWL.ObjectProperty),
    ):
        rows = mapping.get(section, [])
        labels = [row.get("label") for row in rows]
        if len(labels) != len(set(labels)):
            errors.append(f"Duplicate labels in {section}")
        if set(labels) != expected:
            errors.append(f"{section} label coverage differs: {sorted(expected ^ set(labels))}")

        for row in rows:
            label = row.get("label", "<missing>")
            status = row.get("status")
            iri = row.get("iri")
            if status not in MAPPED_STATES | {"ambiguous", "unmapped"}:
                errors.append(f"{label}: invalid status")
                continue
            if status in MAPPED_STATES:
                if not iri or not row.get("source_file") or not row.get("source_ontology"):
                    errors.append(f"{label}: missing mapped IRI or attribution")
                    continue
                if row["source_ontology"] not in mapping.get("source_versions", {}):
                    errors.append(f"{label}: source ontology is not version-pinned")
                term = URIRef(iri)
                if (term, RDF.type, rdf_type) not in graph:
                    errors.append(f"{label}: IRI is not a pinned {rdf_type}")
                if str(term).startswith("https://w3id.org/battinfo/"):
                    errors.append(f"{label}: BattINFO record placeholder is not a domain mapping")
                source_file = row["source_file"]
                if Path(source_file).name != source_file:
                    errors.append(f"{label}: source_file must be a basename")
                    continue
                path = sources_root / source_file
                if not path.is_file():
                    errors.append(f"{label}: source file missing: {source_file}")
                else:
                    if source_file not in source_cache:
                        source_cache[source_file] = Graph().parse(path, format="turtle")
                    if not any(source_cache[source_file].triples((term, None, None))):
                        errors.append(f"{label}: IRI absent from attributed source")
                if status == "conditional" and not row.get("condition"):
                    errors.append(f"{label}: conditional mapping lacks condition")
                if not row.get("preferred_label"):
                    errors.append(f"{label}: missing mapping metadata")
            elif iri is not None:
                errors.append(f"{label}: unresolved mapping must not have a canonical IRI")
            elif not row.get("reason"):
                errors.append(f"{label}: unresolved mapping lacks reason")

            for candidate in row.get("candidate_iris", []):
                if (URIRef(candidate), RDF.type, rdf_type) not in graph:
                    errors.append(f"{label}: candidate IRI absent or wrong type: {candidate}")

            inverse = row.get("inverse")
            if inverse:
                other = URIRef(inverse.get("iri", ""))
                term = URIRef(iri or "")
                if (other, RDF.type, OWL.ObjectProperty) not in graph:
                    errors.append(f"{label}: inverse IRI absent or wrong type")
                if not inverse.get("swap_endpoints"):
                    errors.append(f"{label}: inverse must swap endpoints")
                if (
                    (term, OWL.inverseOf, other) not in graph
                    and (other, OWL.inverseOf, term) not in graph
                ):
                    errors.append(f"{label}: inverse not asserted in pinned graph")

            aliases = row.get("aliases", [])
            if len(aliases) != len(set(aliases)) or label in aliases:
                errors.append(f"{label}: duplicate alias")
            if status in MAPPED_STATES and row.get("preferred_label"):
                labels = {str(value) for value in graph.objects(URIRef(iri), RDFS.label)}
                if row["preferred_label"] not in labels:
                    errors.append(f"{label}: preferred label differs from pinned graph")
    return errors


def audit(root: Path = ROOT) -> list[str]:
    mapping = json.loads((root / "pem_mapping_v1.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    graph = Graph().parse(root / "merged" / "merged.ttl", format="turtle")
    return validate_mapping(mapping, graph, manifest, root / "sources" / "bto")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    errors = audit(args.root)
    for error in errors:
        print(f"ERROR: {error}")
    if not errors:
        print("PEM ontology mapping v1: valid (read-only; not enabled in runtime)")
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
