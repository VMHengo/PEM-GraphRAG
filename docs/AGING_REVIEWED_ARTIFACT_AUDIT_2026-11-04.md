# Reviewed aging relations: frozen-artifact audit

This offline audit applies the same reviewer-approved, case-specific
endpoint/predicate alternatives to both parsed artifacts. `Related only`
means a shortcut, generic state, or measurement-target mismatch; it
does **not** count as a complete multi-hop edge. PDF support was judged
by the human reviewer and is not inferred by this script. The audit
does not verify raw LLM output, final Neo4j merge, or answer quality.
The two candidates were run once each; stochastic extraction variance is not
measured by this paired comparison.

Document: `doc-1c985b11ca48c9796d50febb7eaca9ea`; frozen chunks: 10.

Original live-benchmark scores (context only; **not** rescored here):

| Metric | Baseline | Variant |
| --- | ---: | ---: |
| overall | 34.67 | 48.41 |
| graph | 49.46 | 60.11 |
| directed | 24.32 | 40.22 |
| directed_exact | 13.33 | 13.33 |

| Case | PDF review | Baseline graph | Variant graph | Diagnosis |
| --- | --- | --- | --- | --- |
| H01 | supported | related_only | related_only | generic_total_heat_alias_requires_review |
| H02 | supported | related_only | related_only | generic_total_heat_alias_requires_review |
| G01 | supported | related_only | related_only | potential_intermediate_omitted |
| G02 | supported_in_context | related_only | related_only | potential_intermediate_and_recharge_condition_omitted |
| G03 | supported_no_sign | related_only | related_only | spacing_intermediate_omitted |
| G04 | supported_in_context | related_only | related_only | spacing_intermediate_omitted |
| G05 | supported_with_eis_qualification | missing | direct_match | - |
| G06 | supported | missing | related_only | thickening_state_only_in_prose |
| G07 | supported | direct_match | direct_match | - |
| R01 | supported_signed | related_only | related_only | diffusion_difficulty_intermediate_omitted |
| R02 | supported_only_for_increased_polarization | related_only | related_only | increased_polarization_state_missing |
| R03 | supported | missing | direct_match | - |
| R04 | supported_under_adiabatic_discharge | related_only | direct_match | dc_increase_and_discharge_condition_missing |
| M01 | supported | direct_match | direct_match | - |
| M02 | supported | related_only | related_only | morphology_measurement_target_missing |

Baseline: {'related_only': 10, 'missing': 3, 'direct_match': 2}; variant: {'related_only': 10, 'direct_match': 5}.

A direct match is a structural match under the reviewed case-specific
aliases, **not** independent verification that the saved edge is true
or that its source quote supports it. Conditions and signs still need
manual inspection where they are stored only in prose.

## Interpretation and next decision

This is not evidence that the PDF gold is mostly wrong. Hoang confirmed the
source mechanisms, including the drying -> potential and gas -> spacing
intermediates. The ten `related_only` cases demonstrate why a correct shortcut
or generic endpoint is not the same as a traversable, signed mechanism.

- `G07` (`Side Reaction`/`Side Reactions`) is a safe *case-specific* alias. `M01`
  accepts `uses` for this tested cell/material statement, not as a global
  synonym for `contains`. Both already match directly in this offline audit.
- `H01/H02` remain ambiguous: the parsed artifacts say `Heat Generation`
  contains the components, whereas the reviewed claim names `Total Heat`.
  Do not grant full graph credit from that generic label without confirming
  that the entity denotes total generated heat in this context.
- `G01/G02` and `G03/G04` lack the potential and electrode-spacing intermediate
  endpoints in both artifacts. The shortcut edges remain useful for answer
  context but are insufficient for the reviewed explanatory paths.
- `G06`, `R01`, `R02` and `M02` lose a changed state or measurement target.
  In particular, `R02` requires **increased** polarization, not merely an
  unspecified polarization node. Do not relax these to full structural credit.
- The variant adds direct structural matches for `G05`, `R03` and `R04`.
  `R04` has no verbatim quote in its parsed record, so the PDF review and
  edge-level evidence-retention checks should stay separate.

**Priority:** First preserve explicit changed states (`Local Potential Change`,
`Electrode Spacing Change`, `Increased Diffusion Difficulty`, `Increased Internal
Polarization`) and source conditions in isolated extraction. Then rerun this
same audit and the existing directed-path benchmark. Keep benchmark aliases
case-specific; do not make `related_only` a full path win. A separate random
sample of *predicted* edges is still needed to estimate precision, because
these 15 cases were selected from previously disputed gold facts.
