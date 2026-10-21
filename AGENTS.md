# PEM GraphRAG Agent Guidelines

PEM GraphRAG is a LightRAG-based ingestion, knowledge-graph and retrieval
system with a FastAPI backend and React WebUI. Preserve existing user changes.

## Context Routing

- `.codex/PROJECT_MEMORY.md` is a short index of project-specific facts. Read
  only the section relevant to the task; source code and live configuration
  are authoritative. Do not load every linked document by default. Search
  with `rg` and read narrow file sections; cap log and JSON output.
- `docs/PROJECT_TODO.md` is the ordered implementation queue. For an explicit
  "next TODO step" request, use the `pem-next-todo` skill. Do not start the
  following item without a new request. Add new implementation plans there as
  small tasks with dependencies and acceptance checks.
- `docs/PEM-GRAPHRAG-IMPROVEMENT-ROADMAP.md` holds long-term product goals.
  Change those goals only on the user's explicit direction; ordinary plans
  and follow-ups belong in the TODO.

## Non-Negotiable Contracts

- Initialize and finalize LightRAG storages around use. Preserve the
  workspace-scoped pipeline locks and document reservation rules.
- Normal retrieval remains the default; directed retrieval is optional.
- Changing the embedding model requires rebuilding associated vectors.
- Keep secrets, `.env` files, backups, private documents and runtime data out
  of Git, memory and user-facing command examples.

## Implementation And Delivery

- Follow nearby code patterns. Use focused tests, mock remote services, and
  report checks actually run. Use Ruff for Python; Bun tests/lint/build for
  WebUI changes when applicable.
- Do not deploy, restart services or commit unless requested. For changes,
  give one `git add <path>` per changed file, commit/push commands, and
  relevant staging update commands separately; inspect untracked files before
  suggesting a pull. See `docs/STAGING_TO_PRODUCTION.md` for deployment.
- For substantial independent work, delegate bounded, disjoint tasks to
  `gpt-5.6-sol` at medium effort when available. The coordinator reviews all
  changes and owns final verification. Never claim an unavailable model ran.
