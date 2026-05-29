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
