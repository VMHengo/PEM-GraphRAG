import asyncio
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

import lightrag.lightrag as lightrag_module
from lightrag.base import DocStatus, QueryParam
from lightrag.constants import GRAPH_FIELD_SEP
from lightrag.lightrag import LightRAG
from lightrag.operate import _get_edge_data, _merge_edges_then_upsert
from lightrag.ontology_annotation import _load_mapping
from lightrag.relation_assertions import (
    make_assertion_vdb_id,
    parse_relation_assertions,
    serialize_relation_assertions,
)
from lightrag.relation_identity import (
    make_directional_relation_chunk_key,
    make_directional_relation_vdb_id,
)
from lightrag.utils import (
    EmbeddingFunc,
    Tokenizer,
    make_relation_chunk_key,
    make_relation_vdb_ids,
)

pytestmark = pytest.mark.offline


class _Tokenizer:
    def encode(self, content: str) -> list[int]:
        return [ord(char) for char in content]

    def decode(self, tokens: list[int]) -> str:
        return "".join(chr(token) for token in tokens)


async def _embedding(texts: list[str]) -> np.ndarray:
    return np.ones((len(texts), 8), dtype=float)


async def _llm(*args, **kwargs) -> str:
    return "ok"


def _chunking(*args, **kwargs) -> list[dict]:
    return []


async def _build_rag(tmp_path, name: str, workspace: str | None = None) -> LightRAG:
    rag = LightRAG(
        working_dir=str(tmp_path / name),
        workspace=workspace or f"{name}_{uuid4().hex[:8]}",
        llm_model_func=_llm,
        embedding_func=EmbeddingFunc(
            embedding_dim=8,
            max_token_size=8192,
            func=_embedding,
        ),
        tokenizer=Tokenizer("test-tokenizer", _Tokenizer()),
        chunking_func=_chunking,
    )
    await rag.initialize_storages()
    return rag


def _assertion(source: str, target: str, predicate: str, chunk_id: str) -> dict:
    return {
        "semantic_src_id": source,
        "semantic_tgt_id": target,
        "relation_type": predicate,
        "directionality": "directed",
        "description": f"{source} {predicate} {target}",
        "keywords": predicate,
        "source_id": chunk_id,
        "file_path": f"{chunk_id}.txt",
        "weight": 1.0,
    }


async def _seed_relation_records(
    rag: LightRAG,
    source: str,
    target: str,
    assertions: list[dict],
    *,
    include_legacy: bool = True,
) -> tuple[list[str], list[str]]:
    chunk_ids = [assertion["source_id"] for assertion in assertions]
    chunk_keys = [
        make_directional_relation_chunk_key(source, target, assertion)
        for assertion in assertions
    ]
    vdb_ids = [
        make_directional_relation_vdb_id(source, target, assertion)
        for assertion in assertions
    ]
    assertion_ids = [
        make_assertion_vdb_id(source, target, assertion) for assertion in assertions
    ]

    relation_chunk_rows = {
        key: {"chunk_ids": chunk_ids, "count": len(chunk_ids)}
        for key in chunk_keys
    }
    if include_legacy:
        relation_chunk_rows[make_relation_chunk_key(source, target)] = {
            "chunk_ids": chunk_ids,
            "count": len(chunk_ids),
        }
    await rag.relation_chunks.upsert(relation_chunk_rows)

    vector_rows = {
        vdb_id: {
            "content": assertion["description"],
            "src_id": source,
            "tgt_id": target,
            "source_id": assertion["source_id"],
        }
        for vdb_id, assertion in zip(vdb_ids, assertions, strict=True)
    }
    vector_rows.update({
        assertion_id: {
            "content": assertion["description"],
            "src_id": source,
            "tgt_id": target,
            "source_id": assertion["source_id"],
            "assertion_id": assertion_id,
        }
        for assertion_id, assertion in zip(assertion_ids, assertions, strict=True)
    })
    if include_legacy:
        for legacy_id in make_relation_vdb_ids(source, target):
            vector_rows[legacy_id] = {
                "content": "legacy relation",
                "src_id": source,
                "tgt_id": target,
                "source_id": GRAPH_FIELD_SEP.join(chunk_ids),
            }
    await rag.relationships_vdb.upsert(vector_rows)
    return chunk_keys, vdb_ids + assertion_ids


async def _seed_edge(
    rag: LightRAG,
    source: str,
    target: str,
    assertions: list[dict],
    *,
    with_assertions: bool = True,
) -> None:
    edge = {
        "source": source,
        "target": target,
        "source_id": GRAPH_FIELD_SEP.join(
            assertion["source_id"] for assertion in assertions
        ),
        "description": " relation ".join(
            assertion["description"] for assertion in assertions
        ),
        "keywords": ",".join(assertion["keywords"] for assertion in assertions),
        "relation_type": assertions[0]["relation_type"],
        "directionality": assertions[0]["directionality"],
        "semantic_src_id": assertions[0]["semantic_src_id"],
        "semantic_tgt_id": assertions[0]["semantic_tgt_id"],
        "weight": float(len(assertions)),
        "file_path": GRAPH_FIELD_SEP.join(
            assertion["file_path"] for assertion in assertions
        ),
    }
    if with_assertions:
        edge["relation_assertions_json"] = serialize_relation_assertions(
            assertions, source, target
        )
    await rag.chunk_entity_relation_graph.upsert_edge(source, target, edge)


async def _assert_records_absent(rag: LightRAG, ids: list[str], keys: list[str]):
    vector_records = await asyncio.gather(
        *(rag.relationships_vdb.get_by_id(item) for item in ids)
    )
    chunk_records = await asyncio.gather(
        *(rag.relation_chunks.get_by_id(item) for item in keys)
    )
    assert all(record is None for record in vector_records)
    assert all(record is None for record in chunk_records)


@pytest.mark.asyncio
async def test_assertion_vectors_survive_restart_and_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("ONTOLOGY_ANNOTATION_ENABLED", "true")
    monkeypatch.setenv(
        "PEM_ONTOLOGY_MAPPING_PATH",
        str(Path(__file__).resolve().parents[2] / "ontology" / "pem_mapping_v1.json"),
    )
    _load_mapping.cache_clear()

    async def summarize(_kind, _name, descriptions, _separator, _config, _cache=None, **_kwargs):
        return " ".join(descriptions), False

    monkeypatch.setattr("lightrag.operate._handle_entity_relation_summary", summarize)
    config = {
        "source_ids_limit_method": "KEEP",
        "max_source_ids_per_relation": 100,
        "max_source_ids_per_entity": 100,
        "max_file_paths": 10,
    }
    source, target = "Assertion A", "Assertion B"
    assertions = [
        _assertion(source, target, "causes", "chunk-1"),
        _assertion(target, source, "influences", "chunk-2"),
    ]
    workspace = f"assertions_{uuid4().hex[:8]}"
    rag = await _build_rag(tmp_path, "assertion_restart", workspace)
    try:
        for _ in range(2):
            await _merge_edges_then_upsert(
                source, target, assertions,
                knowledge_graph_inst=rag.chunk_entity_relation_graph,
                relationships_vdb=rag.relationships_vdb,
                entity_vdb=None,
                global_config=config,
            )
        await rag._insert_done()
    finally:
        await rag.finalize_storages()

    reopened = await _build_rag(tmp_path, "assertion_restart", workspace)
    try:
        ids = [make_assertion_vdb_id(source, target, item) for item in assertions]
        rows = [await reopened.relationships_vdb.get_by_id(item) for item in ids]
        assert all(row is not None for row in rows)
        assert [row["source_id"] for row in rows] == ["chunk-1", "chunk-2"]
        assert await reopened.relationships_vdb.get_by_id(
            make_directional_relation_vdb_id(source, target, assertions[0])
        ) is None
        edge = await reopened.chunk_entity_relation_graph.get_edge(source, target)
        assert len(parse_relation_assertions(edge, source, target)) == 2
        retrieved, _ = await _get_edge_data(
            "influences", reopened.chunk_entity_relation_graph,
            reopened.relationships_vdb, QueryParam(mode="global", top_k=10),
        )
        assert {(item["semantic_src_id"], item["relation_type"],
                 item["semantic_tgt_id"]) for item in retrieved} == {
            (source, "causes", target),
            (target, "influences", source),
        }
    finally:
        await reopened.finalize_storages()


@pytest.mark.asyncio
async def test_purge_cleans_every_v2_record_for_two_assertions(tmp_path):
    rag = await _build_rag(tmp_path, "purge_two_assertions")
    try:
        source, target = "A", "B"
        assertions = [
            _assertion("A", "B", "causes", "chunk-drop-1"),
            _assertion("B", "A", "influences", "chunk-drop-2"),
        ]
        await _seed_edge(rag, source, target, assertions)
        v2_keys, v2_ids = await _seed_relation_records(
            rag, source, target, assertions
        )
        doc_id = "doc-purge"
        await rag.full_entities.upsert({doc_id: {"entity_names": []}})
        await rag.full_relations.upsert(
            {doc_id: {"relation_pairs": [(source, target)]}}
        )
        await rag._purge_doc_chunks_and_kg(
            doc_id,
            {"chunk-drop-1", "chunk-drop-2"},
            pipeline_status={"latest_message": "", "history_messages": []},
            pipeline_status_lock=asyncio.Lock(),
            delete_chunks=False,
        )

        await _assert_records_absent(
            rag,
            v2_ids + make_relation_vdb_ids(source, target),
            v2_keys + [make_relation_chunk_key(source, target)],
        )
        assert await rag.chunk_entity_relation_graph.get_edge(source, target) is None
    finally:
        await rag.finalize_storages()


@pytest.mark.asyncio
async def test_delete_one_doc_rebuilds_and_preserves_other_assertion(
    tmp_path, monkeypatch
):
    rag = await _build_rag(tmp_path, "delete_preserves_other")
    try:
        source, target = "A", "B"
        dropped = _assertion("A", "B", "causes", "chunk-drop")
        retained = _assertion("B", "A", "influences", "chunk-keep")
        assertions = [dropped, retained]
        await _seed_edge(rag, source, target, assertions)
        v2_keys, v2_ids = await _seed_relation_records(
            rag, source, target, assertions
        )
        await rag.relation_chunks.delete([make_relation_chunk_key(source, target)])
        truncated_edge = await rag.chunk_entity_relation_graph.get_edge(source, target)
        await rag.chunk_entity_relation_graph.upsert_edge(
            source, target, {**truncated_edge, "source_id": "chunk-drop"}
        )

        doc_id = "doc-delete"
        now = datetime.now(timezone.utc).isoformat()
        await rag.doc_status.upsert(
            {
                doc_id: {
                    "status": DocStatus.PROCESSED,
                    "content_summary": "delete me",
                    "content_length": 9,
                    "chunks_count": 1,
                    "chunks_list": ["chunk-drop"],
                    "created_at": now,
                    "updated_at": now,
                    "file_path": "drop.txt",
                    "track_id": "track-delete",
                    "error_msg": "",
                    "metadata": {},
                }
            }
        )
        await rag.full_docs.upsert(
            {doc_id: {"content": "delete me", "file_path": "drop.txt"}}
        )
        await rag.full_entities.upsert({doc_id: {"entity_names": []}})
        await rag.full_relations.upsert(
            {doc_id: {"relation_pairs": [(source, target)]}}
        )
        await rag.text_chunks.upsert(
            {
                "chunk-drop": {
                    "content": "drop",
                    "full_doc_id": doc_id,
                    "file_path": "drop.txt",
                },
                "chunk-keep": {
                    "content": "keep",
                    "full_doc_id": "doc-keep",
                    "file_path": "keep.txt",
                },
            }
        )

        async def rebuild(**kwargs):
            await _assert_records_absent(
                rag,
                v2_ids,
                v2_keys,
            )
            legacy_tracking = await rag.relation_chunks.get_by_id(
                make_relation_chunk_key(source, target)
            )
            assert legacy_tracking is not None
            assert legacy_tracking["chunk_ids"] == ["chunk-keep"]
            assert kwargs["relationships_to_rebuild"] == {
                (source, target): ["chunk-keep"]
            }
            await _seed_edge(rag, source, target, [retained])
            await _seed_relation_records(
                rag, source, target, [retained], include_legacy=False
            )

        monkeypatch.setattr(lightrag_module, "rebuild_knowledge_from_chunks", rebuild)

        result = await rag.adelete_by_doc_id(doc_id)

        assert result.status == "success"
        assert await rag.chunk_entity_relation_graph.get_edge(source, target) is not None
        assert await rag.relationships_vdb.get_by_id(v2_ids[0]) is None
        assert await rag.relation_chunks.get_by_id(v2_keys[0]) is None
        assert await rag.relationships_vdb.get_by_id(v2_ids[1]) is not None
        assert await rag.relationships_vdb.get_by_id(v2_ids[2]) is None
        assert await rag.relationships_vdb.get_by_id(v2_ids[3]) is not None
        assert await rag.relation_chunks.get_by_id(v2_keys[1]) is not None
    finally:
        await rag.finalize_storages()


@pytest.mark.asyncio
async def test_purge_retains_legacy_relation_cleanup_baseline(tmp_path):
    rag = await _build_rag(tmp_path, "purge_legacy_baseline")
    try:
        source, target = "LEGACY-A", "LEGACY-B"
        assertion = _assertion(source, target, "related_to", "chunk-legacy")
        await _seed_edge(
            rag, source, target, [assertion], with_assertions=False
        )
        await _seed_relation_records(rag, source, target, [], include_legacy=True)
        doc_id = "doc-legacy"
        await rag.full_entities.upsert({doc_id: {"entity_names": []}})
        await rag.full_relations.upsert(
            {doc_id: {"relation_pairs": [(source, target)]}}
        )

        await rag._purge_doc_chunks_and_kg(
            doc_id,
            {"chunk-legacy"},
            pipeline_status={"latest_message": "", "history_messages": []},
            pipeline_status_lock=asyncio.Lock(),
            delete_chunks=False,
        )

        await _assert_records_absent(
            rag,
            make_relation_vdb_ids(source, target),
            [make_relation_chunk_key(source, target)],
        )
    finally:
        await rag.finalize_storages()


@pytest.mark.asyncio
async def test_purge_fails_closed_on_malformed_relation_assertions(tmp_path):
    rag = await _build_rag(tmp_path, "purge_malformed_assertions")
    try:
        source, target = "A", "B"
        edge = {
            "source": source,
            "target": target,
            "source_id": "chunk-bad",
            "description": "bad relation metadata",
            "relation_type": "causes",
            "directionality": "directed",
            "relation_assertions_json": "{not-json",
        }
        await rag.chunk_entity_relation_graph.upsert_edge(source, target, edge)
        legacy_key = make_relation_chunk_key(source, target)
        legacy_ids = make_relation_vdb_ids(source, target)
        await rag.relation_chunks.upsert(
            {legacy_key: {"chunk_ids": ["chunk-bad"], "count": 1}}
        )
        await rag.relationships_vdb.upsert(
            {
                relation_id: {
                    "content": "legacy relation",
                    "src_id": source,
                    "tgt_id": target,
                    "source_id": "chunk-bad",
                }
                for relation_id in legacy_ids
            }
        )
        doc_id = "doc-bad"
        await rag.full_entities.upsert({doc_id: {"entity_names": []}})
        await rag.full_relations.upsert(
            {doc_id: {"relation_pairs": [(source, target)]}}
        )
        await rag.text_chunks.upsert(
            {
                "chunk-bad": {
                    "content": "must survive failed cleanup",
                    "full_doc_id": doc_id,
                    "file_path": "bad.txt",
                }
            }
        )

        with pytest.raises(
            Exception,
            match=r"Invalid relation assertions for `A`~`B`",
        ):
            await rag._purge_doc_chunks_and_kg(
                doc_id,
                {"chunk-bad"},
                pipeline_status={"latest_message": "", "history_messages": []},
                pipeline_status_lock=asyncio.Lock(),
            )

        assert await rag.chunk_entity_relation_graph.get_edge(source, target) is not None
        assert await rag.full_relations.get_by_id(doc_id) is not None
        assert await rag.text_chunks.get_by_id("chunk-bad") is not None
        assert await rag.relation_chunks.get_by_id(legacy_key) is not None
        legacy_records = await asyncio.gather(
            *(rag.relationships_vdb.get_by_id(relation_id) for relation_id in legacy_ids)
        )
        assert all(record is not None for record in legacy_records)
    finally:
        await rag.finalize_storages()
