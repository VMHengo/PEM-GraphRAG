# Staging Graph Diagnostics Connector

This is a separate developer-only MCP endpoint. It does not change the normal
Staging or Production MCP tools. It has fixed, bounded Neo4j read queries, not
an arbitrary Cypher tool. Neo4j Community does not provide a database-enforced
reader role; `READ_ACCESS` is a routing hint, not an authorization boundary.
Keep this service off Production until the security review is complete.

## Auth0 prerequisite

The diagnostic API identifier must match `MCP_DIAGNOSTICS_AUDIENCE`. Enable
RBAC and "Add Permissions in the Access Token" for that API. Give
`read:graph-diagnostics` to a developer role and only authorized developer
users. A valid token without this permission must receive 403. The connector
uses the token's verified `permissions` claim, not an email address or a
client-provided role name.

## Staging configuration

Add only these non-secret values to the VPS `.env.staging`, after checking
whether they already exist:

```dotenv
MCP_DIAGNOSTICS_DOMAIN=mcp-debug-staging.example.edu
MCP_DIAGNOSTICS_AUDIENCE=https://mcp-debug-staging.example.edu
```

The staging file must already provide `AUTH0_DOMAIN`, `NEO4J_USERNAME`,
`NEO4J_PASSWORD`, and optionally `NEO4J_DATABASE`. Do not print the password.
Point the diagnostic domain's DNS record to the staging VPS. The overlay
attaches to the existing project network for `neo4j` and to the external
Traefik network. Confirm the external network name and TLS resolver against
the live staging Compose file before starting it. No Neo4j port is published.

## Deployment

Inspect `git status --short` on the VPS before pulling; preserve untracked
benchmarks and backups. After the code and overlay reach the VPS:

```bash
cd ~/PEM-GraphRAG
docker compose --project-name pem-staging --env-file .env.staging \
  -f deploy/mcp/docker-compose.staging.yml \
  -f deploy/mcp/compose.diagnostics-staging.yml \
  config --quiet
docker compose --project-name pem-staging --env-file .env.staging \
  -f deploy/mcp/docker-compose.staging.yml \
  -f deploy/mcp/compose.diagnostics-staging.yml \
  up -d --build --no-deps mcp-diagnostics
```

The overlay is separate so `up` does not rebuild LightRAG or the normal MCP
gateway. Confirm `mcp-diagnostics` is healthy and can reach Staging Neo4j.
The URL is `https://<MCP_DIAGNOSTICS_DOMAIN>/mcp/`.

## Acceptance checks

1. `GET /healthz` returns a minimal status. No document data is exposed.
2. The MCP endpoint without a bearer token returns 401.
3. A valid token for the diagnostic audience without
   `read:graph-diagnostics` returns 403.
4. A developer token with the permission can list only the three diagnostic
   tools and run each with bounded outputs. Verify returned paths include
   semantic source/target and source provenance.
5. A token for the regular Staging MCP audience returns 401, even if the user
   is a developer. Production is unchanged.
6. Connect the diagnostic endpoint as a separate ChatGPT connector only after
   these checks pass. Never paste bearer tokens or Neo4j credentials into a
   chat or commit them to Git.

If true read-only rights at the database layer or unrestricted Cypher are
required, move to a Neo4j edition with RBAC before expanding this interface.
