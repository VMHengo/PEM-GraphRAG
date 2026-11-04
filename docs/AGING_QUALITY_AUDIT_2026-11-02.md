# Aging-Paper Quality Audit (offline, 2026-11-02)

## Inputs and limits

- Saved single-document Validation result: scorer 2.1.0, directed profile,
  40.7 overall, 56.5 graph, 29.6 directed, 0 directed exact. This is the
  earlier 2026-10-25 Validation run, not the later reported 49.9 run.
- Matching saved prompt-experiment extraction artifact: parsed entity and
  relation records per retained chunk. No live Neo4j snapshot or original
  raw Batch output was compared in this audit.
- Source PDF: `test_documents/quality_docs/Heat Generation and Degradation
  Mechanism of Lithium-Ion Batteries during High-Temperature Aging.pdf`.
  Its heat-balance passage states that generated heat has irreversible and
  reversible components (Equation 4). That supports the structural inverse
  `Irreversible/Reversible Heat --part_of--> Total Heat`.

## Observations

The saved graph result has **31 zero-scored expected relation checks**. The
read-only `scripts/audit_aging_relations.py` comparison with the parsed
artifact groups 23 as *endpoint absent or gold-name mismatch* and 8 as
*relation absent or gold mismatch*. These are triage categories, **not** a
claim that the PDF lacks the facts or that the model missed all 31. The
artifact contains `Irreversible Heat --part_of--> Total Heat` and `Reversible
Heat --part_of--> Total Heat`; the old gold accepted only forward `contains`.
Replaying just this case with the same parsed artifact and the reviewed inverse
rule changes its relation score from 0 to 100, without an extraction call.
Across all 38 cases on the same 224 parsed assertions (210 distinct physical
pairs), the offline relation score moves from 31.79 to 36.79 and relation
exact from 21.67 to 26.67. Entity score stays 79.65 and entity exact 66.85;
`relations_heat_decomposition` is the only changed case. This replays parsed
records, not the merged live graph, so its scores need not equal the saved
Validation result.

Other examples needing PDF and raw-output review: `Local Potential Change`,
`IC Peak Shift to Lower Voltage`, and the passive characterization methods
are absent under their gold names in the parsed artifact. Some may be naming
differences; others may be genuine extraction loss. The previous original
Batch outputs for this paper ended at `max_output_tokens` for all 10 chunks,
so truncation is a plausible source of loss but not a per-relation proof.

A separate known failure is retrieval-side: the graph scored both
`High-Temperature Aging -> DC Resistance` and `DC Resistance -> Irreversible
Heat` in an earlier case, while the directed path check returned zero. Do not
attribute that miss to extraction without inspecting anchors, provider caps,
filters, ranking and source handling on a frozen graph.
In that saved run, the `causal_chain` route's recorded predicate allowlist
omits `increases`, the type of both graph-scored edges. The current router
includes `increases`, so predicate filtering is a concrete, version-specific
candidate cause; a frozen-graph Staging replay is still needed to establish
whether the path now survives provider limits and top-20 ranking.
An offline replay against the saved 224-assertion artifact with the current
router and benchmark settings exposed a second loss stage: the first edge to
`DC Resistance` was ranked 17th, below `chain_fanout=10`. An exact focus-entity
match now receives a bounded 0.18 edge-ranking bonus before that local fanout.
With the benchmark's `ll_keywords` (which include the gold intermediate
`DC Resistance`), the two-hop path appears in the top 20 with chunk-000 and
chunk-006 citations. This is an **oracle-aided upper bound**, not a realistic
query-only result: the actual question does not name `DC Resistance`.
Using only the question's start and endpoint terms still misses the path at
fanout 10; fanout 20 recovers it offline with more expansion. Neither replay
validates live Neo4j candidate limits, actual keyword generation or answers.
On all 16 declared directed gold paths in this single-paper artifact, a
paired offline replay using gold-first-node anchors and benchmark-provided
`ll_keywords` finds 1 exact node sequence without the focus bonus and 2 with
it. The already-found gas/current/plating sequence remains; the additional
hit is the aging/resistance/heat chain. This is an oracle-aided diagnostic,
not an unbiased retrieval-quality estimate, and it does not measure
false-positive path precision.
The active aging benchmark supplies a gold intermediate as an `ll_keywords`
entry absent from the question in 14 of 15 directed cases. The benchmark
runner now reports `gold_intermediate_keyword_hints` for each directed case
and `cases_with_gold_intermediate_keywords` in the summary. Historical saved
results do not gain this field retroactively; their scores remain unchanged.
For an unbiased retrieval comparison, run a separate query-only setting where
intermediates are not manually supplied, while retaining the current
keyword-assisted setting as an explicitly labeled upper bound.

## Reproduce and finish attribution

Run the offline audit with the saved `benchmark_result.json` and
`extraction_artifact.json` from the *same* candidate:

```bash
python -m scripts.audit_aging_relations benchmark_result.json extraction_artifact.json
```

Before changing a prompt or re-extracting, obtain the corresponding live or
exported graph assertions, source chunks and raw model outputs. For each zero
check, record whether the fact is supported by the PDF, present in the raw
output, present after parsing, stored in the graph, and returned by retrieval.
Rerun the *same saved artifact* through old and updated benchmark/scorer, then
compare exact and semantic coverage with explicit denominators. Do not compare
the 40.7 Validation run directly to the later 49.9 run as a scorer-only delta:
their artifacts and scorer revisions differ.
