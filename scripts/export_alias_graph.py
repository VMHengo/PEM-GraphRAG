"""Export a bounded read-only Neo4j edge snapshot for offline alias replay."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from neo4j import GraphDatabase, READ_ACCESS


QUERY = """
MATCH (a)-[r]->(b)
WHERE r.directionality = 'directed'
  AND r.relation_type IS NOT NULL
RETURN elementId(r) AS id,
       coalesce(r.semantic_src_id, a.entity_id) AS semantic_src_id,
       coalesce(r.semantic_tgt_id, b.entity_id) AS semantic_tgt_id,
       r.directionality AS directionality,
       r.relation_type AS relation_type,
       r.source_id AS source_id,
       r.file_path AS file_path,
       r.description AS description
ORDER BY id
LIMIT $limit
"""


def export_snapshot(session, limit: int) -> dict:
    if not 1 <= limit <= 10000:
        raise ValueError("limit must be between 1 and 10000")
    rows = [dict(record) for record in session.run(QUERY, limit=limit + 1)]
    return {
        "truncated": len(rows) > limit,
        "edges": rows[:limit],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--limit", type=int, default=5000)
    args = parser.parse_args()
    uri = os.environ["NEO4J_URI"]
    username = os.environ["NEO4J_USERNAME"]
    password = os.environ["NEO4J_PASSWORD"]
    with GraphDatabase.driver(uri, auth=(username, password)) as driver:
        with driver.session(
            database=os.environ.get("NEO4J_DATABASE", "neo4j"),
            default_access_mode=READ_ACCESS,
        ) as session:
            snapshot = export_snapshot(session, args.limit)
    args.output.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Exported {len(snapshot['edges'])} edges; truncated={snapshot['truncated']}")


if __name__ == "__main__":
    main()
