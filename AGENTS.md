# Repository Guidelines

## Project Memory

Read `.codex/PROJECT_MEMORY.md` before work involving architecture, pipeline
behaviour, deployment, evaluation, ontology integration, or delivery. Update it
after material changes. Keep secrets, tokens, private document content, and
environment values out of Git and the memory. Detailed procedures belong in
`docs/`.

## Implementation Queue

`docs/PROJECT_TODO.md` is the canonical ordered TODO list. When planning new
implementation work, add small actionable items there with a link to the
detailed plan, dependencies and acceptance checks. Update statuses and add
follow-ups as work completes. If the user says "Implementiere den naechsten
Schritt in der TODO", implement only the first unchecked, unblocked item in
that file, verify its acceptance checks, and update the TODO and Project
Memory when the project state changes. Do not infer a task from an older plan
when the queue gives a concrete next step.

## Roadmap Governance

`docs/PEM-GRAPHRAG-IMPROVEMENT-ROADMAP.md` is the long-term product goal;
read it before planning major pipeline or evaluation work. Align TODO tasks
and design choices with evidence-grounded battery-engineering multi-hop
retrieval, a market-ready product, ChatGPT access through MCP, and seamless
developer and user workflows. Change long-term roadmap goals
only deliberately: explicitly ask the user which goal to add or change and
why before editing them, unless the current user request already states the
specific goal. Record the decision in the roadmap. Put routine implementation
ideas and sequencing in `docs/PROJECT_TODO.md`, not in the goal statement.

## Project

PEM GraphRAG is a LightRAG-based document-ingestion and knowledge-graph system.
It extracts entities and relationships, stores graph and vector data, and
supports graph-aware retrieval through a FastAPI service and React WebUI.

Key locations:

- `lightrag/lightrag.py`: `LightRAG` orchestration.
- `lightrag/pipeline.py`: ingestion, parser dispatch, queue processing.
- `lightrag/operate.py`: extraction, graph merge, and retrieval context.
- `lightrag/base.py`: storage abstractions and query configuration.
- `lightrag/llm_roles.py`: role-specific LLM configuration.
- `lightrag/kg/`: graph, vector, KV, and document-status backends.
- `lightrag/parser/` and `lightrag/chunker/`: parsing and chunking.
- `lightrag/api/`: FastAPI routes and packaged WebUI.
- `lightrag_webui/`: React 19, TypeScript, Bun, Vite, Tailwind.
- `tests/`: pytest suite mirroring the backend structure.

## Core Contracts

- After constructing `LightRAG`, always call
  `await rag.initialize_storages()` before using it, and finalize storages when
  finished.
- Preserve the pipeline concurrency contract in `pipeline.py`: use the
  workspace-scoped `pipeline_status` lock for state changes. Do not bypass
  enqueue, scan, processing, or destructive-job reservations.
- The four storage concerns are KV, vectors, graph, and document status.
  Workspaces isolate their data; respect their backend-specific semantics.
- Changing the embedding model requires rebuilding the associated vector data;
  vectors from different embedding spaces must not be mixed.
- The public default retrieval remains normal retrieval. Directed retrieval is
  an optional extension and must not silently regress existing query modes.

## Development And Tests

Use the repository's existing patterns and focused tests. Mock remote services
in unit tests; do not require live Azure, Neo4j, or Ollama.

```bash
# Python setup
uv sync --extra test

# Focused backend test
./scripts/test.sh tests/<path>

# Python lint
ruff check <paths>

# WebUI
cd lightrag_webui
bun install --frozen-lockfile
bun test
bun run lint
bun run build
```

Use English for code comments and backend logs. Use type annotations, async
patterns, `lightrag.utils.logger`, and the established storage and API helpers.
Add a regression test for each bug fix. Run relevant checks and report what
actually passed or could not be run.

## Configuration And Deployment

- Environment configuration is based on `env.example`; do not commit `.env`
  files or secrets.
- Keep host-usable settings in `.env`; container-only hostnames and generated
  SSL paths belong in Compose/setup outputs.
- Prefer `make env-*` over calling setup scripts directly.
- Read the Project Memory and relevant deployment runbook before staging or
  production work. Do not deploy, restart services, or commit unless requested.

## Delivery

Preserve unrelated user changes. For a requested change, report changed files,
checks, residual risks, and provide the repository delivery commands described
in the Project Memory. Never include secrets, backups, data directories,
private keys, or generated runtime artefacts in Git commands.

## Multi-Agent Workflow

For substantial independent work, coordinate with `gpt-6-sol` at medium
reasoning and delegate bounded, disjoint scopes to `gpt-5.6-sol` at medium
reasoning. Define acceptance criteria, ownership, contracts, and checks before
delegation. The coordinator inspects all changes and owns final verification;
agent reports alone are not acceptance.

## Git-Versioning

After every code change, include file-specific git add commands, a commit and push command, optional PowerShell scp commands for changed runtime files, and the exact staging update commands. Never include unrelated or secret files.
