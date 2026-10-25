# Extraction Stress Benchmark

This is a synthetic diagnostic corpus, not published battery evidence. It is
designed to expose extraction failures before paying to re-extract larger PDFs.
The nine short TXT files in `test_documents/extraction_stress/` each target one
failure mode and should remain a single chunk per file. The gold fixture is
`evaluation/benchmarks/pem_extraction_stress_v1.json`.

| File | Main challenge |
| --- | --- |
| `01_aging_direction.txt` | Upstream-to-downstream direction and resistance/heat |
| `02_indirect_porosity.txt` | Demonstrative referring to reduced porosity |
| `03_ambiguous_this.txt` | Do not choose an unsupported antecedent |
| `04_heat_components.txt` | Sum/component relation is not a causal edge |
| `05_passive_methods.txt` | Measurement method is the semantic source |
| `06_negation_condition.txt` | Negation and a temperature-qualified effect |
| `07_background_attribution.txt` | Keep a cited study separate from this experiment |
| `08_four_hop_mechanism.txt` | Preserve four adjacent directed assertions |
| `09_signed_drying.txt` | Preserve the sign of an indirect effect |

## Run an isolated comparison

1. Deploy the new TXT files and benchmark JSON to Staging. The benchmark
   directory is a read-only bind mount when
   `deploy/mcp/compose.evaluation-benchmarks.yml` is active. A backend restart
   is not needed just to read a new JSON fixture. The case-title display change
   requires a new WebUI build.
2. Upload the nine TXT files in Documents and complete their normal initial
   extraction. Prompt Experiments currently requires completed documents with
   retained chunks. Verify each has one chunk. This initial extraction has a
   model cost and writes to the selected environment; use Staging only.
3. In Evaluation > Prompt Experiments, select only these nine documents and
   **PEM Extraction Stress: Direction and Evidence**. Start with one active
   prompt profile in Screening and calculate the estimate before starting.
   Screening has no continuation pass; all source texts fit within one chunk.
   Do not promote a Screening result.
4. The benchmark's questions are empty. The graph checks run, while QA queries
   and directed-path checks are skipped. Read each case's entity and relation
   checks, not just Overall. The four-hop case checks four extracted edges,
   **not** whether retrieval can find a four-hop path.
5. Run the forbidden-edge audit on the candidate's saved artifact:

   ```bash
   cd ~/PEM-GraphRAG
   python3 scripts/evaluate_extraction_stress.py \
     data-staging/rag_storage/prompt_experiments/EXPERIMENT_ID/candidates/CANDIDATE_ID/extraction_artifact.json
   ```

   The script reports exact/explicit-alias entity and relation coverage
   **within each selected document**, plus explicitly forbidden tuples. It
   does not grant the WebUI scorer's partial semantic credit. Zero forbidden
   violations is not full precision: other unsupported edges, conditional
   errors, and wrong entity types still need source review. It prints source
   chunk IDs for violations and exits with status 1 if any required exact
   positive is missing or a reviewed forbidden edge is found.

The repository's `/test_*` ignore rule also matches `test_documents/`.
Explicitly force-add each new TXT file when committing this fixture; do not
remove that broad ignore rule as part of this benchmark change.

## Interpretation and controls

- The Graph score is the average of expected-entity and expected-relation
  coverage. It does not penalize extra wrong edges; use the audit for the
  narrow negative controls and inspect the full artifact for other claims.
- Run all compared profiles against the same uploaded documents and selection
  mode. Keep the prompt and scorer revisions with results; repeated extractions
  can vary even with identical text.
- The evidence anchors are exact substrings of these authored TXT files. Gold
  edges are direct claims or narrowly stated compositional/measurement facts.
  Ambiguous `This` in case 03 is intentionally **not** resolved into a cause.
- The current WebUI runner scores graph cases against the whole candidate
  graph, not source-scoped edges. Shared concepts can therefore hide a miss
  in another document. The artifact audit is source-scoped for both positive
  exact coverage and forbidden tuples. Do not run this benchmark directly on
  a mixed production knowledge graph and interpret it as isolated extraction
  accuracy.
- None of these short TXT files tests PDF reading order. The original aging
  paper's retained chunks remain the control for formula corruption and
  table-interrupted SEM passages.
