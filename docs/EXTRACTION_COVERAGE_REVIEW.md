# Extraction coverage review

This is an offline, read-only pilot for finding **omitted important assertions**
in one frozen extraction artifact. It neither modifies Neo4j nor makes LLM calls.
The current Aging pilot uses the isolated ten-chunk candidate from
`prompt_20261104_095538_c140dfe7`, not the active Staging graph.

## Review

Open the private HTML report in a browser. The center column shows extracted
text segmented into passages; a green rule means an assertion has a *candidate*
link to that passage. Click a passage to see its proposed relations on the right.
Candidate links (especially co-mentions) are not verified evidence; an unlinked
passage is not automatically an omission. Check the source PDF where text
extraction loses formulas, figures, sentence boundaries or context.

For each inspected passage, choose `No missing important relation`, `Missing
important relation`, or `Unclear`. For a missing relation, record the source,
predicate, target, importance and whether it is an omitted **intermediate step**;
multiple relations can be recorded in one passage. Use the note for conditions,
negation, direction or why an apparent gap is only a name variant. Export the
review JSON after each session; browser-local storage is only a convenience.
Do not put the HTML, PDF text or exported reviews in Git.

The report can be generated inside a Staging container from an isolated
`extraction_artifact.json` and retained `kv_store_text_chunks.json`:

```bash
python -m scripts.build_extraction_coverage_review \
  /path/to/extraction_artifact.json \
  /path/to/kv_store_text_chunks.json \
  /tmp/coverage-review.html
```

After exporting annotations, summarize them **locally** without uploading the
review or the private artifact:

```powershell
.venv\Scripts\python.exe -m scripts.summarize_extraction_coverage `
  "$env:TEMP\pem_aging_coverage_review.html" `
  "$HOME\Downloads\coverage-review-<fingerprint>.json"
```

The summary validates document ID, artifact fingerprint, segment IDs, verdicts
and complete missing triples. It counts reviewed versus unreviewed passages,
confirmed missing relations by importance, and missing intermediate steps.

## Quantitative follow-up

Do not divide missing relations by all text segments or treat candidate-link
coverage as extraction recall. For an omission estimate, preselect a random,
document-stratified sample of passages, annotate **all important source-supported
atomic relations** in each (including implicit intermediates), and compare each
against the frozen extraction with aliases and predicate equivalences reviewed.
Report true-positive, omitted, and ambiguous relations separately, with
per-document counts and uncertainty. Oversample unlinked passages for discovery,
but keep that targeted sample separate from the random estimate. A second
reviewer should resolve disputed causality, sign, negation and conditions.
