# Staging Preflight For Directed Retrieval Phase 0 And Phase 1

Use this runbook on the VPS before implementing Phase 0 and Phase 1 of directed multi-hop retrieval.

Goal:

- preserve the current staging state.
- version all non-secret code changes.
- back up staging configuration, prompts, WebUI bundle, `data-staging`, and Neo4j volume.
- avoid committing secrets such as `.env`, `.env.staging`, private keys, data directories, and backups.

## 1. Open VPS Shell

```bash
ssh root@72.61.153.229
cd ~/PEM-GraphRAG
```

## 2. Create Backup Folder

```bash
cd ~/PEM-GraphRAG

TS=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="$HOME/pem-graphrag-backups/staging-pre-directed-phase0-phase1-$TS"

mkdir -p "$BACKUP_DIR"
chmod 700 "$HOME/pem-graphrag-backups"
chmod 700 "$BACKUP_DIR"

echo "$TS" > "$BACKUP_DIR/timestamp.txt"
pwd > "$BACKUP_DIR/repo_path.txt"
```

## 3. Save Git And Docker State

```bash
git rev-parse HEAD > "$BACKUP_DIR/git-head.txt"
git branch --show-current > "$BACKUP_DIR/git-branch.txt"
git status --short > "$BACKUP_DIR/git-status-short.txt"
git log --oneline -20 > "$BACKUP_DIR/git-log-last-20.txt"
git diff > "$BACKUP_DIR/uncommitted-working-tree.patch"
git diff --cached > "$BACKUP_DIR/uncommitted-staged.patch"
git ls-files --others --exclude-standard > "$BACKUP_DIR/untracked-files.txt"
git bundle create "$BACKUP_DIR/repo-all-refs.bundle" --all

docker ps -a > "$BACKUP_DIR/docker-ps-a.txt"
docker compose \
  --project-name pem-staging \
  --env-file .env.staging \
  -f deploy/mcp/docker-compose.staging.yml \
  ps > "$BACKUP_DIR/docker-compose-staging-ps.txt"

docker compose \
  --project-name pem-staging \
  --env-file .env.staging \
  -f deploy/mcp/docker-compose.staging.yml \
  config > "$BACKUP_DIR/docker-compose-staging-config.rendered.yml"
```

## 4. Back Up Secret Config Locally On VPS Only

Do not commit these files.

```bash
cp .env.staging "$BACKUP_DIR/.env.staging.backup"
chmod 600 "$BACKUP_DIR/.env.staging.backup"

if [ -f .env ]; then
  cp .env "$BACKUP_DIR/.env.production.backup"
  chmod 600 "$BACKUP_DIR/.env.production.backup"
fi
```

## 5. Back Up Source Tree Without Secrets Or Data

```bash
tar \
  --exclude='.git' \
  --exclude='.env' \
  --exclude='.env.*' \
  --exclude='data' \
  --exclude='data-staging' \
  --exclude='backups' \
  --exclude='pkey' \
  --exclude='pkey.pub' \
  -czf "$BACKUP_DIR/worktree-no-secrets.tgz" \
  .
```

## 6. Back Up Staging Data Directories

These archives can be large.

```bash
if [ -d data-staging ]; then
  tar -czf "$BACKUP_DIR/data-staging-rag-storage.tgz" data-staging/rag_storage || true
  tar -czf "$BACKUP_DIR/data-staging-prompts.tgz" data-staging/prompts || true
  tar -czf "$BACKUP_DIR/data-staging-inputs.tgz" data-staging/inputs || true
fi
```

## 7. Back Up Staging WebUI Bundle From Container

```bash
mkdir -p "$BACKUP_DIR/container-webui"
docker cp pem-staging-lightrag-1:/app/lightrag/api/webui/. "$BACKUP_DIR/container-webui/"
```

## 8. Cold Back Up Staging Neo4j Volume

This briefly stops staging services. Production containers are not touched.

```bash
cd ~/PEM-GraphRAG

docker compose \
  --project-name pem-staging \
  --env-file .env.staging \
  -f deploy/mcp/docker-compose.staging.yml \
  stop oauth2-proxy mcp-gateway lightrag neo4j

docker run --rm \
  -v pem-staging_neo4j_data:/volume:ro \
  -v "$BACKUP_DIR":/backup \
  alpine \
  tar -czf /backup/neo4j-data-volume.tgz -C /volume .

docker compose \
  --project-name pem-staging \
  --env-file .env.staging \
  -f deploy/mcp/docker-compose.staging.yml \
  up -d neo4j ollama lightrag mcp-gateway oauth2-proxy
```

If the volume name differs, inspect it:

```bash
docker volume ls | grep -E 'pem-staging|neo4j'
```

Then replace `pem-staging_neo4j_data` in the backup command with the actual volume name.

## 9. Version Non-Secret Code Changes

Create a dedicated branch and commit only code/config templates/docs. Do not add `.env`, `data-staging`, `backups`, or private keys.

```bash
cd ~/PEM-GraphRAG

TS=$(cat "$BACKUP_DIR/timestamp.txt")
git switch -c "staging/pre-directed-phase0-phase1-$TS"

git add \
  docs \
  lightrag \
  lightrag_mcp \
  lightrag_webui \
  deploy/mcp \
  prompts \
  Dockerfile \
  Dockerfile.mcp \
  .gitignore

git diff --cached --name-only > "$BACKUP_DIR/git-staged-files.txt"

if grep -E '(^|/)(\.env|\.env\.staging|data-staging|data|backups|pkey|pkey\.pub|.*secret.*|.*private.*)' "$BACKUP_DIR/git-staged-files.txt"; then
  echo "Refusing to commit because staged files may contain secrets or data."
  exit 1
fi

git commit -m "Prepare staging for directed retrieval phase 0 and 1"
git tag -a "staging-pre-directed-phase0-phase1-$TS" -m "Backup point before directed retrieval phase 0 and 1"
```

Push the branch and tag if remote access is configured:

```bash
git push origin "staging/pre-directed-phase0-phase1-$TS"
git push origin "staging-pre-directed-phase0-phase1-$TS"
```

## 10. Verify Backup Integrity

```bash
cd "$BACKUP_DIR"

sha256sum *.tgz *.bundle *.patch *.txt *.yml 2>/dev/null > SHA256SUMS.txt
ls -lah

cd ~/PEM-GraphRAG
docker compose \
  --project-name pem-staging \
  --env-file .env.staging \
  -f deploy/mcp/docker-compose.staging.yml \
  ps
```

## 11. Smoke Test Staging

```bash
curl -k -i https://lightrag-staging.vmhnguyen.dev/webui/ | head -40
curl -i https://mcp-staging.vmhnguyen.dev/healthz
```

Expected:

- WebUI request redirects to Auth0 or returns WebUI HTML if already authenticated.
- MCP health returns `200 OK`.

## 12. Rollback Notes

Rollback code branch:

```bash
cd ~/PEM-GraphRAG
git switch main
git reset --hard staging-pre-directed-phase0-phase1-YYYYMMDD-HHMMSS
```

Restore WebUI bundle:

```bash
docker cp "$BACKUP_DIR/container-webui/." pem-staging-lightrag-1:/app/lightrag/api/webui/
docker restart pem-staging-lightrag-1
```

Restore Neo4j volume:

```bash
docker compose \
  --project-name pem-staging \
  --env-file .env.staging \
  -f deploy/mcp/docker-compose.staging.yml \
  stop oauth2-proxy mcp-gateway lightrag neo4j

docker run --rm \
  -v pem-staging_neo4j_data:/volume \
  -v "$BACKUP_DIR":/backup \
  alpine \
  sh -lc 'rm -rf /volume/* && tar -xzf /backup/neo4j-data-volume.tgz -C /volume'

docker compose \
  --project-name pem-staging \
  --env-file .env.staging \
  -f deploy/mcp/docker-compose.staging.yml \
  up -d neo4j ollama lightrag mcp-gateway oauth2-proxy
```

Only restore Neo4j if you intentionally want to discard all staging graph changes after the backup point.
