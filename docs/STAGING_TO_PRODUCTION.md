# Staging To Production Promotion Runbook

This runbook describes how to promote the tested PEM GraphRAG staging version to production on the VPS.

The current deployment convention is:

- Staging Docker Compose project: `pem-staging`
- Staging env file: `.env.staging`
- Staging compose file: `deploy/mcp/docker-compose.staging.yml`
- Staging data directory: `data-staging/`
- Production Docker Compose project: `mcp`
- Production env file: `.env`
- Production compose file: `deploy/mcp/docker-compose.vps.yml`
- Production data directory: `data/`

Do not blindly copy `.env.staging` over `.env`. Production uses different domains, OAuth callback URLs, Auth0 audience values, cookies, and possibly API keys.

## 1. Decide What To Promote

Usually there are three separate things:

1. **Application code**
   - Python backend changes
   - MCP gateway changes
   - WebUI TypeScript/React changes
   - Compose template changes

2. **Configuration**
   - Azure/OpenAI model variables
   - Azure Batch variables
   - embedding variables
   - Auth/OAuth variables
   - domain variables

3. **Data**
   - uploaded documents
   - LightRAG file stores
   - Neo4j graph volume
   - vector stores

For most releases, promote **code** and carefully copy only selected **configuration**. Promote **data** only when you intentionally want production to receive staging test documents and graphs.

## 2. Verify Staging First

Run this on the VPS:

```bash
cd ~/PEM-GraphRAG

docker compose \
  --project-name pem-staging \
  --env-file .env.staging \
  -f deploy/mcp/docker-compose.staging.yml \
  ps
```

Check that `lightrag`, `mcp-gateway`, `neo4j`, and auth services are up.

Check the MCP health endpoint:

```bash
curl -i https://mcp-staging.vmhnguyen.dev/healthz
```

Check the LightRAG WebUI in the browser:

```text
https://lightrag-staging.vmhnguyen.dev
```

If you tested Azure Batch extraction, make sure the document status is imported:

```bash
DOC_ID="doc-id-here"

docker compose \
  --project-name pem-staging \
  --env-file .env.staging \
  -f deploy/mcp/docker-compose.staging.yml \
  exec -T mcp-gateway python - <<PY
import os, httpx, json

headers = {"X-API-Key": os.environ["LIGHTRAG_API_KEY"]}
doc_id = "$DOC_ID"

r = httpx.get(
    f"http://lightrag:9621/documents/{doc_id}/batch_extraction/status",
    headers=headers,
    timeout=60,
)

print(r.status_code)
print(json.dumps(r.json(), indent=2, ensure_ascii=False))
PY
```

Expected for a finished Batch extraction:

```json
{
  "status": "imported",
  "imported_at": "..."
}
```

## 3. Backup Production

Create a timestamped backup directory:

```bash
cd ~/PEM-GraphRAG

TS=$(date +%Y%m%d_%H%M%S)
mkdir -p backups/$TS
```

Backup production env files:

```bash
cp .env backups/$TS/.env.production.backup
cp deploy/mcp/docker-compose.vps.yml backups/$TS/docker-compose.vps.yml.backup
```

Backup production LightRAG data directories:

```bash
tar -czf backups/$TS/production-data.tar.gz data
```

Backup production Docker volumes, including Neo4j and Ollama:

```bash
docker run --rm \
  -v mcp_neo4j_data:/volume:ro \
  -v "$PWD/backups/$TS:/backup" \
  alpine tar -czf /backup/production-neo4j-volume.tar.gz -C /volume .

docker run --rm \
  -v mcp_ollama_data:/volume:ro \
  -v "$PWD/backups/$TS:/backup" \
  alpine tar -czf /backup/production-ollama-volume.tar.gz -C /volume .
```

If the volume names differ, list them first:

```bash
docker volume ls | grep mcp
```

## 4. Promote Code

Preferred path: use Git as the source of truth.

On your local machine or VPS, commit tested staging changes:

```bash
git status
git add docs lightrag lightrag_mcp lightrag_webui deploy/mcp Dockerfile Dockerfile.mcp
git commit -m "Promote staging changes"
git push
```

On the VPS, pull the latest code:

```bash
cd ~/PEM-GraphRAG
git pull --rebase origin main
```

If production must be updated without rebuilding images, copy changed source files into the running production containers as a temporary hotfix. Prefer a real image rebuild for durable deployments.

Example hotfix copy for the LightRAG backend:

```bash
docker cp lightrag/api/azure_batch.py mcp-lightrag-1:/app/lightrag/api/azure_batch.py
docker cp lightrag/api/routers/document_routes.py mcp-lightrag-1:/app/lightrag/api/routers/document_routes.py
docker restart mcp-lightrag-1
```

Example hotfix copy for the MCP gateway:

```bash
docker cp lightrag_mcp/. mcp-mcp-gateway-1:/app/lightrag_mcp/
docker restart mcp-mcp-gateway-1
```

## 5. Promote WebUI Changes

The WebUI is compiled from `lightrag_webui/src` into static assets under:

```text
lightrag/api/webui/
```

Build locally if Bun is not installed on the VPS:

```powershell
cd "C:\Users\vmhng\OneDrive\Dokumente\Studium\Semester\26SoSe\Hiwi\PEM-GraphRAG\lightrag_webui"
bun install --frozen-lockfile
bun run build
```

Copy the built assets to the VPS:

```powershell
cd "C:\Users\vmhng\OneDrive\Dokumente\Studium\Semester\26SoSe\Hiwi\PEM-GraphRAG"
scp -r .\lightrag\api\webui root@72.61.153.229:/root/PEM-GraphRAG/lightrag/api/
```

Copy them into the production container:

```bash
cd ~/PEM-GraphRAG

docker cp lightrag/api/webui/. mcp-lightrag-1:/app/lightrag/api/webui/
docker restart mcp-lightrag-1
```

Then hard-refresh the browser:

```text
Ctrl + F5
```

## 6. Promote Configuration Carefully

Compare staging and production env files without printing secrets in shared screenshots:

```bash
cd ~/PEM-GraphRAG
diff -u .env .env.staging
```

Copy only the intended feature variables from `.env.staging` to `.env`.

Common variables that may be promoted:

```env
ENTITY_EXTRACTION_USE_JSON=true
EXTRACT_MAX_ASYNC_LLM=1
MAX_ASYNC=1

AZURE_BATCH_ENABLED=true
AZURE_BATCH_BINDING_HOST=...
AZURE_BATCH_MODEL=...
AZURE_BATCH_ENDPOINT=/v1/responses
AZURE_BATCH_COMPLETION_WINDOW=24h
AZURE_BATCH_POLL_SECONDS=60
AZURE_BATCH_HTTP_TIMEOUT=600
AZURE_BATCH_MAX_OUTPUT_TOKENS=
```

Usually keep these production-specific and do not copy from staging:

```env
MCP_DOMAIN=...
LIGHTRAG_WEBUI_DOMAIN=...
AUTH0_AUDIENCE=...
OAUTH2_PROXY_CLIENT_ID=...
OAUTH2_PROXY_CLIENT_SECRET=...
OAUTH2_PROXY_COOKIE_SECRET=...
LIGHTRAG_API_KEY=...
NEO4J_PASSWORD=...
```

After editing `.env`, validate Compose interpolation:

```bash
docker compose \
  --project-name mcp \
  --env-file .env \
  -f deploy/mcp/docker-compose.vps.yml \
  config --quiet
```

## 7. Recreate Production Services

If you only changed env variables or copied hotfix files:

```bash
cd ~/PEM-GraphRAG

docker compose \
  --project-name mcp \
  --env-file .env \
  -f deploy/mcp/docker-compose.vps.yml \
  up -d --force-recreate --no-build lightrag mcp-gateway oauth2-proxy
```

If you changed Dockerfiles, dependencies, or want a durable image-based deploy:

```bash
docker compose \
  --project-name mcp \
  --env-file .env \
  -f deploy/mcp/docker-compose.vps.yml \
  up -d --build lightrag mcp-gateway oauth2-proxy
```

If disk space is low, avoid `--build` until you have cleaned Docker cache:

```bash
df -h
docker system df
docker builder prune -af
```

## 8. Optional: Promote Staging Data To Production

Only do this if you explicitly want production to contain staging documents and graphs.

Stop production first:

```bash
docker compose \
  --project-name mcp \
  --env-file .env \
  -f deploy/mcp/docker-compose.vps.yml \
  stop lightrag mcp-gateway neo4j
```

Copy LightRAG file stores:

```bash
rsync -a --delete data-staging/rag_storage/ data/rag_storage/
rsync -a --delete data-staging/inputs/ data/inputs/
rsync -a --delete data-staging/prompts/ data/prompts/
```

Copying Neo4j volume data is riskier than file stores. Prefer re-ingesting documents in production or exporting/importing through Neo4j tools. If you must copy the volume, do it only after confirming the volume names and after production is stopped.

Start production again:

```bash
docker compose \
  --project-name mcp \
  --env-file .env \
  -f deploy/mcp/docker-compose.vps.yml \
  up -d --no-build
```

## 9. Production Smoke Tests

Check container status:

```bash
docker compose \
  --project-name mcp \
  --env-file .env \
  -f deploy/mcp/docker-compose.vps.yml \
  ps
```

Check MCP health:

```bash
curl -i https://mcp.vmhnguyen.dev/healthz
```

Check LightRAG internally:

```bash
docker compose \
  --project-name mcp \
  --env-file .env \
  -f deploy/mcp/docker-compose.vps.yml \
  exec -T mcp-gateway python - <<PY
import httpx

r = httpx.get("http://lightrag:9621/health", timeout=20)
print(r.status_code)
print(r.text[:1000])
PY
```

Check a query through LightRAG:

```bash
docker compose \
  --project-name mcp \
  --env-file .env \
  -f deploy/mcp/docker-compose.vps.yml \
  exec -T mcp-gateway python - <<'PY'
import os, httpx, json

headers = {"X-API-Key": os.environ["LIGHTRAG_API_KEY"]}

r = httpx.post(
    "http://lightrag:9621/query",
    headers=headers,
    json={
        "query": "Welche Dokumente und Themen sind in der PEM GraphRAG Wissensbasis enthalten?",
        "mode": "mix",
        "stream": False,
        "include_references": True
    },
    timeout=300,
)

print(r.status_code)
print(json.dumps(r.json(), indent=2, ensure_ascii=False)[:6000])
PY
```

Check Neo4j contains nodes:

```bash
PASS=$(grep '^NEO4J_PASSWORD=' .env | cut -d= -f2- | tr -d '\r\n')

docker compose \
  --project-name mcp \
  --env-file .env \
  -f deploy/mcp/docker-compose.vps.yml \
  exec -T neo4j cypher-shell -u neo4j -p "$PASS" \
  "MATCH (n) RETURN count(n) AS nodes;"
```

## 10. Rollback

If production breaks after the release, first restore the previous code commit:

```bash
git log --oneline -5
git checkout <previous-good-commit>
```

Then recreate services:

```bash
docker compose \
  --project-name mcp \
  --env-file .env \
  -f deploy/mcp/docker-compose.vps.yml \
  up -d --force-recreate --no-build lightrag mcp-gateway oauth2-proxy
```

If the issue came from `.env`, restore the backup:

```bash
cp backups/<timestamp>/.env.production.backup .env
```

If the issue came from data, restore the data backup only after stopping production:

```bash
docker compose \
  --project-name mcp \
  --env-file .env \
  -f deploy/mcp/docker-compose.vps.yml \
  stop lightrag mcp-gateway neo4j

rm -rf data
tar -xzf backups/<timestamp>/production-data.tar.gz

docker compose \
  --project-name mcp \
  --env-file .env \
  -f deploy/mcp/docker-compose.vps.yml \
  up -d --no-build
```

## 11. Quick Checklist

- [ ] Staging tested through WebUI.
- [ ] Staging tested through MCP.
- [ ] Batch extraction tested if affected.
- [ ] Production `.env`, `data/`, and volumes backed up.
- [ ] Code committed and pulled on VPS.
- [ ] Production-specific env values preserved.
- [ ] Compose config validates with `config --quiet`.
- [ ] Production services recreated.
- [ ] WebUI hard-refreshed.
- [ ] MCP health check passes.
- [ ] LightRAG query passes.
- [ ] Neo4j node count looks sane.

