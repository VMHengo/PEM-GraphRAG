# Extraction Versioning And Prompt Comparison

## Purpose

The knowledge graph is derived from documents and chunks. This implementation
tracks which extraction configuration created each document's graph
contribution, without retaining complete historic graphs in `rag_storage`.

Git remains the source of truth for historic code and prompt files. Document
metadata and saved benchmark runs retain only the active version, fingerprint,
prompt profile, and optional Git commit for traceability.

## Active Extraction Revision

Configure the deployment with:

```env
EXTRACTION_ALGORITHM_VERSION=1.0.0
RELATION_SCHEMA_VERSION=1
EXTRACTION_GIT_COMMIT=
ENTITY_TYPE_PROMPT_FILE=pem_graphrag_entity_type_prompt.yml
```

`EXTRACTION_ALGORITHM_VERSION` is a human-managed semantic version. Increment
it when intentionally changing entity/relation prompts, ontology, parsing of
relations, or extraction semantics. `RELATION_SCHEMA_VERSION` is for changes
to stored relation fields or their meanings.

The system also calculates a SHA-256 fingerprint over the resolved prompt
profile, active model/binding, JSON extraction mode, extraction limits, and
the two versions. Therefore a changed prompt becomes visible as outdated even
when the semantic version was not bumped.

`EXTRACTION_GIT_COMMIT` is optional. Set it during a deployment to the commit
that contains the prompt and extraction implementation. It is displayed as
provenance only and must never contain secrets.

## Re-Extracting Documents

Open **Documents**, then choose **Re-extract outdated**. The dialog shows:

- eligible completed documents with retained chunks;
- documents matching the active fingerprint;
- outdated documents, including legacy documents with no stored revision;
- the active version, prompt profile, and short fingerprint.

The action only queues outdated completed documents. It does not delete or
re-upload documents. For every selected document it:

1. retains `full_docs`, original file information, `source_url`/`download_url`,
   chunks, and chunk embeddings;
2. removes only the document's current entity/relation contribution from the
   graph, rebuilding shared graph entries from other documents when needed;
3. runs extraction again against the existing chunks;
4. merges the regenerated graph contribution and stores the active revision.

The re-extraction job has the same exclusive maintenance reservation as a
delete operation. Wait for uploads, scans, or another pipeline job to finish.
The pipeline status dialog reports progress and supports the existing cancel
mechanism.

The API can select individual documents or force all retained-chunk documents:

```http
GET  /documents/extraction_revision
POST /documents/reextract
{
  "doc_ids": ["doc-..."],
  "outdated_only": true,
  "force": false
}
```

Leave `doc_ids` absent to consider all completed documents and failed documents
with retained chunks. `force: true` with
`outdated_only: false` is an intentional full refresh and should be used only
after a backup and a benchmark baseline.

## Prompt Experiment Workflow

1. Commit the current prompt/code and run a benchmark. Give the run a title
   such as `baseline prompt 1.0.0`.
2. Copy or edit a profile in `prompts/entity_type/` and commit the change.
3. Increase `EXTRACTION_ALGORITHM_VERSION` and optionally set
   `EXTRACTION_GIT_COMMIT` to that commit. Restart the API container.
4. Open **Documents** and run **Re-extract outdated**.
5. Run exactly the same benchmark, title it with the candidate profile/version,
   and add an explanatory note.
6. In **Evaluation**, open the candidate run and choose the baseline under
   **Prompt Comparison**. The view shows the stored revision and score deltas.

This creates a controlled sequential experiment: the same retained documents
and chunks are used, while the regenerated graph is evaluated after each
prompt revision. It does not preserve a second live graph. To return to an old
experiment, restore its Git commit, set the corresponding version/profile,
restart, re-extract, and rerun the benchmark.

## Batch Extraction

When Azure Batch extraction is imported, the imported document is also stamped
with the active extraction revision. Batch extraction is appropriate when the
document is currently chunk-only. The graph-only re-extract endpoint currently
uses the regular extraction path; it is designed for safely refreshing already
completed documents without reparsing or rechunking them.

## Verification

Run the focused tests locally:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/extraction/test_extraction_revisions.py `
  tests/evaluation/test_run_history_extraction_revision.py -q
```

Run `git diff --check` before committing. New extraction provenance is visible
in document metadata as `extraction_revision` and in Evaluation run history as
the **Extraction revision** column.
