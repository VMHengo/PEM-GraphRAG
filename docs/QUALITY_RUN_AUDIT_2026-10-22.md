# Staging quality-run audit (2026-10-22)

This is an offline analysis of the user-provided, saved **retrieval-mode** run
`pem_quality_docs_multihop_mean_test` from 2026-10-22 10:24 UTC. The raw run
is intentionally not committed. The corresponding `mean_test` fixture is not
in this checkout; the 18 expected relation lists were checked against the
tracked `pem_quality_docs_multihop.json` and match exactly. Its evidence page
references below are leads for review, not substitute graph or chunk evidence.

## Frozen configuration and denominators

- Scorer 2.0.0, directed profile: Graph 35%, Retrieval 15%, Directed 50%.
  Overall 38.89, Graph 64.31, Retrieval 96.52, Directed 3.81, Exact 0.
- Extraction revision 1.0.1, relation schema 1, active PEM entity-type
  prompt, GPT-5.4-mini, ontology annotation disabled. The saved run records
  the extraction fingerprint and Git revision; it does **not** prove every
  previously ingested document used that revision.
- 18 graph, query and directed cases; 69/96 entity checks exact, 0/45
  relation checks exact, 19/20 expected document references found.
  Thirteen directed cases returned candidate paths; five returned none.
  Only three cases received nonzero directed partial credit.
- This run uses scorer 2.0.0, which checks pair-level edge representatives.
  It cannot rule out a matching stored `relation_assertions_json` entry.
  Scorer 2.1.0 now expands those assertions. The same graph must be re-scored
  before interpreting the 0/45 count as an extraction failure.
- Query status was successful for all 18 cases. The retrieval score measures
  expected terms and references, not claim truth or multi-hop reasoning.

## Ten-case triage sample

All classifications below are **provisional**. `R` is pair-level relation
score, `P` is directed partial score, and `N` is returned candidate paths.
Evidence pages refer to the tracked base fixture; inspect the actual source
chunks and graph assertions before declaring a missing fact.

| Case | R | P | N | First check | Evidence lead |
| --- | ---: | ---: | ---: | --- | --- |
| `mh_aging_gas_current_plating` | 0 | 0 | 1 | Stored assertions; gold skips electrode spacing | aging p4 |
| `mh_root_plating_local_current` | 0 | 0 | 18 | Same graph facts as preceding case, reverse traversal anchors | aging p4 |
| `mh_plating_sei_impedance` | 30 | 0 | 0 | Stored assertions, then anchor/filter stage | aging p4 |
| `mh_aging_resistance_irreversible_heat` | 72.42 | 0 | 4 | Best pair-level matches use generic temperature/resistance edges; inspect exact assertion and path | aging p8-9 |
| `mh_cold_resistance_joule_heat` | 63.15 | 0 | 2 | Inspect predicate, endpoints and path anchors | heat_factors p3 |
| `mh_root_joule_heat_cold` | 63.15 | 0 | 8 | Same expected mechanism, reverse traversal; not independent evidence | heat_factors p3 |
| `mh_separator_short_additional_heat` | 0 | 0 | 0 | Stored assertions and source extraction completeness | thermal_review p5 |
| `mh_heat_accumulation_hotspots` | 0 | 0 | 6 | Stored assertions, then anchors and pruning | thermal_design p1 |
| `mh_hppc_heat_parameter_state_error` | 15.58 | 0 | 0 | Entity resolution and assertion presence before path search | estimation_review p1, p7 |
| `mh_root_pbm_temperature_overprediction` | 0 | 0 | 9 | Source wording, stored assertions and reverse path anchors | model_comparison p11-12 |

## What the saved run cannot settle

- A zero or partial pair-level score is **not** proof the assertion is absent.
  Read `relation_assertions_json` for the expected entity pairs and source
  chunks. If present, distinguish scoring-only from traversal filtering.
- A returned path can be unrelated to the expected chain. `path_status` of
  `completed` only says the provider completed; it does not mean a gold path
  was found. The path list includes source IDs, but absent graph-neighbor and
  pruning counters it cannot identify the first rejected stage.
- No full-credit semantic path paired with a failed strict check was observed;
  `Directed Exact = 0` alone does not establish a strict-only mismatch.
- The source page anchors were reviewed when the base fixture was authored,
  but this saved result does not include original PDF passages or a graph
  snapshot. Gold granularity (notably the omitted electrode-spacing step)
  needs a source-grounded decision rather than an automatic relaxation.

## Next read-only checks

1. Re-score the **unchanged** Staging graph with scorer 2.1.0, graph mode.
   Compare relation checks and assertion/pair counts against this frozen run.
2. For the ten cases above, inspect bounded matching assertions and their
   `source_id`/`file_path` through the diagnostic connector or read-only
   Neo4j. Confirm source chunks against the cited PDF pages. Record whether
   each gold edge is absent, present-but-filtered, or represented by a
   different, evidence-supported intermediate.
3. For graph-present but missing paths, inspect seed anchors, query-specific
   predicate allowlists and pruning limits. No extraction/model calls are
   needed for these checks.

This audit is not answer accuracy and does not justify re-extracting all
documents. Keep this run as the scorer-2.0.0 baseline.
