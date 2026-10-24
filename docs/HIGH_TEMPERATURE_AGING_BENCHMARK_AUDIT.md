# High-Temperature Aging Benchmark: Evidence Audit

Source: `test_documents/quality_docs/Heat Generation and Degradation Mechanism of Lithium-Ion Batteries during High-Temperature Aging.pdf` (DOI `10.1021/acsomega.2c04093`). Page numbers below are one-based physical PDF pages. The PDF SHA-256 matches the benchmark's `document_scope`. Each retained case has an evidence anchor on the stated page; the benchmark JSON carries the exact anchor and the relation-to-evidence mapping.

| Case ID | PDF page | Evidence and qualification |
| --- | ---: | --- |
| `causal_gas_current_plating` | 4 | Section 3.1: electrolyte decomposition generates gas; gas alters electrode distance, then local current and subsequent plating. The gas-to-current edge abbreviates the distance intermediate. |
| `root_plating_upstream` | 8 | Section 3.4: the same mechanism, read backward from plating; physical edges remain cause-to-effect. |
| `causal_drying_potential_current` | 8 | Section 3.4: drying changes local potential, followed by nonuniform current on recharge. |
| `causal_plating_sei_resistance` | 4 | Section 3.1: plated lithium reacts with electrolyte, thickens SEI, and increases film resistance; the reaction is an intermediate. |
| `causal_plating_products_coating` | 8 | Section 3.3: plated lithium reacts with electrolyte to form lithium salts that coat graphite. |
| `causal_metals_side_reactions_fade` | 8 | Sections 3.3-3.4: dissolved transition metals aggravate side reactions; side reactions contribute to fading. |
| `causal_degradation_polarization_ic` | 8 | Section 3.4: degradation causes severe polarization and a lower-voltage IC shift. |
| `causal_plating_inventory_ic_area` | 4 | Section 3.1: authors attribute inventory loss mainly to plating and smaller IC area partly to inventory loss. |
| `causal_sei_active_material_ic` | 4 | Section 3.1: SEI thickening and decomposition contribute to active-material loss; smaller IC area follows. |
| `causal_aging_dc_heat` | 8-9 | Section 3.4, across page break: degradation raises DC resistance, which increases irreversible heat on discharge. |
| `root_ic_shift` | 4 | Section 3.1: aging-related polarization explains the lower-voltage IC peaks. |
| `causal_diffusion_warburg` | 4 | Section 3.1: aging hinders solid-state lithium diffusion and raises Warburg resistance relative to fresh cells; Table 2 is not strictly increasing at every step. |
| `entities_cell_materials` | 2 | Experimental Section: pouch cell, NCM622 cathode, graphite anode, ceramic-coated PP/PE/PP separator. |
| `entities_electrolyte` | 2 | Experimental Section: LiPF6 plus EMC, EC, DEC, and PC solvents. |
| `entities_characterization` | 2-3 | Section 2.5 continuation: SEM morphology, EDS surface elements, XPS surface composition. |
| `entities_eis_roles` | 4 | Section 3.1, before Table 2: physical interpretations of Roh, RSEI, Rct, and Rw. |
| `protocol_temperatures` | 2 | Sections 2.1-2.3: 25 C calibration, 60 C cycling, 30 C initial ARC condition. |
| `protocol_capacity_cycling` | 2 | Table 1 and Section 2.1: currents, limits, rest steps, and 3 versus 20 cycles. |
| `protocol_eis` | 2 | Section 2.2: SOH checkpoints, charged state, AC amplitude, frequency range; electrochemical tests at 25 C. |
| `protocol_hppc` | 2-3 | Section 2.2 gives pulses and SOC steps; Section 3.1 defines mean charge/discharge pulse resistance. |
| `protocol_arc` | 2 | Sections 2.2-2.3: IC protocol differs from adiabatic discharge rates and initial temperature. |
| `protocol_postmortem` | 2, 7 | Section 2.5 specifies 100/90% SOH samples; Section 3.3 explains argon-filled disassembly. |
| `numeric_capacity_mass_soh` | 2-3 | Section 2 lists 4.2 Ah and about 63 g; Equation 1 defines SOH using actual and initial capacity. |
| `numeric_eis_table` | 4 | Table 2: all four resistance values at 100/95/90% SOH. |
| `boundary_rct_monotonic` | 4 | Table 2: Rct first falls then rises; Rw reaches a plateau. |
| `numeric_temperature_table` | 5 | Table 3: nine temperature rises across SOH and C-rate. |
| `synthesis_early_late_heating` | 5 | Section 3.2: early capacity loss lowers integrated rise; later heating-rate increase dominates. |
| `numeric_specific_heat` | 6 | Section 3.2: three SOH-specific Cp values and Equation 7. |
| `relations_heat_decomposition` | 5-6 | Equations 4-7: total, irreversible, and residual reversible heat; PDF text extraction splits formula glyphs. |
| `boundary_endothermic_heat` | 5, 7 | Equation 4 plus Section 3.2: endothermic contribution can offset irreversible heat. |
| `numeric_soc_resistance` | 3 | Section 3.1: resistance minimum near 40% SOC, not SOH. |
| `entities_xps_species` | 8 | Section 3.3: C 1s, O 1s, F 1s binding-energy assignments. |
| `observed_eds_anode` | 8 | Section 3.3: reduced surface carbon signal and increased oxygen signal on aged anode; not bulk carbon loss. |
| `boundary_cathode_not_unchanged` | 8 | Section 3.3: little cathode surface change, but transition metals detected on anode. |
| `observed_xps_organic_lif` | 8 | Section 3.3: larger organic proportion in aged SEI; LiF content not significantly changed. |
| `synthesis_two_side_reaction_routes` | 8 | Section 3.4: plating-mediated side reactions and decomposition products both contribute to SEI thickening. |
| `causal_gas_spacing_current_plating` | 8 | Section 3.4: explicit gas -> electrode distance -> recharge current -> plating sequence; added to avoid hiding the spacing intermediate. |
| `causal_consumption_drying_current` | 4, 8 | Section 3.1 links consumption to local drying; Section 3.4 links drying to potential and recharge-current nonuniformity. |

Removed `boundary_scope_and_gas`: its proposed gold answer depended on absence of gas-species, runaway-threshold, and cross-chemistry evidence. Pages 2 and 8 establish the studied cell and propose gas formation, but they cannot, by themselves, prove all three negative claims. The case also expected a `Thermal Runaway` graph entity not asserted as an experimental result.

## Interpretation limits

- The paper's gas/drying/plating sequence is an **authors' mechanistic interpretation**, not a separately manipulated gas or drying experiment. The benchmark must not treat it as direct experimental proof of each intervention.
- Some existing graph edges abbreviate an intermediate (especially gas -> current and plating -> SEI thickening). The two added cases expose the intervening nodes explicitly.
- `expected_answer` and `unacceptable_claims` document the gold answer, but the current automatic scorer does not fully grade numerical correctness or hallucination rejection from those fields. Empty `must_include` lists also mean answer-content checks are limited. Review answer quality separately from graph/path scores.
- Existing causal questions often do not match the current deterministic auto-router's narrow phrase rules. An `auto` routing failure on those questions can indicate a router limitation, not an unsupported scientific relation. Noncausal cases have no directed-path expectation and are excluded from directed-path scoring.
