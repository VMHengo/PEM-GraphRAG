# Graph Cypher Explorer

The Knowledge Graph view includes a developer-facing **Cypher Explorer**. Its
button is at the right side of the graph. It runs a limited read-only Cypher
query against the configured Neo4j instance and shows matching relations or
nodes in a drawer.

Click a returned relation to focus it in the current graph view. The relation
and its two endpoint nodes remain prominent; all other currently visible graph
elements are dimmed. The graph is not replaced or reduced. Click the eraser in
the drawer, press `Esc`, or click empty graph space to clear that focus.

## Access control

The endpoint remains protected by the existing LightRAG API authentication and
the WebUI's OAuth2 Proxy. To restrict it further, add this to the deployment
environment file:

```env
GRAPH_CYPHER_EXPLORER_ALLOWED_EMAILS=developer1@pem.rwth-aachen.de,developer2@pem.rwth-aachen.de
```

Only identities passed from OAuth2 Proxy in `X-Auth-Request-Email`,
`X-Forwarded-Email`, or `X-Forwarded-User` can then use the endpoint. Do not
publish LightRAG's internal API port directly to the internet; requests should
pass through the authenticated WebUI reverse proxy.

When the variable is empty or absent, every user who can access the protected
WebUI can use the explorer. Use an allowlist on staging and production when
Neo4j inspection is intended only for developers.

## Query contract

The API is `POST /graph/cypher/read`. The server accepts only one query that:

- starts with `MATCH` or `OPTIONAL MATCH`;
- includes `RETURN`;
- contains no write, administration, procedure, load, or multi-statement
  syntax;
- has at most 8,000 characters;
- returns at most 200 rows; and
- executes in a Neo4j read transaction with a five-second transaction timeout.

The server adds a `LIMIT` when omitted. A supplied `LIMIT` must be a literal
integer within the requested result cap. Neo4j credentials never leave the
server.

The UI's 100-row request limit is intentional: it keeps result tables useful
and avoids trying to render a complete large graph.

## Useful queries

All LightRAG relations are stored as physical `:DIRECTED` relationships. The
meaningful direction is in `semantic_src_id` and `semantic_tgt_id`; it is used
by the explorer when it presents a selected relation.

### Inspect directed causal relations

```cypher
MATCH (source)-[edge:DIRECTED]-(target)
WHERE edge.relation_type IN ['causes', 'influences', 'leads_to', 'results_in', 'affects']
RETURN source, edge, target
LIMIT 50
```

### Find a named entity

```cypher
MATCH (node)
WHERE toLower(node.entity_id) CONTAINS toLower('electrode')
RETURN node
LIMIT 50
```

### Inspect three-hop causal candidates

```cypher
MATCH (source)-[first:DIRECTED]-(middle)-[second:DIRECTED]-(target)
WHERE first.relation_type IN ['causes', 'influences', 'leads_to', 'results_in', 'affects']
  AND second.relation_type IN ['causes', 'influences', 'leads_to', 'results_in', 'affects']
RETURN source, first, middle, second, target
LIMIT 50
```

For data inspection, the physical Neo4j direction is not authoritative because
older data and the existing storage merge relation endpoints without a physical
arrow. Use the semantic direction metadata above or the directed retrieval
feature for causal interpretation.
