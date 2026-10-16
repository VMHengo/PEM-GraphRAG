# Quality Documents Benchmark

This suite is based on the ten actual PDFs in `test_documents/quality_docs`.
It separates extraction coverage from directed path retrieval, rather than
using a single difficult path score to judge every prompt change.

| Benchmark ID | Cases | Purpose |
| --- | ---: | --- |
| `pem_quality_docs_core` | 30 | Three cases per paper: extracted entities/relations, retrieved source coverage and scientific qualifications |
| `pem_quality_docs_multihop` | 18 | Twenty connected reference paths: two/three hops, five upstream queries and two cross-paper synthesis questions |

The JSON files are in [`evaluation/benchmarks`](../evaluation/benchmarks/).
They work with the existing Evaluation tab and prompt-experiment runner.
No changes to ingestion, extraction prompts or the benchmark engine are needed.

## Sources and Evidence

The core benchmark's `document_scope` records exact filenames, physical page
counts and SHA-256 fingerprints. Each expected relation links to one or more
`evidence_ids`. Each evidence entry provides a document ID, PDF page, section,
short text anchor and explanation of what that passage supports.

Page numbers are **one-based physical PDF pages**, including publisher and
ResearchGate covers. They are not journal page numbers. For example, the
generic-model paper starts on PDF page 2, and the thermal review's journal
page R1 is PDF page 2.

| Source ID | Paper | Core focus |
| --- | --- | --- |
| `thermal_review` | A Critical Review of Thermal Issues in Lithium-Ion Batteries | Separator failure; cold-charge plating and irreversible loss; SEI protection |
| `estimation_review` | Advancements in parameter estimation techniques for 1RC and 2RC equivalent circuit models... | HPPC heating bias; forgetting-factor tradeoff; model order and overfitting |
| `heat_factors` | Analysis of the heat generation...considering different influencing factors | Cold-operation resistance; current scaling; entropic heat sign |
| `generic_models` | An Overview of Generic Battery Models | Fitting measured data; voltage/SOC dependency; transient model selection |
| `model_comparison` | Critical comparison of equivalent circuit and physics-based models... | Calibration-domain limits; PBM cost; initialization-history fairness |
| `calorimeter` | Finite-Element Simulation for Thermal Modeling of a Cell in an Adiabatic Calorimeter | Fluid-vessel disambiguation; geometry and gradients; adiabatic shield |
| `aging` | Heat Generation and Degradation Mechanism...during High-Temperature Aging | Gas/current/plating mechanism; SEI impedance; early versus late aging |
| `mixing` | Heats of mixing and of entropy in porous insertion electrodes | Post-interruption heat; enthalpy limiting case; particle-transport exception |
| `coupled_model` | The Polarization and Heat Generation Characteristics... | Cold/high-rate polarization; relative entropy contribution; heat signs |
| `thermal_design` | Thermal modeling and design considerations of lithium-ion batteries | Heat-removal failure; cooling/Biot validity; state-dependent onset temperatures |

The calorimeter article is deliberately retained. Its "cell" is a vessel
containing test fluid, not a lithium-ion electrochemical cell. Confusing these
meanings is a meaningful domain-understanding failure.

These are source-audited reference representations, not an independently
expert-adjudicated gold standard. A supervisor should review the reference
answers before using results as a scientific claim. A review article's stated
mechanism also remains an attributed literature claim, not new experimental
verification by this project.

## Directed Cases

All arrows below show the **semantic cause/dependency direction**. For root
queries the expected `traversal_nodes` run in the opposite order. The benchmark
never changes the scientific direction to accommodate a reverse query.

| Case ID suffix after `mh_` | Reference mechanism | Evidence PDF pages |
| --- | --- | --- |
| `aging_gas_current_plating` | Electrolyte decomposition -> gas -> nonuniform current -> lithium plating on later charge | aging 4 |
| `root_plating_local_current` | Reverse-query partner of the preceding chain | aging 4 |
| `plating_sei_impedance` | Plated lithium -> SEI thickening -> SEI resistance | aging 4 |
| `aging_resistance_irreversible_heat` | High-temperature aging -> DC resistance -> irreversible discharge heat | aging 8-9 |
| `cold_resistance_joule_heat` | Operating temperature -> internal resistance -> Joule heat | heat_factors 3 |
| `root_joule_heat_cold` | Reverse-query partner of the preceding chain | heat_factors 3 |
| `cold_charge_capacity_loss` | Poor interfacial charge transfer -> plating -> irreversible capacity loss | thermal_review 6 |
| `separator_short_additional_heat` | Separator melting -> short circuit -> additional heating | thermal_review 5 |
| `heat_accumulation_hotspots` | Insufficient heat removal -> heat accumulation -> hot spots -> runaway risk | thermal_design 1 |
| `calorimeter_geometry_accuracy` | Vessel geometry -> internal gradients -> heat-capacity measurement accuracy | calorimeter 9-10 |
| `hppc_heat_parameter_state_error` | HPPC pulses -> heating -> parameter errors -> state-estimation quality | estimation_review 1, 7 |
| `root_hppc_state_error` | Reverse-query partner of the preceding chain | estimation_review 1, 7 |
| `soc_entropy_reversible_heat` | SOC -> reaction entropy -> reversible heat | mixing 1 |
| `coupled_temperature_resistance_heat` | Cell temperature -> ohmic resistance -> ohmic heat | coupled_model 10, 12 |
| `synthesis_heat_components` | Two branches: current -> ohmic heat -> total heat; SOC -> entropy -> reversible heat | coupled_model 20; mixing 1 |
| `synthesis_cold_vs_aged_root_heat` | Two incoming branches: cold operation and accumulated hot aging, each through resistance to heat | heat_factors 3; aging 8-9 |
| `generic_parameters_voltage_soc` | Fitted parameters -> voltage prediction -> SOC prediction | generic_models 2, 5 |
| `root_pbm_temperature_overprediction` | Excess resistance estimate -> excessive predicted heat -> temperature-trend deviation | model_comparison 11-12 |

The PBM explanation is explicitly tentative, following the authors' wording.
The gas chain allows additional electrode-spacing intermediates, and the
cold-charge chain allows an explicit electrolyte-reduction intermediate.
Missing an exact reference path can reflect a different valid graph granularity.
Partial scores and the actual returned paths must be inspected together.

Forward/reverse partner questions test traversal, not independent experiments.
They are correlated and must not be presented as independent accuracy samples.
The cross-paper questions require separately sourced branches; they do not
invent a causal edge joining unrelated experiments or require each individual
path to cite every paper.

## What Is Scored Automatically

The runner reads these existing fields:

- `expected_entities`: normalized name coverage.
- `expected_relations`: semantic endpoint/predicate/direction matches.
- `source_aliases`, `target_aliases`: explicitly accepted endpoint names.
- `accepted_relation_types`: full or weighted credit for reviewed alternatives.
- `must_include`: lexical terms in retrieved chunks or generated answers.
- `expected_documents`: source-reference coverage.
- `expected_directed_paths`: ordered path checks with partial credit,
  `node_aliases`, per-hop predicate alternatives and citations.

`evidence`, `expected_answer`, `unacceptable_claims`, source fingerprints and
explanatory metadata support auditing and human review. **They are not an
automatically executed factuality rubric.** In particular, the evaluator does
not reject an answer just because it asserts an `unacceptable_claims` item.

See [`BENCHMARK_SCORING.md`](BENCHMARK_SCORING.md) and
[`live_benchmark.py`](../lightrag/evaluation/live_benchmark.py) for the actual
score computation.

Important interpretation limits:

- Graph and directed scores are gold-coverage measures. They do not measure
  false-positive extraction precision over all graph edges.
- Correct endpoints, ordering and evidence receive partial credit despite
  predicate variation. Exact scores remain a separate diagnostic.
- Directionality and predicates such as `affects` do not encode whether an
  effect increases or decreases a quantity. Check sign in the description and
  answer. Aliases must not equate "error" with "accuracy" or "gradient" with
  "uniformity".
- The current graph scorer can award component points to a wrong relation;
  path scoring can award direction, continuity and citation points to a poorly
  matched path. Inspect endpoint/edge recall, not just the aggregate.
- Strict exact-path diagnostics use the older matching code; explicit aliases
  and weighted alternatives primarily benefit the semantic score.
- `must_include` is a lexical diagnostic. A paraphrase or translation can miss
  a term while being correct; an incorrect answer can still contain all terms.
- Current normal-query checks use the runner's default retrieval strategy.
  Directed/combined/auto checks run separately on context-only requests. A
  `full` run does not establish that every generated answer used the evaluated
  directed path context.
- `normal` passing its directed check means it correctly skipped traversal.
  It does not mean it found the expected causal chain.
- Metadata coverage is completeness, not correctness. In a mixed workspace it
  also includes graph edges outside this corpus.
- Graph matching is workspace-wide rather than document-filtered per edge.
  Use an isolated workspace/candidate corpus for controlled comparisons.

The numeric quality gates are provisional screening targets, not research
accuracy claims or validated production release thresholds. Calibrate them
after reviewing baseline runs. There is no `max_failed_checks: 0` requirement:
one spelling or predicate difference should not make an exploratory run useless.

## Human Review of Answer Quality

Use the JSON's reference answers and rejected claims for every generated answer.
For a focused audit, use these eight challenge prompts in addition to the live
scores. They deliberately test false premises and scientific qualification.

| ID | Prompt | What a good answer must establish |
| --- | --- | --- |
| H1 | Does the finite-element paper demonstrate that a spherical lithium-ion battery is safer than a cylindrical battery? | Reject the premise: it studies a fluid-filled calorimeter. Explain the actual gradient/measurement result. |
| H2 | Can we conclude that aging always increases total discharge heat? | Separate heat rate, integrated heat, duration and capacity; explain mild versus deep aging in the tested cells. |
| H3 | Is reversible entropy heat always positive during discharge? | Reject a universal sign; discuss SOC, chemistry, current convention and the studied end-of-discharge behavior. |
| H4 | If stronger cooling lowers average temperature, must it reduce the internal gradient? | Explain surface cooling, Biot number and the possibility of a cooler but less uniform cell. |
| H5 | An ECM passes WLTC. Can we deploy it for sustained fast charging without further validation? | Preserve calibration range, pulse duration, chemistry and ECM/PBM tradeoffs. |
| H6 | Should we always choose more RC branches and the smallest forgetting factor? | Explain model-order overfitting/complexity and tracking-versus-fluctuation tradeoffs; reject universal dominance. |
| H7 | At zero external current, does any measured heat prove continued Joule heating or a side reaction? | Explain concentration relaxation and mixing heat, enthalpy dependence, sign and its limiting case. |
| H8 | Do cold operation and high-temperature aging contradict one another as causes of higher resistance-related heat? | Separate present operating state from accumulated degradation; cite both sources and explain the shared resistance mechanism. |

For each answer, award 0, 1 or 2 points in each dimension:

| Dimension | 0 | 1 | 2 |
| --- | --- | --- | --- |
| Mechanism | Incorrect or disconnected topics | Useful but incomplete mechanism | Relevant intermediates and connected explanation |
| Direction and sign | Reversed cause or wrong trend | Correct direction with missing sign qualification | Correct direction, trend and heat/current convention where relevant |
| Conditions | Universalizes a conditional result | Retains some conditions | Retains decisive chemistry, state/history and protocol limits |
| Grounding | Missing/irrelevant sources | Partly grounded | Claims traceable to the appropriate passages; both papers for synthesis |
| Uncertainty and false premise | Accepts unsupported premise | Partial correction | Clearly corrects the premise and distinguishes evidence from interpretation |

Maximum: 10 per answer, 80 over H1-H8. Record the individual scores, run title,
notes and source version; do not average these human scores into the automated
Overall without documenting a new evaluation protocol. A fabricated central
mechanism should be flagged even if other dimensions earn points.

For multilingual robustness, repeat a root-cause question in German, for
example: "Woher kommt die erhoehte irreversible Waerme nach Hochtemperatur-
Alterung, und welche Rolle spielt der Gleichstromwiderstand?" Compare the
reasoning manually. The English `must_include` terms are not a multilingual
answer grader.

## Recommended Run Order

1. Finish importing all ten documents and verify that embeddings and the local
   model endpoint are healthy. A `completed` Azure batch alone does not mean
   the local graph and vector import completed.
2. Select **PEM Quality Papers - Extraction and Grounding**, mode `graph`.
   This makes no query/answer calls. Inspect missing and partial relations.
3. Run the same benchmark in `retrieval` mode. Check source references and
   retrieved content before spending tokens on full answers.
4. Select **PEM Quality Papers - Directed Mechanisms**, mode `retrieval`.
   Inspect per-strategy paths, source citations, orientation and routing.
5. Use `full` to inspect answers, then apply the human rubric. Save run titles
   such as `baseline - extraction 1.0.1 - complete corpus` and record prompt,
   model, extraction version, Git commit, retrieval settings and document IDs.
6. Compare prompts on the same fully extracted corpus, benchmark revision and
   retrieval budgets. Use at least repeated validation runs before concluding
   that a small score difference is meaningful.

Core retrieval performs 30 normal context requests; core full performs 30
answer requests. Multi-hop retrieval performs 18 normal context requests plus
72 context-only strategy requests. Multi-hop full generates 18 normal answers
and also runs those 72 context-only strategy requests. Explicit keyword lists
avoid the usual keyword-generation step, but embedding, retrieval and any
provider-dependent preprocessing still consume resources. Run serially on
the small VPS.

In Prompt Experiments select all ten relevant documents. Sampling may omit
evidence pages, so do not treat a screening run's absolute score as full-corpus
performance. Use a complete-chunk validation/final run for the actual decision.
Corpus preflight checks filenames, not whether all evidence chunks were sampled.

If graph relations exist but paths fail, inspect
[`adaptive_retrieval.py`](../lightrag/adaptive_retrieval.py). Its causal
allowlist currently excludes extracted types including `increases`, `reduces`,
`produces` and `contributes_to`, even when the semantic scorer accepts them.
Do not change gold scientific claims to conceal a retrieval-filter limitation.

## Local Checks

Run from the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/evaluation/test_quality_docs_benchmarks.py tests/evaluation/test_semantic_benchmark_matching.py -q
.\.venv\Scripts\python.exe -m ruff check tests/evaluation/test_quality_docs_benchmarks.py
git diff --check
```

The data tests check discovery/preflight, balanced source coverage, connected
and consistently oriented paths, current router bounds, accepted semantic
aliases, compatibility with the graph scorer, duplicate JSON keys, and actual
text anchors on the declared PDF pages. PDF audits also verify fingerprints;
they skip on machines without the local PDFs or `pypdf`. They make no paid API
calls and do not validate live extraction quality.

## Publish to Staging

Commit only the new files locally. Keep unrelated uncommitted work separate:

```bash
git add evaluation/benchmarks/pem_quality_docs_core.json
git add evaluation/benchmarks/pem_quality_docs_multihop.json
git add tests/evaluation/test_quality_docs_benchmarks.py
git add docs/QUALITY_DOCUMENTS_BENCHMARK.md
git commit -m "Add source-audited battery quality benchmarks"
git push origin feature/azure-batch-extraction
```

On the VPS, from the existing staging checkout on that branch:

```bash
cd ~/PEM-GraphRAG
git status --short
git branch --show-current
git pull --ff-only origin feature/azure-batch-extraction
```

With the existing benchmark bind mount active, refresh the benchmark list in
the Evaluation tab. Neither a WebUI build nor an image rebuild is required.
Confirm discovery from the actual running staging container:

```bash
docker compose \
  --project-name pem-staging \
  --env-file .env.staging \
  -f deploy/mcp/docker-compose.staging.yml \
  -f deploy/mcp/compose.evaluation-benchmarks.yml \
  exec -T lightrag python -c 'from lightrag.evaluation.live_benchmark import list_benchmarks; print([(b.id, b.case_count) for b in list_benchmarks() if b.id.startswith("pem_quality_docs_")])'
```

Expected IDs/counts: `pem_quality_docs_core: 30` and
`pem_quality_docs_multihop: 18`. If the mount is missing, enable it once:

```bash
docker compose \
  --project-name pem-staging \
  --env-file .env.staging \
  -f deploy/mcp/docker-compose.staging.yml \
  -f deploy/mcp/compose.evaluation-benchmarks.yml \
  up -d --no-deps --force-recreate lightrag
```

Wait for ongoing imports/experiments to finish before recreating the container.
The local PDFs are excluded by the repository's existing test-document ignore
rule; publishing benchmark JSON does not upload or ingest the papers.
