# Relation coverage baseline: frozen sample

Goal: estimate important, source-supported relations omitted by extraction,
without changing the scorer or paying for a second extraction first. Keep PDF
text, annotations and extraction artifacts outside Git.

## Sample frozen on 2026-11-06

Use `scripts/sample_relation_coverage.py` with seed `20261106`, 12 passages
per document and PDF pages 1-8. The three battery-domain PDFs are:

1. `Heat Generation and Degradation Mechanism of Lithium-Ion Batteries during High-Temperature Aging.pdf`
2. `Analysis of the heat generation of lithium-ion battery during charging and discharging considering different influencing factors.pdf`
3. `The Polarization and Heat Generation Characteristics of Lithium-Ion Battery with Electric-Thermal Coupled Modeling.pdf`

The first attempt used a finite-element calorimeter *cell* paper as document 3.
It was replaced before annotation because its primary subject is a calorimeter
cell, not a battery cell. Do not change this sample after seeing extraction
results. The PDF SHA-256, page, passage index and adjacent context are stored
in the private JSON output. The sampler's 80-800 character filter is only an
extraction convenience; figure/table captions, background citations and
incomplete OCR remain in the sample and must receive eligibility labels.

For a convenient local review, render the private sample as HTML:

```powershell
.venv\Scripts\python.exe -m scripts.render_relation_coverage_review `
  "$env:TEMP\pem_relation_coverage_sample.json" `
  "$env:TEMP\pem_relation_coverage_review.html" `
  --pdf-root test_documents/quality_docs
Start-Process "$env:TEMP\pem_relation_coverage_review.html"
```

The page shows each passage with adjacent context and a link to its PDF page.
Select `Ja`, `Nein` or `Unklar`; for `Ja`, add one or more atomic relations
with conditions and evidence. The form saves locally in the browser, but
**export the review JSON** before changing browsers or clearing storage.
Import accepts only reviews whose seed and PDF hashes match this sample.
The form does not query or change Neo4j.

## Annotation before matching

For every sampled passage, inspect neighboring context and the PDF page.
Record `eligible_fact` as `yes`, `no` or `unclear`, with a reason. Eligible:
an important, atomic and source-supported battery mechanism, condition,
measurement or process relation. Background claims attributed to other work
may be recorded but must be marked as such. Exclude pure references, layout
artifacts, isolated parameter values, general motivation and claims with an
unresolved referent. Do not infer a causal direction from correlation.

For each eligible passage, annotate every important atomic claim separately:
source concept, predicate, target concept, direction, sign, negation,
temperature/SOC/SOH/rate/material conditions, source page and exact supporting
span. Mark a required intermediate concept or condition explicitly. Use
`unknown` rather than inventing a value. A second reviewer should adjudicate
ambiguous claims and a subset of positives and negatives.

Only after freezing annotations compare with the **same document's** frozen
extraction artifact and an independently named active-graph snapshot. Label
each fact `exact`, `alias_or_equivalent`, `condition_lost`, `wrong_direction`,
`wrong_sign`, `only_elsewhere_in_graph`, `missing_entity`, `missing_edge`,
`parser_or_merge_loss`, or `unknown`. A relation found in another document does
not count as extracted from this paper. Preserve distinct fact-level and
document-level denominators; report both exact and semantically supported
recall, false additions, and counts of missing intermediate steps. Do not
turn 36 passages into an accuracy percentage before eligibility and gold facts
are finalized.

The Aging isolated artifact and its offline report are available locally for
an initial pilot. Matching artifacts for documents 2 and 3 have not yet been
verified locally. Until they are retrieved, the multi-document extraction
coverage estimate is **not available**.

### Initial Aging triage (single reviewer, not gold)

The 12 seeded Aging passages were inspected before any new extraction. Six
contain potentially important claims, three are ineligible for mechanism
coverage, and three need adjacent PDF context or have an unresolved referent.
The provisional claims below are paraphrases, not extracted PDF quotations.

| Page:passage | Decision | Provisional atomic claim or reason |
| --- | --- | --- |
| 001:006 | yes | Capacity degradation decreases temperature rise in early aging. |
| 001:008 | unclear | Contrasting temperature-rise claim; antecedent/conditions need review. |
| 001:013 | no | General motivation about electric vehicles. |
| 001:021 | yes, attributed | Higher temperature increases capacity degradation rate in cited work. |
| 001:030 | unclear | Prior-work result is truncated by PDF layout metadata. |
| 002:020 | no | Apparatus connection, not a target mechanism. |
| 003:008 | no | Test schedule; no target relation to score here. |
| 005:004 | unclear | The referent of "this phenomenon" needs preceding context. |
| 005:015 | yes | Further aging raises temperature-rise rate despite falling capacity. |
| 006:008 | yes | Midrange SOC has lower heat and lower temperature-rise rate; association, not automatically causation. |
| 008:006 | yes | Plated lithium reacts with electrolyte and forms lithium salts. |
| 008:039 | yes | Severe degradation increases DC resistance and AC impedance. |

This triage is neither independent adjudication nor an extraction-recall score.
The next reviewer should first verify page context and atomize the six positive
cases, then match those fixed facts against the same-document frozen artifact.

## Offline Aging comparison

The previously generated private Aging coverage HTML embeds parsed assertions
from one frozen, isolated extraction candidate. It is not the active graph and
does not include a complete isolated-node inventory. Compare only the reviewed
Aging passages against this same-document snapshot:

```powershell
.venv\Scripts\python.exe -m scripts.compare_relation_coverage `
  "$env:TEMP\pem_relation_coverage_sample.json" `
  "$HOME\Downloads\relation-coverage-review-20261106-gold-v1.json" `
  "$env:TEMP\pem_aging_coverage_review.html" `
  "$env:TEMP\pem_aging_offline_comparison.json" `
  --pdf 'test_documents/quality_docs/Heat Generation and Degradation Mechanism of Lithium-Ion Batteries during High-Temperature Aging.pdf'
```

The tool verifies sample seed, document names, PDF hashes and passage IDs,
then writes private JSON plus a Markdown review sheet. `exact_labels` means
only label agreement, not source or condition support. Semantic candidates,
predicate mismatches and lexical leads require expert adjudication.
`no_match_under_conservative_rules` is **not** proof that the relation or an
entity is absent; aliases, typos and compositional gold statements can defeat
the matcher. Do not report recall until the adjudicated gold, matched aliases,
condition rules and independent source review are fixed.

## Regeneration (local PowerShell)

```powershell
$pdfs = @(
  'test_documents/quality_docs/Heat Generation and Degradation Mechanism of Lithium-Ion Batteries during High-Temperature Aging.pdf',
  'test_documents/quality_docs/Analysis of the heat generation of lithium-ion battery during charging and discharging considering different influencing factors.pdf',
  'test_documents/quality_docs/The Polarization and Heat Generation Characteristics of Lithium-Ion Battery with Electric-Thermal Coupled Modeling.pdf'
)
.venv\Scripts\python.exe -m scripts.sample_relation_coverage `
  "$env:TEMP\pem_relation_coverage_sample.json" $pdfs `
  --seed 20261106 --per-document 12 --max-pages 8
```
