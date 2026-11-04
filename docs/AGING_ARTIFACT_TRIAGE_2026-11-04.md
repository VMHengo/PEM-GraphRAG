# Aging Extraction Artifact Triage (2026-11-04)

## Scope and provenance

This read-only audit uses the local source PDF in
`test_documents/quality_docs/Heat Generation and Degradation Mechanism of Lithium-Ion Batteries during High-Temperature Aging.pdf`,
the saved prompt-experiment files `benchmark_result.json` and
`extraction_artifact.json` (2026-10-24), and the later
`aging_validation_result.json` and `aging_validation_artifact.json`
(2026-10-25). The JSON files were supplied separately in the user's Downloads
folder; they are not committed or copied into the repository. Neither pair is
a raw model response or a snapshot of the live Neo4j graph.

Both artifacts cover the same document, ten chunk IDs and source fingerprint.
Both record `gpt-5.4-mini`, the same active profile, prompt SHA-256 and
extraction revision fingerprint, with ontology annotation disabled. They are
**different extraction runs** and should not be treated as an old/new prompt
ablation:

| Saved run | Parsed node records | Parsed relation records | Graph | Directed | Zero-scored relation checks |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2026-10-24 | 263 | 246 | 57.49 | 1.33 | 29 |
| 2026-10-25 Validation | 272 | 224 | 56.51 | 29.64 | 31 |

Both results report scorer `2.1.0`, but their run settings and query behavior
must also be compared before attributing the score change to extraction.
`relation_importance` and metadata coverage are not evidence of correctness.

## What can be classified now

The reproducible `scripts/audit_aging_relations.py` comparison of the later
result against its matching parsed artifact finds 31 zero-scored relation
checks: 23 lack at least one expected endpoint under the audit's 0.85 name
threshold; eight have both endpoints but lack the expected relation. These
are **candidate locations of loss or gold mismatch**, not 31 proven model
errors. The PDF-anchored manual review in
`AGING_FAILURE_CLASSIFICATION_2026-11-03.md` assigns the same 31 checks:

| PDF/graph interpretation | Checks | Concrete observation |
| --- | ---: | --- |
| Reviewed inverse gold mismatch | 2 | `Irreversible Heat -> part_of -> Total Heat` and the analogous reversible-heat assertion exist in chunk-004; old gold expected only the inverse `contains` form. |
| Plausible alternative granularity | 4 | Some mechanisms are represented by different or longer routes, or `uses` where gold asks for component membership. These require expert judgment, not automatic equivalence. |
| Missing structured state, intermediate, metric or sign | 17 | A condition or changed quantity survives in a description but not in a traversable endpoint; other endpoints are absent altogether. |
| Missing measurement/physical-meaning role | 6 | Method/resistance entities exist, but their link to the measured or represented property is missing. |
| Sign-sensitive diffusion | 2 | A generic diffusion node may change the physical meaning of a directed `increases` edge. |

The first table is a name/edge-presence audit. The second is a source-informed
interpretation. They are different classifications and their categories must
not be combined as if they measured the same thing.

## High-value exemplars from the later parsed artifact

| Case | Parsed evidence | Current interpretation |
| --- | --- | --- |
| `causal_drying_potential_current` | Chunk-006 stores `Local Electrolyte Drying -> leads_to -> Nonuniform Local Current`; its description says drying *changes local potential*. | The intermediate is only text, not a traversable `Local Potential Change` node. Check the raw chunk-006 answer to locate the loss stage. |
| `causal_degradation_polarization_ic` and `root_ic_shift` | Chunk-006 stores `Internal Polarization -> leads_to -> IC Curve`, described as shifting the curve toward lower voltage; chunk-000 has a similar assertion. | The lower-voltage state is present in prose but absent from the endpoint. The repeated gold check is one underlying issue, not two independent omissions. |
| `causal_gas_spacing_current_plating` | Chunks 003/006 store `Gas Generation -> leads_to -> Local Current Nonuniformity`; descriptions mention changed electrode distance. | The spacing change is not a graph node, so this shortcut cannot satisfy an all-intermediates path. |
| `causal_diffusion_warburg` | Chunk-003 stores `High-Temperature Aging -> degrades -> Lithium Ion Diffusion` and `Lithium Ion Diffusion -> increases -> Warburg Resistance`. The second description qualifies its source as *difficult* diffusion. | Read literally as structured triples, the second edge can invert the mechanism. This is a safety issue, not merely an alias mismatch. |
| `causal_sei_active_material_ic` | Chunk-003 stores `Solid Electrolyte Interphase Film -> causes -> Loss Of Active Materials`; the description specifies SEI-film *thickening*. | The changed state is missing in the source node. Do not conflate SEI presence with SEI thickening. |
| `entities_cell_materials` | Chunk-001 stores `Pouch Lithium-Ion Battery -> uses -> NCM622/Graphite`. | Battery/Cell naming is a possible alias; `uses` versus `contains` needs a reviewed component-role decision. |
| `entities_characterization` / `entities_eis_roles` | Chunk-002 stores EDS/XPS equipment links and EIS measurement links. | Instrument presence does not prove extraction of morphology, composition or physical-process interpretation. |

The PDF-anchored case review locates the associated source passages and page
numbers. The descriptions above are copied only as short audit cues, not as
verified quotes. A source-backed edge still needs a sentence-level entailment
check for direction, sign, condition and role.

## Still unknown and next evidence

1. **Model omission versus parser loss:** The saved artifacts contain parsed
   node/edge records, not the raw model JSON. Match each affected chunk ID to
   the corresponding Batch/experiment response and compare raw JSON with
   parsed records. Do not transfer the historical 1,200-token truncation
   finding to this run without matching request IDs.
2. **Parsed versus stored graph:** Query the matching experiment workspace or
   a frozen graph export for the listed assertions. The parsed artifact alone
   cannot prove Neo4j persisted them; the current staging graph may reflect a
   different ingestion revision.
3. **Graph-present versus retrieval miss:** Evaluate only gold paths for which
   every required assertion is actually in the same frozen graph. Report
   anchor, allowlist, fanout, ranking and citation failures separately. The
   known aging/DC-resistance path is an example of a possible retrieval miss,
   not an extraction failure.
4. **Benchmark correction:** Keep the reviewed inverse `part_of` acceptance;
   adjudicate `uses`/`contains`, aliases and extra intermediates against the
   source. Never award full credit for reversed causal direction or lost sign.

No new model calls, live graph queries, re-ingestion or benchmark changes were
made for this audit.

## Follow-up: raw-output availability and a small adjudication set

A read-only check of the 2026-10-25 Staging experiment workspace found
`kv_store_llm_response_cache.json` at two bytes (`{}`). The candidate directory
retains only `extraction_artifact.json` and `benchmark_result.json`; there is no
separately retained raw response there. This matches the default cleanup in
`lightrag/evaluation/prompt_experiments.py::_dispose_candidate`. It does **not**
prove that the provider never produced the missing fact. The separately
downloaded, completed ten-chunk Azure Batch pilot is a different run and must
not be matched record-for-record to this parsed experiment artifact.

The following ten *review units* are deliberately heterogeneous. They are
source-grounded adjudication decisions, not ten additional benchmark cases.
PDF pages count from the first page of the file; chunk IDs refer to the later
parsed artifact. `Accepted alternative` means the gold matcher may recognize
the alternative form. `Needs structure` means a description-only mention must
not receive full graph-path credit. A domain reviewer should confirm the
conditional/measurement interpretations before editing benchmark gold.

| # | Expected fact or relation | PDF | Later parsed artifact | Decision |
| ---: | --- | ---: | --- | --- |
| 1 | Total Heat contains Irreversible Heat | 5 | `Irreversible Heat -> part_of -> Total Heat`, chunk-004 | Accepted inverse; old zero is a gold/scorer mismatch. Current benchmark already lists this inverse. |
| 2 | Total Heat contains Reversible Heat | 5 | `Reversible Heat -> part_of -> Total Heat`, chunk-004 | Accepted inverse on the same basis. |
| 3 | Local Electrolyte Drying causes Local Potential Change | 8 | The local-potential change appears only inside the drying-to-current description, chunk-006. | Needs structure: the intervening state is not a node. |
| 4 | Local Potential Change contributes to nonuniform current on subsequent recharging | 8 | No potential-change endpoint; drying-to-current shortcut in chunk-006. | Source supports the *combined, conditioned mechanism*; do not assert an unconditional standalone effect without review. Needs structure and condition. |
| 5 | Gas Generation changes electrode spacing | 4, 8 | Spacing change appears inside gas-to-current descriptions, chunks 003/006. | Needs structure: `change` must retain its direction only if the PDF specifies one. |
| 6 | Changed electrode spacing contributes to Local Current Nonuniformity | 4, 8 | Gas-to-current shortcut, chunks 003/006. | Needs structure; the paper supports the mechanism in the subsequent-charging context. |
| 7 | Internal Polarization shifts the IC curve toward lower voltage | 4, 8 | `Internal Polarization -> leads_to -> IC Curve`, description specifies the lower-voltage shift, chunks 000/006. | Needs a shifted-peak/voltage state or qualified assertion; generic `IC Curve` is insufficient for exact path credit. |
| 8 | More difficult solid-state lithium diffusion increases Warburg resistance | 4 | `Lithium Ion Diffusion -> increases -> Warburg Resistance`, chunk-003, with *difficult* only in its description. | Sign-critical: the bare structured edge is potentially misleading. Do not count it as a safe equivalent. |
| 9 | Cell composition includes NCM622 in the cathode | 2 | `Pouch Lithium-Ion Battery -> uses -> NCM622`, chunk-001. | Partial at most. Cell/battery is a plausible alias, but `uses` is not automatically `contains`; prefer cathode/material roles. |
| 10 | SEM characterizes electrode morphology | 2 | SEM/method nodes or equipment links are present; the morphology-method relation is absent. | Missing measurement role. If a future model emits `SEM -> measures -> Morphology`, accept its inverse only after source and ontology review. |

The first two entries should not become two independent wins in a path-quality
metric merely because the same component pattern is repeated. Likewise, the
IC-shift expectation appears in multiple benchmark cases and should be
deduplicated when counting distinct extraction failures.

## Controlled A/B after this adjudication

1. Freeze the same document ID, all ten retained chunk IDs, source fingerprint,
   benchmark version, model/binding, chunking settings, scorer and retrieval
   settings. The 2026-10-24 and 2026-10-25 runs are not an A/B: they have the
   same prompt hash but different parsed outputs and possibly different run
   settings. A read-only 2026-11-04 Staging check found that the *currently*
   active prompt hashes to `c149a623ec855eb8a65a5362fdefeb5ba1dc2a0c12bb410cc3bcc71a7f49a497`,
   whereas both saved artifacts record
   `af926b59f7ff022de0be77cf6b8a9ee5bb09c58534f0c80dd952bc97130dbcee`.
   Therefore the saved 2026-10 runs cannot serve as an unchanged active-prompt
   baseline for a new A/B test. The currently active file must be snapshotted
   and tested alongside its new variant on the same retained chunks.
2. Compare the active prompt against **one** targeted variant that requires
   explicit changed-state, polarity, condition and evidence fields. Keep the
   normal extractor as a baseline; no live-document promotion in screening
   or validation mode. Account for the fact that those modes set gleaning to
   zero, unlike a possible final import.
3. Preserve raw finish reason, output-token count and raw JSON per chunk in a
   private, bounded artifact before candidate cleanup. Otherwise model omission
   cannot be distinguished from parser loss. Do not commit raw paper content
   or retain entire candidate workspaces by default on the storage-constrained
   VPS.
4. Report valid/completed chunks, exact and reviewed-semantic entity/edge
   recall, unsupported-edge rate, sign/condition errors, evidence coverage,
   fully supported 2-4-hop paths, tokens and estimated cost. Evaluate the ten
   units above separately from the existing benchmark Overall. Inspect
   disagreements against the PDF before changing gold or promoting a prompt.

## Isolated Staging A/B on 2026-11-04

The user separately authorized a paid, isolated Validation run after the
read-only audit. Experiment `prompt_20261104_095538_c140dfe7` compared a byte
snapshot of the then-active prompt (`pem_aging_baseline_20261104.yml`) with
`pem_aging_signed_states_v1.yml`. Both candidates used the same one document,
all ten retained chunk IDs and source/selected fingerprints, `gpt-5.4-mini`,
JSON extraction, zero gleaning, the same benchmark and scorer, and separate
disposable workspaces. Neither candidate was promoted or imported into the
active graph. The extraction-only estimate was $0.2378 for 20 calls; it does
not include any query/benchmark model cost or actual provider billing.

| Metric | Baseline | Signed-state variant |
| --- | ---: | ---: |
| Overall | 34.67 | 48.41 |
| Graph | 49.46 | 60.11 |
| Graph entity semantic / exact | 76.36 / 61.72 | 83.60 / 66.64 |
| Graph relation semantic / exact | 22.57 / 16.67 | 36.63 / 16.67 |
| Directed semantic / exact | 24.32 / 13.33 | 40.22 / 13.33 |
| Metadata | 98.78 | 99.65 |

Both ran 15 directed cases. The variant raised directed continuity and direction
accuracy from 33.33 to 60.00, but exact-path success remained 2/15. The
retrieval score is null in this Validation run: answer generation/quality was
not evaluated. Both candidates failed the benchmark's graph and directed
quality gates; the retrieval gate also fails because that score is absent, not
because an answer was judged incorrect.
This is one stochastic run per profile, not an estimate of variance or a
causal proof that the prompt alone accounts for every score change.

The largest directed-case gains were plating -> SEI -> resistance (0 -> 85),
plating -> lithium-inventory loss -> reduced IC area (0 -> 86.25), and SEI ->
active-material loss -> reduced IC area (0 -> 78.75). The metal-dissolution ->
side-reactions -> capacity-fade case *regressed* (81.5 -> 42.5), including a
singular/plural `Side Reaction` endpoint. Local drying -> potential change ->
current nonuniformity and diffusion difficulty -> Warburg resistance still
score zero; the former remains compressed into a direct drying-to-current edge.
The variant produced a more specific `IC Curve Shift Toward Lower Voltages`
endpoint but still misses its complete root-cause path. It also uses
`Pouch Lithium-Ion Battery -> uses -> Graphite` rather than a structural
component edge. These are not just harmless spelling differences.

In the *parsed* variant artifact, 196/244 edge records carry a nonempty
evidence field versus 0/247 in the baseline. This is quote availability, not
yet an exact-source or claim-support verdict; several newly scored edges still
lack a quote. The raw extraction-response cache was disabled by the candidate
configuration during this run. Its two snapshot attempts therefore reported
`unavailable`, and per-chunk finish reasons/output tokens were not retained.
The local code now enables candidate-only extraction caching for future runs,
but that change was not active during this experiment and must be checked in a
later *small* smoke test before claiming raw-output preservation works.

**Decision:** Do not promote the variant or re-extract the live document yet.
First adjudicate the changed assertions against the PDF (especially the
newly partial, quote-less claims and the regression), validate the remaining
zero-score chains and run a query-only evaluation without gold intermediate
keyword hints. The isolated comparison shows promise but not sufficient exact
or independently verified causal-path quality.
