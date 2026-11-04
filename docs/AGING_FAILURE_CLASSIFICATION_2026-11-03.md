# Aging-Paper Failure Classification (offline, 2026-11-03)

## Scope

This audit compares the saved 2026-10-25 Validation result (scorer 2.1.0,
Overall 40.7) with its 224 parsed assertions and the local source PDF. It is
**not** an audit of the later 49.9 run or of the current Staging graph. The
31 zero-scored checks cover 29 distinct expected relations; two expectations
occur in two cases each. The PDF evidence anchors for all 16 affected cases
were located in the extracted paper text. Source page numbers below refer to
the PDF pages, not the journal's printed page labels.

The categories below are mutually exclusive *triage assignments per check*,
not a measurement of model accuracy:

| Category | Checks | Meaning |
| --- | ---: | --- |
| Reviewed gold representation mismatch | 2 | Correct `part_of` inverse was extracted but old gold accepted only `contains`. |
| Plausible alternative graph granularity | 4 | Related facts were extracted through different entities/predicates; equivalence needs review, not automatic full credit. |
| Missing state, intermediate, metric or signed observation in structured fields | 17 | The PDF supports a more specific fact than the traversable nodes and predicates retain; descriptions may still mention it. |
| Missing measurement/physical-meaning role | 6 | Method or resistance nodes exist, but the measured property or represented process relation is absent. |
| Sign-sensitive diffusion mechanism | 2 | One supporting relation was generalized and the other can invert the physical effect if its description is ignored. |

## Case-level attribution

| Case | Zero checks | PDF page | Parsed artifact versus gold | Next check |
| --- | ---: | ---: | --- | --- |
| `causal_drying_potential_current` | 2 | 8 | `Local Electrolyte Drying -> Nonuniform Local Current` skips the local-potential node, although its description mentions a potential change. | Check raw output for the potential-change node; retain the recharge condition. |
| `causal_plating_sei_resistance` | 1 | 4 | SEI-resistance node exists, but the `SEI Film Thickening -> SEI Film Resistance` link is absent. | Inspect chunk-003/006 and distinguish SEI presence from thickening. |
| `causal_plating_products_coating` | 2 | 8 | `Metallic Lithium -> Organic/Inorganic Lithium Salts -> White Substance -> Graphite Particles` is a longer, more specific candidate route than the two-hop gold. | Expert-review whether it supports the same coating conclusion; preserve its extra hops and conditions. |
| `causal_degradation_polarization_ic` | 1 | 8 | `Internal Polarization -> IC Curve` has a description that mentions the lower-voltage shift, but the target node loses it. | Check why the shift was not represented as a traversable state. |
| `causal_plating_inventory_ic_area` | 1 | 4 | Loss of lithium inventory is present, but the **reduction in IC area** is not represented. | Check the area/aging observation in raw output and parsed entities. |
| `causal_sei_active_material_ic` | 2 | 4 | The generic SEI-film edge description mentions thickening, but the node does not; the IC-area endpoint is absent. | Preserve *film thickening* and *area reduction* as distinct states. |
| `root_ic_shift` | 1 | 4 | Same missing lower-voltage shift as above; this is a repeated gold relation, not an independent failure. | Reuse the same root-cause evidence review. |
| `causal_diffusion_warburg` | 2 | 4 | `Aging --degrades--> Lithium Ion Diffusion` is a possible shorthand for harder diffusion. The next edge's description says *difficult* diffusion raises Warburg resistance, but its structured source is only `Lithium Ion Diffusion`. | Treat the structured path as a potential false causal bridge; do not award full credit for a generic diffusion-to-resistance edge. |
| `entities_cell_materials` | 3 | 2 | `Pouch Battery --uses--> NCM622/Graphite` is present, while `contains` is expected; the PP/PE/PP separator is absent. | Review `uses` versus component membership for two edges; audit the separator separately. |
| `entities_characterization` | 3 | 2-3 | SEM is abbreviated, while EDS/XPS are present but linked to instrument models rather than morphology/elements/composition. | Add reviewed SEM alias only; measure whether the actual property-role edges are extracted. |
| `entities_eis_roles` | 3 | 4 | EIS measurement edges exist, but the three resistance-to-physical-process `represents` links do not. | Compare raw chunk-002/003 output with the PDF's EIS definitions. |
| `relations_heat_decomposition` | 2 | 5 | Both inverse `part_of` assertions are present and source-supported. | Fixed in gold with explicit inverse; replay on the same frozen artifact only. |
| `observed_eds_anode` | 2 | 8 | Carbon decrease and oxygen increase in aged anode are not represented as signed observations. | Verify whether quantities/conditions were omitted in model output or parser. |
| `causal_gas_spacing_current_plating` | 2 | 8 | `Gas Generation -> Local Current Nonuniformity` skips the spacing-change node, although its description mentions electrode distance. | Check chunk-003/006 for the omitted intermediate; a shortcut should not pass an all-hops gold path. |
| `causal_consumption_drying_current` | 2 | 4, 8 | The same missing local-potential intermediate recurs in a longer drying chain. | Reuse the drying/potential audit; keep the subsequent-charging condition. |
| `synthesis_two_side_reaction_routes` | 2 | 8 | Decomposition products and lithium-electrolyte side reactions are discussed in the PDF but not preserved as the two expected adjacent assertions. | Check raw extraction before changing gold; direct `Lithium Plating -> SEI Film` is too coarse to substitute automatically. |

## Consequences

1. **Do not tune to Overall alone.** At least 2/31 zeros were a reviewed
   structural gold mismatch, whereas many others lose domain-critical
   intermediates, signs or experimental conditions.
2. **Do not accept all apparent synonyms.** `uses` versus `contains`, an
   aggregate reaction-products node versus organic/inorganic salts, and a
   generic `IC Curve` versus its lower-voltage shift need explicit, source-
   grounded equivalence decisions. A longer valid route may be preferable to
   inventing a direct edge.
3. **Prioritize extraction of states and role relations.** A targeted prompt
   variant should preserve changed quantity/state, direction of effect,
   physical-process meaning and passive measurement targets. Evaluate on
   frozen chunks and adversarial sign controls before any bulk ingestion.
4. **Separate retrieval.** In the saved `causal_aging_dc_heat` case, both
   required graph edges scored 100 but the directed path scored 0. The run's
   causal allowlist omitted `increases`; current code includes it. Offline
   artifact replay then found the first needed edge at rank 17 before a
   fanout of 10. A bounded exact focus-entity bonus recovers the path offline
   only when the benchmark supplies the gold intermediate as a keyword; a
   frozen-graph query-only Staging replay is still required.
5. **Separate text retention from graph reasoning.** Some critical qualifiers
   survived in edge descriptions but not in structured endpoints. A text-based
   answer may be adequate while a graph-only 4-5-hop traversal is still
   unsound. Evaluate those two uses separately.

## Remaining evidence

Parsed artifact presence proves only that a candidate survived extraction and
parsing, not that the live graph stored it or that the underlying claim is
true. Parsed absence cannot distinguish model omission from truncation,
malformed output, parser loss or a gold wording mismatch. Before assigning
those finer causes, inspect the same candidate's raw per-chunk responses,
current stored assertions, and the source PDF together. The historical
1,200-token Batch truncations concern a different ingestion run and must not
be transferred to this Validation run without matching request IDs.
