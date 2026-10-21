# Ontology Integration Plan

Status (2026-10-21): ONT-01 through ONT-03 complete. ONT-04 has an
experimental, default-off graph annotation path and ONT-05 has optional
benchmark diagnostics. Neither has passed a staging pilot or domain review;
ONT-04 through ONT-06 remain open. No production deployment.

## Goal And Baseline

Use the supervisor's ontology material to improve entity typing, predicate
consistency and explainable directed paths. Keep the current PEM labels and
document evidence intact. The ontology provides candidate concepts, aliases,
hierarchies and constraints; it does not establish that a relation extracted
from a document is true.

Runtime uses `lightrag/relation_ontology.py` for conservative label
normalization and benchmark similarity. Experimental annotations are in
`lightrag/ontology_annotation.py` and require `ONTOLOGY_ANNOTATION_ENABLED=true`.
Extraction is in `lightrag/operate.py`
and `prompts/entity_type/*.yml`; directed paths use
`lightrag/directed_retrieval.py`, and Neo4j storage is in
`lightrag/kg/neo4j_impl.py`. The optional annotation module reads the pinned
`ontology/pem_mapping_v1.json`; it does not load the RDF graph at runtime.
Normal retrieval remains the default.

## Local Material Review

| Material | Current finding | Intended use |
| --- | --- | --- |
| `ontology/sources/bto/*.ttl` | 49 Turtle files now present | Offline ontology source closure |
| `ontology/sources/battinfo.ttl` and `battinfo-records-placeholder-vocab.ttl` | Both present; the latter contains record-layer placeholders | Separate domain concepts from software-record terms |
| `ontology/sources/battinfo-repo/` | A separate, large BattINFO software checkout with its own Apache-2.0 license | Review provenance; do not import or commit wholesale as runtime ontology |
| `ontology/merged/merged.ttl` and `merge_report.json` | Report lists 51 parsed files, zero failures, 65,882 triples, 4,725 classes and 310 object properties | Versioned, checked input to mapping work |
| `ontology/manifest.json` | Source versions, licenses, SHA-256 pins and historical merge notes | Provenance for current 0.7.0 snapshot |
| `ontology/inventory/*.csv` | Class/property inventory and screened relation candidates | Human review, not automatic extraction allowlist |
| `ontology/relation_types.json` | Provisional relation families based on a narrow pilot | Curate mappings; do not treat as validated production gold |
| `ontology/type_mapping_emmo.json`, `subproperties.json` | Coarse type rules and subproperty/inverse hints | Typed diagnostics and mapping candidates |

The previous note that `sources/bto/` is missing is obsolete. The 49 BTO
files plus two BattINFO source files match the 51 filenames in the merge
report. The current pinned graph contains 65,882 triples and BattINFO
0.7.0/Apache-2.0. The previous 65,863-triple, 0.8.0-beta/CC BY 4.0 merge is
preserved under `ontology/history/`; its standalone source is not recoverable.
See `ontology/README.md` for the audit and mixed-version import caveat.
The separate `domain-battery-0.20.2.ttl` is a header with imports;
the locally resolved module closure is under `sources/bto/`. The manifest and
inventory contain historical counts and notes; verification must distinguish
current counts from earlier versions. Some notes refer to `NOTES.md` and
`map.md`, which are not present at the top of this checkout. Record missing
provenance rather than silently treating those references as current evidence.

## Integration Contract

1. **One versioned mapping, two labels.** Preserve `relation_type` and
   `entity_type` as extracted; add separate canonical predicate/class IRI,
   mapping version and mapping status. Do not rewrite old Neo4j edges in place.
2. **Direction is semantic.** Map inverse labels only with an endpoint swap.
   Keep `A causes B` distinct from `B causes A`; do not equate temporal order
   with causation. `part_of`/`contains` needs explicit inverse handling.
3. **Uncertainty stays visible.** Unknown or ambiguous terms remain usable as
   legacy labels, marked for review. Domain/range checks initially warn; they
   must not silently delete assertions or overfit broad upper classes.
4. **Source and version travel with assertions.** Keep document/chunk IDs,
   evidence text, extraction revision, prompt profile, ontology source version
   and source URL. Validate the same contract in normal and Azure Batch flows.
5. **Optional and reversible.** Gate ontology enrichment independently of
   normal retrieval. Keep a baseline query path and compare before promotion.

## Ordered Implementation

The canonical task order and checkboxes are in [Project TODO](PROJECT_TODO.md).
Each item below supplies the design details for that queue item.

### ONT-01: Reproducibility And Source Audit

Implemented: a validator for expected filenames, parseability, version identifiers,
source licenses and merge-report counts. Compare against existing artefacts in
a temporary or in-memory graph; do not run `build_merged.py` against the
checked-in baseline during audit because it overwrites the merged file and
report. Record whether the full BattINFO repository is needed at all; its
software license differs from the ontology source-license summary. Report
label conflicts and unavailable historical notes. Use `ontology/manifest.json`,
`build_merged.py` and `merge_report.json` as inputs. ONT-01B reconciled the
detected source snapshot before ONT-02. Estimated work: 0.5-1 day.

### ONT-02: Versioned Mapping

Design a compact mapping JSON/YAML under `ontology/` with schema version,
source ontology versions, original label, canonical IRI, aliases, inverse,
direction, domain/range hint, relation family and review state. Begin with
the predicates already used in PEM examples (`causes`, `affects`,
`influences`, `results_in`, `precedes`, `produces`, `uses`, `part_of`,
`contains`). Inspect ontology definitions, not label similarity alone. Keep
`relation_types.json` as a candidate source and review conflicts against
`lightrag/relation_ontology.py`; preserve unmapped labels. Add validation of
IRI existence and inverse consistency. Review the BattINFO import-version
mismatch before relying on domain/range axioms across these versions.
Estimated work: 1-2 days plus domain review.

Implemented as `ontology/pem_mapping_v1.json` with read-only validation in
`ontology/validate_mapping.py`. The offline mapping is intentionally not a
runtime allowlist: 31 current relation labels and ten entity types are covered,
but only strong or explicitly conditional EMMO core matches receive canonical
IRIs. `precedes`/`follows`, broad effect and input labels remain unresolved
where the pinned definitions are narrower. Domain review of conditional cases
is still required before using the mapping in production data paths.

### ONT-03: Resolver Without Runtime Writes

Implement a deterministic resolver using the reviewed mapping. Normalize
surface forms conservatively, resolve `skos:prefLabel`, `rdfs:label` and
`skos:altLabel`, avoid collisions across namespaces, and return a structured
unknown/ambiguous result. Test class and predicate resolution separately,
including German-English aliases and BattINFO placeholder exclusions. Integrate
as an optional read-only adapter for experiments; no migration. Candidate code:
`lightrag/relation_ontology.py` plus a focused new ontology module and tests.
Estimated work: 1-2 days.

Implemented in `ontology/resolver.py` as an explicit offline adapter. It
validates the pinned mapping on load, keeps conditional mappings as candidates,
checks PEM domain/range hints without asserting OWL entailments, excludes
BattINFO placeholders and reports lexical collisions instead of guessing.
There is no runtime import or graph write. See `ontology/README.md` for the
CLI and `tests/ontology/test_resolver.py` for DE/EN, inverse and collision
regressions.

### ONT-04: Extraction And Storage Pilot

Attach optional ontology metadata after extraction, before merge. Review
`operate.py`, `lightrag.py`, `extraction_revisions.py`, Azure Batch import,
all graph-storage implementations, Neo4j serialization, and deletion/rebuild
paths. Audit how multiple assertions between one entity pair are represented:
the current pair-based merge can collapse distinct relations, so ontology
mapping cannot repair lost assertions. Preserve the raw predicate and evidence
even if ontology normalization succeeds. Test an isolated staging workspace
with retained chunks and preserved source URLs. Estimated work: 2-4 days;
assertion-preservation migration may require the separate P4 project.

Partial implementation: optional flat-string `ontology_mapping_version`,
`ontology_mapping_status`, `ontology_iri` and `ontology_source` properties are
written at entity/relation merge. Only `status=mapped` asserts an IRI;
conditional and ambiguous rows clear stale IRIs. The source mapping is copied
into the API image. Batch import rejects a changed mapping snapshot before
graph writes. New opt-in extractions also retain the extracted raw entity type
and predicate where available; legacy rows cannot recover already discarded
raw labels. Default-off extraction remains unchanged. These are **not**
acceptance evidence: the current graph still collapses multiple predicates
for one unordered entity pair, and deletion/rebuild paths use older relation
keys. Source URLs remain on document metadata, not individual edges.

### ONT-05: Benchmark And Retrieval Pilot

Add reporting for raw-label exactness, mapped-IRI exactness, alias/inverse
equivalence, hierarchy-aware partial credit, unmapped rate and false-positive
rate. A parent class/predicate match must not count as an exact match.
Evaluate against reviewed annotations from battery manufacturing, defects,
electrochemistry and German/English documents; hold out whole document
families. Compare normal, directed and combined retrieval with matched costs
and context budgets. Only then add optional ontology-aware predicate expansion
to `adaptive_retrieval.py` and `directed_retrieval.py`. Estimated work: 2-4
days plus gold-data review.

Partial implementation: `ontology_diagnostics=true` in a benchmark enables
separate per-case raw, mapped-IRI, alias, inverse, hierarchy and false-positive
diagnostics. It does not change Overall, Graph or Directed scores. Conditional
mappings do not receive IRI equivalence credit. No reviewed hierarchy entries
or held-out staging comparisons exist yet. Ontology-aware directed retrieval
remains disabled pending domain review and measured false positives.

### ONT-06: Decision And Rollout

Version ontology source, mapping schema and extraction algorithm separately.
Choose metadata backfill versus retained-chunk re-extraction based on whether
the change alters only labels or changes assertions. Write a staging migration
and rollback runbook with counts of mapped/unmapped edges, document-level
completion and a no-data-loss check. Gate production promotion on measured
quality and backward compatibility. Estimated work: 1-2 days.

The staging procedure and decision template are in
`docs/ONTOLOGY_STAGING_PILOT.md`. Its go/no-go remains pending real pilot data.

## Acceptance For The Overall Effort

- Each mapped IRI resolves to the pinned local source graph; attribution and
  versions are documented.
- A directed three-hop causal example preserves orientation and cites its
  originating chunks. Inverse predicates receive the correct endpoint swap.
- Legacy documents and all existing query modes continue to work; ontology
  mode can be disabled without data migration.
- Held-out results show entity/relation precision and recall, path quality,
  supported-answer quality, latency and cost beside the baseline. A high
  metadata score alone is not acceptance.
- Staging rollback and partial-failure recovery are rehearsed before any
  production change.
