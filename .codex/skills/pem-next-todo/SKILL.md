---
name: pem-next-todo
description: Implement the next item in PEM GraphRAG's ordered TODO when the user asks for the next TODO step; not for unrelated feature requests.
---

# Next TODO Step

1. Read the Ordered Queue in `docs/PROJECT_TODO.md`. Select only the first
   unchecked, unblocked item. Read its linked plan and only the relevant
   section of `.codex/PROJECT_MEMORY.md`; inspect current code and prerequisites.
2. If already implemented, verify acceptance before marking it done and moving
   to the next item. If genuinely blocked, record the concrete reason in the
   TODO and select the next unblocked item. Do not guess past a blocker.
3. Implement one item, preserve unrelated changes and the existing retrieval
   baseline, run focused checks, then update TODO status, evidence and follow-up.
   Update Project Memory only when a durable fact changes.
4. Do not deploy to staging or production unless that TODO item explicitly
   includes deployment. Report residual risks and delivery commands separately.
