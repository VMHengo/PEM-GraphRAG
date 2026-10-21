"""Read-only, opt-in PEM label resolver for the pinned ontology mapping.

This module is not imported by extraction, storage or retrieval. Conditional
matches are candidates, never assertions that an extracted fact is true.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from ontology.validate_mapping import ROOT, validate_mapping


_LABEL_PREDICATES = (RDFS.label, SKOS.prefLabel, SKOS.altLabel)
_PLACEHOLDER_PREFIX = "https://w3id.org/battinfo/"


def normalize_label(value: object) -> str:
    """Conservatively normalize spacing, case, camelCase and German umlauts."""

    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text)
    text = text.casefold().translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue"}))
    return re.sub(r"[^\w]+", "_", text).strip("_")


@dataclass(frozen=True)
class Resolution:
    input_label: str
    status: str
    mapping_version: str
    canonical_label: str | None = None
    iri: str | None = None
    candidate_iris: tuple[str, ...] = ()
    swap_endpoints: bool = False
    source_ontology: str | None = None
    source_file: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class _Match:
    row: dict[str, Any]
    inverse: bool = False


class OntologyResolver:
    """Resolve only curated PEM labels; never expand arbitrary graph terms."""

    def __init__(self, mapping: dict[str, Any], graph: Graph):
        if mapping.get("schema_version") != 1:
            raise ValueError("Unsupported ontology mapping schema")
        self.mapping_version = str(mapping["mapping_version"])
        self._index: dict[str, dict[str, list[_Match]]] = {
            "entity_types": {}, "relations": {}
        }
        self._graph_labels: dict[str, dict[str, set[str]]] = {
            "entity_types": {}, "relations": {}
        }
        self._explicit: dict[str, set[str]] = {"entity_types": set(), "relations": set()}
        for section in self._index:
            for row in mapping[section]:
                self._add(section, row["label"], _Match(row))
                self._explicit[section].add(normalize_label(row["label"]))
                for alias in row.get("aliases", []):
                    self._add(section, alias, _Match(row))
                    self._explicit[section].add(normalize_label(alias))
                if row.get("preferred_label"):
                    self._add(section, row["preferred_label"], _Match(row))
                if row.get("inverse"):
                    self._add(section, row["inverse"]["label"], _Match(row, True))
                if row.get("iri"):
                    iri = URIRef(row["iri"])
                    for predicate in _LABEL_PREDICATES:
                        for label in graph.objects(iri, predicate):
                            self._add(section, str(label), _Match(row))

        # Inspect label collisions only for names the curated mapping accepts.
        for section, rdf_type in (
            ("entity_types", OWL.Class), ("relations", OWL.ObjectProperty)
        ):
            accepted = self._index[section]
            for predicate in _LABEL_PREDICATES:
                for iri, label in graph.subject_objects(predicate):
                    if not isinstance(iri, URIRef) or (iri, RDF.type, rdf_type) not in graph:
                        continue
                    if str(iri).startswith(_PLACEHOLDER_PREFIX):
                        continue
                    key = normalize_label(label)
                    if key in accepted:
                        self._graph_labels[section].setdefault(key, set()).add(str(iri))

    @classmethod
    def from_project(cls, root: Path = ROOT) -> OntologyResolver:
        mapping = json.loads((root / "pem_mapping_v1.json").read_text(encoding="utf-8"))
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        graph = Graph().parse(root / "merged" / "merged.ttl", format="turtle")
        errors = validate_mapping(mapping, graph, manifest, root / "sources" / "bto")
        if errors:
            raise ValueError("Ontology mapping validation failed: " + "; ".join(errors))
        return cls(mapping, graph)

    def _add(self, section: str, label: str, match: _Match) -> None:
        key = normalize_label(label)
        if key:
            matches = self._index[section].setdefault(key, [])
            if match not in matches:
                matches.append(match)

    def resolve_entity_type(self, label: str) -> Resolution:
        return self._resolve("entity_types", label)

    def resolve_relation(
        self, label: str, *, source_type: str | None = None,
        target_type: str | None = None,
    ) -> Resolution:
        return self._resolve("relations", label, source_type, target_type)

    def _resolve(
        self, section: str, label: str,
        source_type: str | None = None, target_type: str | None = None,
    ) -> Resolution:
        raw = str(label)
        if raw.startswith(_PLACEHOLDER_PREFIX) or raw.casefold().startswith("battinfo:"):
            return Resolution(raw, "unmapped", self.mapping_version,
                              reason="BattINFO record placeholders are excluded")
        key = normalize_label(raw)
        matches = self._index[section].get(key, [])
        if not matches:
            return Resolution(raw, "unknown", self.mapping_version,
                              reason="No reviewed PEM mapping for this label")

        # A direct label takes precedence over a semantically equivalent inverse.
        direct = [match for match in matches if not match.inverse]
        if direct:
            matches = direct
        unique = {(match.row["label"], match.inverse): match for match in matches}
        matches = list(unique.values())
        curated_iris = {
            match.row["iri"] for match in matches if match.row.get("iri")
        }
        graph_iris = self._graph_labels[section].get(key, set())
        external = graph_iris - curated_iris
        if len(matches) != 1 or (curated_iris and external and key not in self._explicit[section]):
            candidates = set(curated_iris) | graph_iris
            for match in matches:
                candidates.update(match.row.get("candidate_iris", []))
            return Resolution(raw, "ambiguous", self.mapping_version,
                              candidate_iris=tuple(sorted(candidates)),
                              reason="Label collision across mappings or ontology IRIs")

        match = matches[0]
        row = match.row
        status = row["status"]
        inverse = match.inverse
        if inverse:
            source_type, target_type = target_type, source_type
        for name, actual in (("domain", source_type), ("range", target_type)):
            hint = row.get(f"{name}_hint")
            if hint and actual:
                allowed = {normalize_label(value) for value in hint.split("|")}
                if normalize_label(actual) not in allowed:
                    return Resolution(
                        raw, "incompatible", self.mapping_version,
                        canonical_label=row["label"],
                        candidate_iris=(row["iri"],) if row.get("iri") else (),
                        swap_endpoints=inverse,
                        reason=f"{name} type {actual!r} conflicts with {hint!r}",
                    )

        iri = row.get("iri") if status == "mapped" else None
        candidates = set(row.get("candidate_iris", []))
        if status == "conditional" and row.get("iri"):
            candidates.add(row["iri"])
        return Resolution(
            raw, status, self.mapping_version, canonical_label=row["label"],
            iri=iri, candidate_iris=tuple(sorted(candidates)),
            swap_endpoints=inverse, source_ontology=row.get("source_ontology"),
            source_file=row.get("source_file"),
            reason=row.get("condition") or row.get("reason") or row.get("note"),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve one PEM label without graph writes")
    parser.add_argument("kind", choices=("entity", "relation"))
    parser.add_argument("label")
    parser.add_argument("--source-type")
    parser.add_argument("--target-type")
    args = parser.parse_args()
    resolver = OntologyResolver.from_project()
    if args.kind == "entity":
        result = resolver.resolve_entity_type(args.label)
    else:
        result = resolver.resolve_relation(
            args.label, source_type=args.source_type, target_type=args.target_type
        )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
