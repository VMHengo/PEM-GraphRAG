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
**not comparable to a full-document run**. The initial case-specific audit
reported these **alias-list matches**, not a semantic verdict:

| Case | v2 | v3 |
| --- | --- | --- |
| G01: drying to potential change | direct | alias-list miss |
| G02: potential change to nonuniform current | alias-list miss | alias-list miss |
| G03: gas to changed electrode spacing | alias-list miss | alias-list miss |
| G04: spacing change to nonuniform current | alias-list miss | alias-list miss |
| G05-G07: previously supported controls | direct | direct |
| R01: diffusion difficulty to Warburg resistance | alias-list miss | alias-list miss |
| R02: increased polarization to lower-voltage IC shift | related only | direct |

Inspection of the artifacts changes the interpretation: v2 contains `Local
Electrolyte Drying -> Local Potential Change -> Nonuniform Local Current`
and `Gas Generation -> Electrode Distance Change -> Local Current
Nonuniformity`. V3 contains both paths too, but in one chunk uses the more
generic `Local Potential` and `Electrode Distance` as intermediate nodes;
their edge descriptions explicitly say those quantities change. Both
profiles contain the spacing-change path in the other chunk.

The case-specific matcher omitted `influences`/`affects` for G02, `Electrode
Distance Change` for G03/G04, and `Local Potential` plus `changes` for v3
G01. These audit misses are mostly matcher false negatives, not missing
extracted paths. R01 is also present in both: v2 has `Lithium Ion Diffusion
Difficulty -> Increased Warburg Resistance`; v3 has `Increased Lithium-Ion
Diffusion Difficulty -> Warburg Resistance`. The matcher omitted these
signed variants. Whether generic state names deserve full or partial credit
remains a domain judgment. V2 has 65 node and 72 assertion records; v3 has
86 and 90. The larger output may add noise; counts alone do not measure
precision. Assertion records have source chunk IDs and descriptions but no
`evidence_quote` field, so this comparison does not independently verify
the exact PDF support for each edge.

The two reviewed reverse-causality controls matched no semantic assertions
in either candidate. This does not prove all other edges are correct.

## Corrected offline audit

The case-specific matcher now includes only the reviewed endpoint and
predicate alternatives found in these artifacts. Generic intermediate
nodes receive `state_in_description_only` rather than full direct credit
when the change appears in the relationship description. A two-hop chain
requires identical structured intermediate endpoints on both edges.

| Result on nine source-covered cases | v2 | v3 |
| --- | ---: | ---: |
| Direct single-edge matches | 8 | 7 |
| State only in description | 0 | 2 |
| Related only | 1 | 0 |
| Potential-to-current chain | direct | partial |
| Spacing-to-current chain | direct | direct |

This is an offline correction of the reviewed-case audit, **not** a change
to the live benchmark's scoring version or Overall score. The two artifact
files remain private and are not committed. The corrected audit prints the
matched source, predicate, target and source chunk for inspection.

## Decision

Do **not** promote v3 or re-extract the active document based on these scores.
The intended bridge paths exist in both artifacts, while v3's generic node
names and larger output need review. V2 itself varied from the prior day's
isolated run, illustrating extraction variance. First fix the case-specific
benchmark aliases and distinguish a well-named changed-state intermediate
from an unqualified quantity whose *description* carries the change. Then
review PDF spans and sample extra edges for precision before another paid
prompt test. Keep exact intermediate-chain success separate from broad
full-document scores.
