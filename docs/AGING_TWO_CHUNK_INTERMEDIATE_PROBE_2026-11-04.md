# Aging intermediate-state probe (two retained chunks)

Experiment `prompt_20261104_114829_64a6cdd8` ran on **Staging only** after
explicit user approval. It selected only chunks `003` and `006` of
`doc-1c985b11ca48c9796d50febb7eaca9ea` in non-promotable Validation mode.
The active graph and active prompt were not changed. Baseline was the saved
active-prompt snapshot `pem_aging_baseline_20261104.yml`; the candidate was
`pem_aging_explicit_intermediates_v2.yml`. Both used the same selected/source
fingerprints. The estimate was four extraction calls and **$0.0488 for
extraction only**; actual provider billing and benchmark-query cost were not
measured. This is one stochastic run per profile.

The profile adds an unrelated fan/temperature/sensor example and explicit
instructions to preserve stated changed-state intermediates, signs and
conditions. It does not contain the aging-paper answers as examples. The
parser/merge regression tests show that a correctly emitted intermediate
chain, its direction, quote and condition-bearing description survive those
stages. These tests do not prove the model will emit that chain.

## Results

| Metric | Baseline | Candidate | Interpretation |
| --- | ---: | ---: | --- |
| Graph | 47.11 | 47.34 | Full-document gold on two chunks; not comparable with ten-chunk runs. |
| Directed | 32.14 | 37.60 | Same limitation. |
| Directed exact | 6.67 | 13.33 | Same limitation. |
| Reviewed, source-covered direct edges | 3/9 | 5/9 | Case-specific, structural matching only. |
| Reviewed, source-covered related-only edges | 2/9 | 4/9 | Shortcuts or generic states, not full path wins. |
| Reviewed, source-covered missing edges | 4/9 | 0/9 | A related shortcut is still not the required intermediate. |

The nine-case offline audit used the same reviewed alternatives for both
artifacts: `G01`–`G07`, `R01`, `R02`. `G05`–`G07` match directly in both.
`R01` becomes a direct match only after recognizing the source-supported,
case-specific alias `Lithium Ion Diffusion Difficulty In Active Material
Particles`; the candidate contains
`High-Temperature Aging -> causes -> Lithium Ion Diffusion Difficulty In
Active Material Particles -> increases -> Warburg Resistance`. `R02` gains
`Cell Degradation -> causes -> Severe Internal Polarization -> leads_to ->
IC Curve Shift Toward Lower Voltages`. Neither alias relaxes the requirement
for the correct sign or direction.

`G01`–`G04` remain **related-only** in the candidate: gas/drying-to-current
shortcuts exist but the potential-change and electrode-spacing states are not
structured. The raw-response cache confirms that `Potential` and `Spacing`
occur in model text for at least one chunk but not as entity or relationship
endpoints in either profile. This is model-output compression/selection in
these two chunks, **not a JSON parser loss**. The baseline also mentions
`Local Potential Change` in raw text without emitting it as an endpoint.

Two targeted reverse-causality controls (`Side Reactions -> Transition-Metal
Dissolution` and degraded performance -> high-temperature aging) found **zero
semantic** assertions in both artifacts. The misleading reverse-looking
merge log entries came from physical storage order; the audit checks
`semantic_src_id`/`semantic_tgt_id`. This does not certify that *all* other
candidate edges are correct.

Both candidate caches were saved before disposable workspace cleanup with
two records each and file mode `0600` (about 20–23 KB compressed). This
verifies the new candidate-only cache/snapshot path on Staging. It retains
response strings and prompts, not finish reasons or provider token usage.
Historic runs cannot be recovered this way.

## Decision

**Do not promote or re-extract the active document yet.** The candidate helps
two important chains but does not solve the gas/drying mechanism. The next
small extraction iteration should focus on multi-cause sentence decomposition
and an explicit no-sign `Electrode Spacing Change` / `Local Potential Change`
state without inventing an isolated causal effect. Keep the same two-chunk
probe and add a few reviewed negative controls; then repeat on the full ten
chunks only if this targeted result improves. A separate random sample of
predicted edges is still needed for precision.
