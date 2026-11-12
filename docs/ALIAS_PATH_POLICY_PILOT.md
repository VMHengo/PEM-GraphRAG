# Offline Alias Path Policy Pilot

This experiment does not write to Neo4j or change extraction, retrieval defaults,
benchmark scoring, or the WebUI. It compares two top-20 lists on one frozen
alias replay: the prior causal-first order and a versioned composition triage.
Neither list is verified evidence.

## Run

Create a bounded graph export and replay as documented in
`docs/OFFLINE_ALIAS_REPLAY.md`. Keep graph exports and comparison outputs
outside Git. From the repository root:

```powershell
python -m scripts.rank_alias_paths C:\path\to\alias-replay.json evaluation/aliases/path_policy_v1.json C:\path\to\comparison.json --review-markdown C:\path\to\comparison.md --limit 20 --pool-size 100
```

The JSON retains every original edge, document and source chunk, plus the
triage reason. A blocked pair is excluded from the proposed top list, not
deleted from the full candidate set. Unknown predicates or missing source
references remain visible as `needs_check`. Policy rules are explicit and
versioned in `evaluation/aliases/path_policy_v1.json`; changing that file
requires a new policy version for interpretable comparisons.

## Evaluation

Use the same frozen export and alias list for both lists. Randomize list order
for reviewers and conceal which method selected each path. Per path, judge:
original passage support of each hop, semantic identity of alias bridges,
condition compatibility, whether the endpoint statement actually follows,
and whether it is interesting across subject areas. Report supported and
composable precision at 20, source coverage, distinct endpoints and documents,
review burden, and latency. Do not infer population accuracy from the earlier
20-case targeted sample. Do not permit automatic causal assertions from a
passing type pair. Increase hop depth only after shorter paths pass review.

The policy uses coarse relation classes, not a complete formal logic. A
`produces -> measures` path is reviewable as a possible methodological link,
not proof that the start causes the target. Conditions, negation, source
validity and physical-versus-model quantities still require human checking.
