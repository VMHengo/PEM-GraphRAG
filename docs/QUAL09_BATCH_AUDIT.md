# Historic Azure Batch Completeness Audit

This is a read-only, offline inventory for QUAL-09. It does not call Azure,
import results, or decide whether graph facts are correct.

On Staging, keep downloaded output JSONL files outside Git. Name each file
`<output_file_id>.jsonl`, using the `output_file_id` recorded in its saved
`batch_jobs/<doc_id>.json`. Then run from the repository root:

```bash
python3 scripts/audit_azure_batch_completeness.py \
  data-staging/rag_storage/batch_jobs \
  --outputs-dir /path/to/downloaded-batch-outputs \
  --json > /path/to/private-batch-audit.json
```

The report records document ID, submission revision, requested output-token
budget, finish reasons, missing/invalid/duplicate outputs and artifact line
references. `repair_required=true` means a saved output exhibits an issue;
`null` means the output artifact was unavailable, **not** proof that extraction
was incomplete. Inspect the cited JSONL and source chunks before selecting a
document for the paid, reversible QUAL-10 pilot. Do not run Extract All from
this report alone.
