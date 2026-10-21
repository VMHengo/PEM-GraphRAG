# PEM GraphRAG Improvement Roadmap

This roadmap collects potential improvements for the PEM GraphRAG system. It separates changes that improve the end-user answer quality from changes that improve developer/admin operation.

## Status Update: 2026-10-19

Reviewed against local commit `2b146577`; no new runtime inspection is implied.
The original feature proposals below remain useful background. Their wording
does not mean every item is still missing. The actionable quality plan is now
[Pipeline Research And Improvement Plan](PIPELINE_RESEARCH_AND_IMPROVEMENT_PLAN_2026-10.md),
including research through October 2026, optional pretrained models, prompt
reuse, effort estimates, and acceptance tests.

| Area | Verified code status | Remaining work |
| --- | --- | --- |
| Source/download URLs (1.4) | Editing, REST reference enrichment and MCP citation mapping implemented | Claim-level/page-level attribution and link availability checks |
| Directed retrieval | Optional normal/directed/combined/auto, bounded Neo4j BFS, citations | Predicate alignment, query relevance, assertion preservation; currently max 3 hops |
| WebUI batch controls (3.3) | Start/status/import and Advance All bulk operations; Batch JSON output validation and submission manifests implemented | Per-chunk retry and idempotent recovery after graph merge |
| Evaluation (3.5) | Versioned benchmarks, partial/exact scoring, saved runs and notes | Precision, claim/condition checks and controlled strategy answer comparisons |
| Prompt comparison | Isolated retained-chunk candidates, three cost modes and gated promotion implemented | Representative evidence-aware sampling, held-out evaluation, optional two-stage adapter |
| Re-extraction | Revision fingerprints, retained-document refresh and new Batch submission provenance implemented | Normal-provider completion provenance and complete assertion-level migration |
| Community reports | No Leiden/report retrieval in the reviewed query flow | Consider only if task-specific evaluation demonstrates a need |

Highest-priority findings: the normal extraction path still needs equivalent
completion validation; physical pair-based merge loses parallel assertions;
the causal allowlist omits some predicates emitted by the prompts. High
Metadata or keyword coverage does not demonstrate correct scientific answers.

## 1. User-Facing Quality Improvements

### 1.1 Domain-Specific Extraction Prompts

Improve the PEM entity extraction profile so that extracted entities and relations focus more strongly on PEM's target domains:

- battery production
- electromobility components
- electric motors
- energy systems
- PEM electrolysis
- recycling
- production engineering
- digital manufacturing
- chemistry/materials

Recommended changes:

- Add more real examples from PEM/VDMA publications.
- Define preferred relationship patterns, not only entity types.
- Avoid generic nodes such as `Process`, `System`, `Study`, or `Technology` unless they are part of a canonical term.
- Prefer domain-specific canonical names.
- Keep abbreviations as aliases unless the abbreviation is itself the common domain term.

Relevant files:

```text
prompts/entity_type/pem_graphrag_entity_type_prompt.yml
prompts/samples/pem_graphrag_entity_type_prompt.sample.yml
lightrag/prompt.py
lightrag/operate.py
```

Example desired extraction:

```text
Battery Cell Manufacturing --includes_process--> Electrode Drying
Laser-Based Drying --optimizes--> Electrode Drying
PEM RWTH Aachen --researches--> Battery Cell Manufacturing
Lithium Plating --degradation_mechanism_of--> Lithium-Ion Battery Cell
PEM Electrolyzer --used_for--> PEM Electrolysis
```

### 1.2 Language Normalization

The knowledge base may contain German and English documents. Without normalization, the graph can contain duplicate nodes:

```text
Lithium-Ionen-Batterie
Lithium-ion battery
LIB
Li-ion battery
Lithium-ion battery cell
```

Recommended policy:

- Use English canonical entity names.
- Preserve German terms in descriptions or alias metadata.
- Answer in the language of the user's query.
- Keep document titles in their original language.

Example:

```text
German source term: Lithium-Ionen-Batterie
Canonical entity: Lithium-Ion Battery
Description: German alias: Lithium-Ionen-Batterie; abbreviation: LIB.
```

This should improve cross-document retrieval, reduce duplicate graph nodes, and make ChatGPT answers more consistent.

### 1.3 Alias Mapping And Entity Deduplication

Add a domain alias layer to normalize important terms before or after extraction.

Possible file:

```text
prompts/domain_aliases/pem_aliases.yml
```

Example:

```yaml
canonical_entities:
  Lithium-Ion Battery:
    aliases:
      - Lithium-Ionen-Batterie
      - LIB
      - Li-ion battery
  PEM Electrolysis:
    aliases:
      - Proton Exchange Membrane Electrolysis
      - PEM water electrolysis
  Battery Cell Manufacturing:
    aliases:
      - Batteriezellfertigung
      - battery cell production
```

Implementation options:

- Prompt-only normalization.
- Postprocessing step after extraction.
- Periodic graph cleanup job.
- Manual admin review for high-value canonical entities.

### 1.4 Source Metadata And Download URLs

Implemented baseline: a user-editable source/download URL in the WebUI,
preserved during retained-chunk re-extraction and included in reference mapping.
The examples below describe its intended use and further metadata extensions.

Example URLs:

```text
https://arxiv.org/pdf/...
https://www.pem.rwth-aachen.de/...
https://internal-sharepoint.example.edu/...
```

Recommended document metadata fields:

```json
{
  "title": "Production Process of a Lithium-Ion Battery Cell",
  "authors": ["..."],
  "year": "2026",
  "source_url": "https://...",
  "download_url": "https://...",
  "publisher": "PEM RWTH Aachen",
  "document_type": "Technical Report"
}
```

The WebUI should allow admins to enter or edit this URL on a per-document basis.

Relevant areas:

```text
lightrag_webui/src/features/DocumentManager.tsx
lightrag_webui/src/api/lightrag.ts
lightrag/api/routers/document_routes.py
lightrag_mcp/
```

Expected user-facing behavior:

```text
Query:
Was sind die aktuellen verfügbaren Dokumente?

Answer:
**Verfügbare Dokumente**
Aktuell sind in der bereitgestellten Wissensbasis folgende Dokumente verfügbar:

**Production Process of a Lithium-Ion Battery Cell**
**Montageprozess eines Batteriepacks**
**Production of Lithium-Ion Battery Cell Components**
**Recycling of Lithium-Ion Batteries**
**Production Processes of Rotors**
**Production Process of a Continuous Hairpin Stator**

Einige dieser Publikationen gehören zur Reihe **Guide to Electric Motor Production**
bzw. zu den PEM/VDMA-Publikationen rund um Batterie- und E-Mobility-Produktion.
Außerdem ist für die elektrische Motorproduktion eine E-Mail-Adresse angegeben,
über die kostenlose Exemplare angefragt werden können:
**contactinfo@pem.rwth-aachen.de**.

**References**
[1] Production+Process+of+a+Lithium-Ion+Battery+Cell+(2026-03).pdf URL: {source_url_1}
[2] Flyer+Montage+Batteriepacks.pdf URL: {source_url_2}
[3] Komponentenherstellung+einer+Lithium-Ionen-Batteriezelle+2023+(ENG).pdf URL: {source_url_3}
[4] Recycling+von+Lithium-Ionen+Batterien+2023+(ENG).pdf URL: {source_url_4}
[5] Production+Processes+of+Rotors+(2024).pdf URL: {source_url_5}
```

This improves trust because users can verify the answer and download the cited documents directly.

### 1.5 Better Citation Output For ChatGPT

Improve MCP and LightRAG query responses so that references include:

- document title
- file name
- source/download URL
- page number, if available
- section heading, if available
- chunk excerpt
- reference ID

This should improve both the answer text and the ChatGPT "Sources" foldout.

Relevant areas:

```text
lightrag_mcp/server.py
lightrag_mcp/lightrag_client.py
lightrag/api/routers/query_routes.py
lightrag/operate.py
```

### 1.6 Embedding Model Evaluation

The current local embedding baseline is likely:

```env
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIM=768
```

Potential alternatives:

- `text-embedding-3-small`: good cloud baseline, comparatively cheap.
- `text-embedding-3-large`: stronger but more expensive.
- `bge-m3`: strong multilingual local embedding candidate.
- `multilingual-e5-large`: strong multilingual retrieval candidate.
- `jina-embeddings-v3`: multilingual candidate depending on deployment constraints.

Important rule:

If the embedding model changes, vector stores must be rebuilt. Old vectors are not compatible with the new embedding space.

Recommended evaluation:

- Keep a small fixed test set of queries.
- Compare retrieved chunks across embedding models.
- Track whether the expected source document appears in top-k.
- Compare German, English, and mixed-language queries.

### 1.7 Reranking

Add a reranker after initial vector/graph retrieval.

Why:

- The vector search may retrieve many similar scientific chunks.
- A reranker can improve the final context passed to the answer LLM.
- This can improve answer quality without changing the graph.

Candidates:

- local `bge-reranker`
- Jina reranker
- Cohere rerank
- Azure/OpenAI-compatible reranking option, if available

### 1.8 Section-Aware Chunking

Pure fixed-token chunking is robust but not ideal for scientific PDFs and technical reports.

Better chunking should preserve:

- title
- abstract
- section headings
- page references
- table context
- figure captions
- equation context

Relevant files:

```text
lightrag/chunker/
lightrag/operate.py
lightrag/pipeline.py
docs/ParagraphSemanticChunking.md
```

Expected benefit:

- Better entity/relation extraction.
- Better source references.
- Better retrieval for specific questions about methods, results, figures, and tables.

### 1.9 Query Prompt Improvements

Improve the final answer generation behavior:

- Answer in the language of the user's query.
- Use only retrieved evidence.
- State uncertainty clearly.
- Do not invent missing sources.
- Mention document titles and source URLs where available.
- Prefer concise but cited answers.
- Avoid immediate "No relevant context found" when weak evidence exists.

## 2. PDF, Formula, Image, And Figure Handling

### 2.1 Current Recognition Flow

For PDFs, mathematical formulas and figures are recognized by the configured parser. The relevant parser paths are:

```text
parse_mineru
parse_docling
analyze_multimodal
```

Relevant code:

```text
lightrag/pipeline.py
lightrag/parser/external/mineru/
lightrag/parser/external/docling/
lightrag/prompt_multimodal.py
lightrag/multimodal_context.py
```

Parser output can create sidecar files:

```text
*.drawings.json
*.tables.json
*.equations.json
*.blocks.jsonl
```

Typical flow:

```text
PDF
  -> MinerU or Docling
  -> structured blocks
  -> drawings/tables/equations sidecars
  -> optional VLM analysis
  -> enriched text chunks
  -> entity/relation extraction
```

### 2.2 Mathematical Formulas

Formulas are handled well only if the parser recognizes them as equations.

Expected sidecar:

```text
*.equations.json
```

Potential equation data:

- equation ID
- LaTeX representation
- caption
- surrounding text
- page or section, if available

Improvement options:

- Prefer MinerU/Docling over legacy parsing for formula-heavy PDFs.
- Add OCR/formula recognition where parser output is weak.
- Normalize formulas to LaTeX.
- Add a short natural-language explanation for formulas during multimodal analysis.
- Preserve the surrounding section and page metadata.
- Extract relationships between variables, concepts, and equations.

Example:

```text
Equation eq-001 describes the relationship between cell voltage, overpotential,
and internal resistance in the battery model.
```

### 2.3 Figures, Graphs, And Images

Figures are recognized when the parser emits image/drawing blocks.

Expected sidecar:

```text
*.drawings.json
```

Potential drawing data:

- image path
- caption
- footnote
- surrounding text
- page or section

The multimodal pipeline can pass images to a VLM for description.

Improvement options:

- Configure a vision-capable VLM for image analysis.
- Improve prompts for technical figure interpretation.
- Preserve figure captions and nearby paragraphs.
- Extract key trends from diagrams and plots.
- Keep figure IDs and page references in citations.
- Store figure descriptions as retrievable chunks.

Example extraction target:

```text
Figure 3 --shows--> Electrode Drying Energy Consumption
Laser-Based Drying --reduces--> Drying Time
```

### 2.4 Tables

Tables are often important for technical reports.

Expected sidecar:

```text
*.tables.json
```

Improvement options:

- Preserve table title, columns, units, and row semantics.
- Split very large tables row-wise instead of by raw tokens.
- Keep table captions in the chunk.
- Use a table-specific prompt for extraction.
- Keep page and section metadata.

### 2.5 Parser Debugging

Use the parser debug CLI to compare MinerU and Docling on the same PDF:

```bash
python -m lightrag.parser.cli ./inputs/sample.pdf --engine mineru --force-reparse
python -m lightrag.parser.cli ./inputs/sample.pdf --engine docling --force-reparse
```

Check whether the parser produces:

```text
*.drawings.json
*.tables.json
*.equations.json
*.blocks.jsonl
```

Relevant documentation:

```text
docs/ParserDebugCLI.md
docs/RoleSpecificLLMConfiguration.md
docs/ParagraphSemanticChunking.md
```

## 3. Developer And Admin Experience Improvements

### 3.1 Teams Batch Notification

Add a lightweight batch watcher that sends a Teams notification when Azure Batch jobs become:

- `completed`
- `failed`
- `expired`
- `cancelled`

Recommended first implementation:

- Teams webhook or Power Automate webhook.
- Poll `data/rag_storage/batch_jobs/*.json`.
- Refresh active jobs.
- Send one notification per terminal status.
- Mark job with `notified_at`.

### 3.2 Auto-Import Option

Add optional auto-import after Batch completion:

```env
AZURE_BATCH_AUTO_IMPORT=false
```

When enabled:

- Watcher detects completed batch.
- Calls `/documents/{doc_id}/batch_extraction/import`.
- Sends notification after import.

For production, keep this disabled until Batch output parsing is stable.

### 3.3 WebUI Batch Controls

Implemented controls cover Batch start/status/import, Advance All bulk
operations, and source URL editing. Remaining improvements are persistent
per-document/per-chunk error display, safe retries, and validated completion.
The checklist below describes baseline behavior already present in code:

- show current Batch status
- show error details
- show Batch ID
- show "Import results" button
- show "Retry Batch" button
- show source/download URL editor
- avoid relying on terminal commands for common operations

Relevant file:

```text
lightrag_webui/src/features/DocumentManager.tsx
```

### 3.4 Cost And Time Estimation

Improve pre-extraction estimates:

- use real token count per chunk
- read model price from config
- distinguish normal extraction from Batch extraction
- show estimated Batch discount
- show warning for large PDFs

### 3.5 Evaluation Set

Implemented baseline: JSON definitions under `evaluation/benchmarks/`, live
graph/retrieval/full modes, separate semantic/exact diagnostics, saved history,
and isolated prompt experiments. The earlier structure below is a historical
proposal, not the active definition directory. Next add claim correctness,
false-positive precision, conditions, and per-stage failure attribution.

Suggested structure:

```text
eval/
  queries.yml
  expected_sources.yml
  expected_entities.yml
```

Track:

- whether the expected source is retrieved
- whether the answer cites the right document
- whether key entities are found
- whether the answer language is correct
- whether the answer avoids unsupported claims

### 3.6 Deployment Reliability

Improve the staging-to-production process:

- avoid manual `docker cp` hotfixes where possible
- publish built images
- reduce VPS build disk pressure
- keep `.env` files out of Git
- automate smoke tests after deployment

Relevant runbook:

```text
docs/STAGING_TO_PRODUCTION.md
```

## 4. Recommended Priority Order

1. Reject incomplete extraction and freeze actual batch submission provenance.
2. Evaluate extraction precision/recall and answer claims independently of coverage.
3. Align predicate definitions, inverse rules, routing and evaluation.
4. Compare compact evidence/condition prompts, including a two-stage pilot.
5. Preserve parallel, source-specific assertions before interpreting long chains.
6. Improve query anchoring, bounded path reranking and nonredundant evidence.
7. Validate selected path IDs and grounded claims; pilot 4-5 hops separately.
8. Audit existing embedding prefixes/context handling, then compare new indexes.
9. Compare layout-aware parsing and section-aware chunks where evidence is lost.
10. Pilot GLiNER2 or a small reranker on a separate worker if gains justify it.
11. Consider GEPA after a held-out, scientifically reviewed benchmark exists.
12. Add notifications/auto-import only after import integrity is established;
    continue deployment isolation and resource controls.

