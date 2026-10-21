# Ontology Integration Plan

Status: planned, 2026-10-21. This is a local source review, not a claim that
the ontology has been integrated into the runtime or deployed.

## Goal And Baseline

Use the supervisor's ontology material to improve entity typing, predicate
consistency and explainable directed paths. Keep the current PEM labels and
document evidence intact. The ontology provides candidate concepts, aliases,
hierarchies and constraints; it does not establish that a relation extracted
from a document is true.

Runtime today uses `lightrag/relation_ontology.py` for conservative label
normalization and benchmark similarity. Extraction is in `lightrag/operate.py`
and `prompts/entity_type/*.yml`; directed paths use
`lightrag/directed_retrieval.py`, and Neo4j storage is in
`lightrag/kg/neo4j_impl.py`. No runtime module currently reads `ontology/`.
Normal retrieval remains the default.

## Local Material Review

| Material | Current finding | Intended use |
| --- | --- | --- |
| `ontology/sources/bto/*.ttl` | 49 Turtle files now present | Offline ontology source closure |
| `ontology/sources/battinfo.ttl` and `battinfo-records-placeholder-vocab.ttl` | Both present; the latter contains record-layer placeholders | Separate domain concepts from software-record terms |
| `ontology/sources/battinfo-repo/` | A separate, large BattINFO software checkout with its own Apache-2.0 license | Review provenance; do not import or commit wholesale as runtime ontology |
| `ontology/merged/merged.ttl` and `merge_report.json` | Report lists 51 parsed files, zero failures, 65,863 triples, 4,725 classes and 310 object properties | Versioned, checked input to mapping work |
| `ontology/manifest.json` | Source versions, attribution and historical merge notes | Provenance; reconcile with current files |
| `ontology/inventory/*.csv` | Class/property inventory and screened relation candidates | Human review, not automatic extraction allowlist |
| `ontology/relation_types.json` | Provisional relation families based on a narrow pilot | Curate mappings; do not treat as validated production gold |
| `ontology/type_mapping_emmo.json`, `subproperties.json` | Coarse type rules and subproperty/inverse hints | Typed diagnostics and mapping candidates |

The previous note that `sources/bto/` is missing is obsolete. The 49 BTO
files plus two BattINFO source files match the 51 filenames in the merge
report. The separate `domain-battery-0.20.2.ttl` is a header with imports;
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

Add a validator for expected filenames, parseability, version identifiers,
source licenses and merge-report counts. Compare against existing artefacts in
a temporary or in-memory graph; do not run `build_merged.py` against the
checked-in baseline during audit because it overwrites the merged file and
report. Record whether the full BattINFO repository is needed at all; its
software license differs from the ontology source-license summary. Report
label conflicts and unavailable historical notes. Use `ontology/manifest.json`,
`build_merged.py` and `merge_report.json` as inputs. Estimated work: 0.5-1 day.

### ONT-02: Versioned Mapping

Design a compact mapping JSON/YAML under `ontology/` with schema version,
source ontology versions, original label, canonical IRI, aliases, inverse,
direction, domain/range hint, relation family and review state. Begin with
the predicates already used in PEM examples (`causes`, `affects`,
`influences`, `results_in`, `precedes`, `produces`, `uses`, `part_of`,
`contains`). Inspect ontology definitions, not label similarity alone. Keep
`relation_types.json` as a candidate source and review conflicts against
`lightrag/relation_ontology.py`; preserve unmapped labels. Add validation of
IRI existence and inverse consistency. Estimated work: 1-2 days plus domain
review.

### ONT-03: Resolver Without Runtime Writes

Implement a deterministic resolver using the reviewed mapping. Normalize
surface forms conservatively, resolve `skos:prefLabel`, `rdfs:label` and
`skos:altLabel`, avoid collisions across namespaces, and return a structured
unknown/ambiguous result. Test class and predicate resolution separately,
including German-English aliases and BattINFO placeholder exclusions. Integrate
as an optional read-only adapter for experiments; no migration. Candidate code:
`lightrag/relation_ontology.py` plus a focused new ontology module and tests.
Estimated work: 1-2 days.

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

### ONT-06: Decision And Rollout

Version ontology source, mapping schema and extraction algorithm separately.
Choose metadata backfill versus retained-chunk re-extraction based on whether
the change alters only labels or changes assertions. Write a staging migration
and rollback runbook with counts of mapped/unmapped edges, document-level
completion and a no-data-loss check. Gate production promotion on measured
quality and backward compatibility. Estimated work: 1-2 days.

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
