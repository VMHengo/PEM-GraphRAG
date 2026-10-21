"""The optional resolver must never reinterpret uncertain assertions as facts."""

import copy
import json

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import SKOS

from lightrag.relation_ontology import canonicalize_relation
from ontology.resolver import OntologyResolver, normalize_label
from ontology.validate_mapping import ROOT


@pytest.fixture(scope="module")
def resolver():
    return OntologyResolver.from_project()


def test_normalization_and_german_english_aliases(resolver):
    assert normalize_label("  isCauseOf  ") == "is_cause_of"
    assert normalize_label("ENTHÄLT") == "enthaelt"
    cause = resolver.resolve_relation("verursacht")
    assert cause.status == "mapped"
    assert cause.canonical_label == "causes"
    assert cause.iri.endswith("EMMO_d67ee67e_4fac_4676_82c9_aec361dba698")
    assert resolver.resolve_relation("isCauseOf").iri == cause.iri
    assert resolver.resolve_relation("enthaelt").status == "conditional"
    assert resolver.resolve_entity_type("Werkstoff").status == "conditional"


def test_inverse_swaps_semantic_endpoints(resolver):
    caused_by = resolver.resolve_relation("caused_by")
    assert caused_by.status == "mapped"
    assert caused_by.canonical_label == "causes"
    assert caused_by.swap_endpoints is True
    assert caused_by.iri == resolver.resolve_relation("causes").iri
    assert resolver.resolve_relation("hasPart").canonical_label == "contains"
    assert resolver.resolve_relation("isPartOf").canonical_label == "part_of"


def test_conditional_and_incompatible_hints(resolver):
    output = resolver.resolve_relation("produces", source_type="Process", target_type="Artifact")
    assert output.status == "conditional"
    assert output.iri is None
    assert len(output.candidate_iris) == 1
    assert resolver.resolve_relation("produces", source_type="Artifact").status == "incompatible"
    inverse = resolver.resolve_relation(
        "produced_by", source_type="Artifact", target_type="Process"
    )
    assert inverse.status == "conditional"
    assert inverse.swap_endpoints is True
    assert resolver.resolve_relation(
        "produced_by", source_type="Process", target_type="Artifact"
    ).status == "incompatible"


def test_ambiguity_missing_mapping_and_placeholders(resolver):
    assert resolver.resolve_relation("affects").status == "ambiguous"
    assert resolver.resolve_relation("precedes").iri is None
    assert resolver.resolve_relation("does_not_exist").status == "unknown"
    assert resolver.resolve_entity_type("Method").status == "unmapped"
    assert resolver.resolve_entity_type("https://w3id.org/battinfo/Material").status == "unmapped"
    assert resolver.resolve_entity_type("battinfo:Method").status == "unmapped"
    assert resolver.resolve_entity_type("Material").status == "conditional"
    object_match = resolver.resolve_entity_type("Object")
    assert object_match.status == "ambiguous"
    assert len(object_match.candidate_iris) == 2


def test_curated_alias_collision_stays_ambiguous():
    mapping = json.loads((ROOT / "pem_mapping_v1.json").read_text(encoding="utf-8"))
    mapping = copy.deepcopy(mapping)
    mapping["relations"][0]["aliases"].append("shared predicate")
    mapping["relations"][5]["aliases"].append("shared predicate")
    result = OntologyResolver(mapping, Graph()).resolve_relation("shared predicate")
    assert result.status == "ambiguous"
    assert result.iri is None
    assert len(result.candidate_iris) == 2


def test_skos_label_from_reviewed_iri_only():
    mapping = json.loads((ROOT / "pem_mapping_v1.json").read_text(encoding="utf-8"))
    graph = Graph()
    iri = URIRef(mapping["relations"][0]["iri"])
    graph.add((iri, SKOS.altLabel, Literal("Kausalursache", lang="de")))
    result = OntologyResolver(mapping, graph).resolve_relation("Kausalursache")
    assert result.status == "mapped"
    assert result.iri == str(iri)


def test_resolver_does_not_change_legacy_relation_logic(resolver):
    before = canonicalize_relation("B", "A", "caused_by")
    resolver.resolve_relation("caused_by")
    assert canonicalize_relation("B", "A", "caused_by") == before
