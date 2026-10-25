from lightrag_mcp.exploration import classify_domain, format_exploration


def _path(*, relation="causes", source_ids=("chunk-1", "chunk-2")):
    return {
        "nodes": ["Electrode Calendering", "Cathode Porosity", "Lithium Plating"],
        "edges": [
            {
                "source": "Electrode Calendering",
                "target": "Cathode Porosity",
                "relation_type": relation,
                "directionality": "directed",
                "source_ids": [source_ids[0]],
            },
            {
                "source": "Cathode Porosity",
                "target": "Lithium Plating",
                "relation_type": "leads_to",
                "directionality": "directed",
                "source_ids": [source_ids[1]],
            },
        ],
    }


def _payload(paths):
    return {
        "data": {
            "chunks": [
                {"chunk_id": "chunk-1", "file_path": "a.pdf", "content": "First passage"},
                {"chunk_id": "chunk-2", "file_path": "b.pdf", "content": "Second passage"},
            ],
            "references": [{"file_path": "a.pdf", "source_url": "https://example.org/a"}],
        },
        "metadata": {"directed_paths": {"status": "completed", "paths": paths}},
    }


def test_classify_domain_is_provisional_and_unknown_stays_unknown():
    assert classify_domain("Electrode Calendering") == "Fertigung"
    assert classify_domain("Cathode Porosity") == "Eigenschaften und Transport"
    assert classify_domain("Lithium Plating") == "Degradation und Alterung"
    assert classify_domain("Unmapped Technical Term") is None


def test_exploration_keeps_indirect_hops_and_each_source():
    result = format_exploration(_payload([_path()]), start="Electrode Calendering")
    assert len(result["connections"]) == 1
    connection = result["connections"][0]
    assert connection["status"] == "unreviewed_indirect_connection"
    assert connection["hops"] == 2
    assert connection["path"][0]["sources"][0]["chunk_excerpt"] == "First passage"
    assert connection["path"][0]["sources"][0]["url"] == "https://example.org/a"
    assert connection["path"][1]["sources"][0]["chunk_id"] == "chunk-2"


def test_exploration_rejects_unsupported_or_unresolved_edges():
    reversed_path = _path()
    reversed_path["edges"][0]["source"] = "Cathode Porosity"
    undirected_path = _path()
    undirected_path["edges"][0]["directionality"] = "undirected"
    result = format_exploration(
        _payload([
            _path(relation="does_not_cause"),
            _path(source_ids=("missing", "chunk-2")),
            reversed_path,
            undirected_path,
        ]),
        start="Electrode Calendering",
    )
    assert result["connections"] == []


def test_exploration_requires_exact_start_and_distinct_known_domains():
    payload = _payload([_path()])
    assert format_exploration(payload, start="Different Process")["connections"] == []
    same_domain = _path()
    same_domain["nodes"][-1] = "Electrode Drying Process"
    same_domain["edges"][-1]["target"] = "Electrode Drying Process"
    result = format_exploration(_payload([same_domain]), start="Electrode Calendering")
    assert result["connections"] == []


def test_exploration_deduplicates_targets_and_reports_missing_domain():
    result = format_exploration(
        _payload([_path(), _path()]), start="Electrode Calendering", limit=20
    )
    assert result["candidate_count"] == 1
    assert len(result["connections"]) == 1
    unknown = format_exploration(_payload([]), start="Unmapped Technical Term")
    assert unknown["empty_reason"] == "Starting node has no provisional subject classification."


def test_exploration_suggests_retrieved_node_names_for_retry():
    payload = _payload([])
    payload["data"]["entities"] = [{"entity_name": "Electrode Calendering"}]
    result = format_exploration(payload, start="Calendering")
    assert result["suggested_start_nodes"] == ["Electrode Calendering"]
