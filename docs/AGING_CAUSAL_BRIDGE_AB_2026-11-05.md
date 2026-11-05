# Aging causal-bridge A/B (two chunks)

Staging experiment `prompt_20261105_090432_478efe01` compared the saved v2
intermediate-state profile with the new v3 causal-bridge profile. Both used
only chunks `003` and `006` of document
`doc-1c985b11ca48c9796d50febb7eaca9ea` in isolated, non-promotable
Validation mode. The active graph and prompt were not changed. The profiles
were checked by SHA-256 before the run; no Aging-paper answer phrases were
added as few-shot examples.

The preflight estimated four extraction calls and **$0.0515 for extraction
only**. Provider billing and benchmark-query cost were not measured. Both
candidates completed and saved two cache records each. This was one
stochastic run per profile, so the result is not a robust effect estimate.

| Metric | v2 | v3 |
| --- | ---: | ---: |
| Overall | 52.24 | 42.30 |
| Graph | 55.66 | 52.14 |
| Directed | 49.85 | 35.40 |
| Directed exact | 0.00 | 6.67 |
| Metadata | 99.42 | 99.77 |

These benchmark scores use full-document gold on only two chunks and are
**not comparable to a full-document run**. The reviewed, source-covered
relation audit is more diagnostic:

| Case | v2 | v3 |
| --- | --- | --- |
| G01: drying to potential change | direct | missing |
| G02: potential change to nonuniform current | missing | missing |
| G03: gas to changed electrode spacing | related shortcut only | missing |
| G04: spacing change to nonuniform current | related shortcut only | missing |
| G05-G07: previously supported controls | direct | direct |
| R01: diffusion difficulty to Warburg resistance | missing | missing |
| R02: increased polarization to lower-voltage IC shift | related only | direct |

The two reviewed reverse-causality controls matched no semantic assertions
in either candidate. This does not prove all other edges are correct.

## Decision

Do **not** promote v3 or re-extract the active document on this result. The
four intended bridge cases did not improve, and G01 regressed. V2 itself
varied from the prior day's isolated run, illustrating extraction variance.
Before another paid prompt iteration, inspect the two candidates' raw JSON
and source quotes for G01-G04 and consider a small, gold-separated extraction
test with several repeats. The benchmark should continue to report exact
intermediate-chain success separately from related shortcuts and broad
full-document scores.
