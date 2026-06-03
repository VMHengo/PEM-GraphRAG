# PEM GraphRAG MCP Gateway

This deployment exposes a read-only MCP server for ChatGPT Developer Mode.
The MCP gateway forwards `query_pem_graphrag` tool calls to the internal
LightRAG `/query` endpoint and returns answers with references.

## Files

- `docker-compose.vps.yml`: VPS stack with LightRAG, Neo4j, MCP gateway, and Caddy.
- `Caddyfile`: HTTPS reverse proxy for the public MCP endpoint.
- `env.example`: Required environment variables for the VPS.

## VPS Setup

1. Point DNS to the VPS:

   ```text
   mcp.example.edu A <your-vps-ip>
   ```

2. Copy `env.example` to `.env` at the repository root on the VPS and fill:

   ```env
   MCP_DOMAIN=mcp.example.edu
   AUTH0_DOMAIN=your-tenant.eu.auth0.com
   AUTH0_AUDIENCE=https://mcp.example.edu
   NEO4J_PASSWORD=change-this-password
   ```

3. Start the stack:

   ```bash
   docker compose -f deploy/mcp/docker-compose.vps.yml up -d --build
   ```

4. Pull the Ollama models used by LightRAG:

   ```bash
   docker compose -f deploy/mcp/docker-compose.vps.yml exec ollama ollama pull qwen2.5:7b
   docker compose -f deploy/mcp/docker-compose.vps.yml exec ollama ollama pull nomic-embed-text
   docker compose -f deploy/mcp/docker-compose.vps.yml restart lightrag
   ```

5. Check the public health endpoint:

   ```bash
   curl https://mcp.example.edu/healthz
   ```

## Auth0 Setup

Create an Auth0 API with:

```text
Identifier: https://mcp.example.edu
Signing Algorithm: RS256
```

Create an Auth0 application for ChatGPT OAuth. In ChatGPT Developer Mode,
use:

```text
Authorization URL: https://<AUTH0_DOMAIN>/authorize
Token URL: https://<AUTH0_DOMAIN>/oauth/token
Scope: openid profile email
Audience: https://mcp.example.edu
```

After ChatGPT shows the callback URL, add it to Auth0 Allowed Callback URLs.

## ChatGPT Setup

In ChatGPT Developer Mode, create a custom MCP app with:

```text
Server URL: https://mcp.example.edu/mcp
Authentication: OAuth
```

Scan tools. The first version intentionally exposes only:

```text
query_pem_graphrag(question, mode="mix")
```

Document ingestion remains an admin workflow through LightRAG WebUI/API.
