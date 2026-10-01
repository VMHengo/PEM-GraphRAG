# Benchmark Scoring

The PEM benchmark runner deliberately reports two complementary views of graph
and directed-retrieval quality:

- **Semantic score:** a graded measurement for prompt screening and diagnosis.
  A partly correct, ordered, evidence-backed path receives partial credit.
- **Exact score:** a strict regression signal.  It only passes when the
  benchmark's reviewed nodes, predicate labels, orientation, and required
  citations all match.

`Directed` in the WebUI is the semantic score used by the Overall score.
`Directed Exact` is retained as a diagnostic and release-regression signal; it
does not lower Overall a second time.

## Score Components

For a graph relation, semantic scoring weights source match (50% together with
target), predicate compatibility (40%), and declared directionality (10%).
The UI labels a result **Exact**, **Partial**, or **Missing**.

For a directed path, each expected edge is matched in order.  The score is:

| Component | Weight |
| --- | ---: |
| Edge recall (endpoint and predicate match) | 55% |
| Consecutive-hop continuity | 15% |
| Semantic edge orientation | 15% |
| Declared source document / citation coverage | 15% |

Routing and path-provider status contribute a further 15% at the retrieval
strategy level.  Thus a useful two-hop prefix is visible as a partial result
instead of becoming indistinguishable from no path at all.

The Overall weighting when directed checks are present is Graph 35%, Metadata
10%, Retrieval 20%, and Directed semantic quality 35%.  If no directed checks
run, weights are rebalanced as before.

## Relation Ontology

The shared normalisation lives in
[`lightrag/relation_ontology.py`](../lightrag/relation_ontology.py).

- Surface aliases such as `cause` / `causes` are canonicalised.
- Unambiguous inverse labels such as `caused_by`, `affected_by`, and
  `influenced_by` are normalised during new extraction.  Their semantic source
  and target are swapped before directed traversal.
- Existing graph rows keep their stored semantic endpoints.  This avoids
  guessing the endpoint convention of legacy extraction data.
- Closely related predicates receive conservative partial credit.  For example
  `causes`, `leads_to`, and `results_in` form one family; `affects`,
  `influences`, and `degrades` form another.  Relations in different families
  score zero unless the benchmark explicitly accepts them.

Do not use aliases to hide a disputed scientific claim.  Add an explicit,
reviewed alternative to the benchmark instead.

## Benchmark Schema Extensions

Existing benchmark JSON remains valid.  A relation can now optionally declare:

```json
{
  "source": "Electrode coating",
  "source_aliases": ["Coating process"],
  "relation_type": "causes",
  "accepted_relation_types": {"leads_to": 0.9},
  "target": "Coating defect",
  "directionality": "directed"
}
```

`accepted_relation_types` may be a list (full credit for each listed canonical
predicate) or an object mapping predicate to a score from 0 to 1.

For an expected directed path, the same `accepted_relation_types` field can be
one shared list/object or an array with one item per hop.  `node_aliases` maps a
node index to accepted alternative names.  `path_requirement` is `all`
(default), `any`, or `at_least`; for `at_least`, set `min_matching_paths`.

## Benchmark Tiers

- `fixture`: small deterministic checks for code changes.
- `core`: reviewed, representative corpus checks suited to prompt comparison.
- `stress`: difficult multi-document chains.  Use it for investigation and
  regression coverage, not as the only basis for selecting a prompt.

The runner performs a document-scope preflight before a prompt experiment.  It
blocks the run when the selected documents do not cover the benchmark's
declared `document_scope`, `expected_documents`, or directed-path source files.
This avoids paying for comparisons that are guaranteed to fail due to a corpus
mismatch.

## Editing Checklist

1. Put new prompt-screening cases in a `core` benchmark and record their
   source document.
2. Add exact relation labels first; add aliases or alternatives only after
   manually reviewing the source sentence.
3. Keep strict quality gates for release regressions.  Prefer semantic score
   thresholds over `max_failed_checks: 0` for exploratory prompt comparison.
4. Use the per-strategy semantic and exact fields to distinguish a missing
   path, a routing problem, a reversed path, and a near-equivalent predicate.
