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

For a graph relation, both endpoints form a hard semantic bound. The score is
the lower endpoint match multiplied by predicate compatibility and declared
directionality. A matching predicate therefore earns no credit when either
source or target is unrelated. Explicit aliases still receive full endpoint
credit; reviewed predicate alternatives may receive partial credit. The UI
labels a result **Exact**, **Partial**, or **Missing** and shows the matched
edge plus source, target, predicate, and direction components.

For a directed path, each expected edge is matched in order.  The score is:

| Component | Weight |
| --- | ---: |
| Endpoint-gated edge recall | 55% |
| Consecutive-hop continuity | 15% |
| Semantic edge orientation | 15% |
| Declared source document / citation coverage | 15% |

Continuity, orientation, citations, and routing qualify matching hops; they
cannot create credit without a matching hop. A path with no matching mechanism
scores zero. A two-hop prefix of a three-hop path can score at most 66.7%, and
a one-hop prefix at most 33.3%, before any evidence or routing deficiency.
Routing and path-provider status can reduce a path score by up to 15% at the
retrieval-strategy level; they cannot raise a missing path above zero.

Graph combines entity coverage and relation quality at equal weight. Each case
also derives required entities from relation endpoints and directed-path nodes,
so an omitted intermediate cannot disappear from Entity Coverage.

Metadata is a diagnostic and optional quality gate. It is excluded from
Overall because populated fields do not prove a scientifically correct claim.
The versioned Overall profiles are:

| Profile | Graph | Retrieval | Directed |
| --- | ---: | ---: | ---: |
| `graph_only` | 100% | - | - |
| `core` | 80% | 20% | - |
| `directed` | 35% | 15% | 50% |

Weights are rebalanced only across components that were actually evaluated.
Every new result stores its scoring version, profile, configured weights, and
effective weights. Historical results retain the calculation saved with them.

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

A benchmark may select an Overall profile or define its own positive weights:

```json
{
  "scoring": {"profile": "directed"}
}
```

```json
{
  "scoring": {
    "overall_weights": {"graph": 40, "retrieval": 10, "directed": 50}
  }
}
```

Use custom weights only when they are documented in the benchmark's notes and
kept fixed during a comparison series.

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
