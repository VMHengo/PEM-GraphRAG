# Folder for User-Defined Prompts

This folder is designated for storing customized prompt templates created by users.

## PEM GraphRAG Entity Prompt

The PEM GraphRAG domain profile is available as:

- `prompts/samples/pem_graphrag_entity_type_prompt.sample.yml` for the versioned template.
- `prompts/entity_type/pem_graphrag_entity_type_prompt.yml` for local source runs with `PROMPT_DIR=./prompts` or unset.
- `data/prompts/entity_type/pem_graphrag_entity_type_prompt.yml` for Docker compose runs, because `docker-compose.yml` maps `./data/prompts` to `/app/data/prompts`.

Enable it with:

```env
ENTITY_TYPE_PROMPT_FILE=pem_graphrag_entity_type_prompt.yml
```

## Compact directed profiles for prompt comparison

Two versioned JSON-mode profiles are available under `prompts/samples/`:

- `pem_causal_evidence_compact.sample.yml`: strict evidence for causal and root-cause chains.
- `pem_process_chain_compact.sample.yml`: explicit manufacturing, material, and process order.

Copy them into the active `PROMPT_DIR/entity_type` directory without the
`.sample` segment in the filename. Local runs normally use
`prompts/entity_type/`; the production Docker Compose uses
`data/prompts/entity_type/` on the host. Staging can use a separate
`data-staging/prompts/entity_type/` mount; check its Compose volumes.
These runtime directories are ignored by Git. With
`ENTITY_EXTRACTION_USE_JSON=true`, the Evaluation prompt comparison lists
both profiles automatically. They contain one short example each and leave
the current active prompt unchanged until a final candidate is promoted.
