"""Build a private, offline HTML review of extracted-text relation coverage.

The report links assertions to candidate source passages. It does not treat
co-mentions as proof, and it never writes annotations back to the graph.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from pem_evidence import propose_relation_span
except ImportError:
    from lightrag_mcp.evidence import propose_relation_span


_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])|\n\s*\n")


def _sentences(content: str, chunk_id: str) -> list[dict[str, Any]]:
    result = []
    start = 0
    for separator in _SPLIT.finditer(content):
        if separator.start() > start and content[start:separator.start()].strip():
            result.append((start, separator.start()))
        start = separator.end()
    if content[start:].strip():
        result.append((start, len(content)))
    return [
        {
            "id": f"{chunk_id}:s{index:03d}",
            "start": left,
            "end": right,
            "text": content[left:right].strip(),
            "relations": [],
        }
        for index, (left, right) in enumerate(result)
    ]


def build_coverage(artifact: dict[str, Any], chunks: dict[str, Any]) -> dict[str, Any]:
    docs = artifact.get("documents") or []
    if len(docs) != 1:
        raise ValueError("Select one document's frozen extraction artifact")
    document = docs[0]
    chunk_ids = document.get("chunk_ids") or []
    if not chunk_ids or len(set(chunk_ids)) != len(chunk_ids):
        raise ValueError("Artifact must have distinct selected chunk IDs")
    for chunk_id in chunk_ids:
        item = chunks.get(chunk_id)
        if not isinstance(item, dict) or item.get("full_doc_id") != document["doc_id"]:
            raise ValueError(f"Missing or mismatched source chunk: {chunk_id}")
        if not item.get("content"):
            raise ValueError(f"Empty source chunk: {chunk_id}")

    rendered_chunks = [
        {"id": chunk_id, "sentences": _sentences(chunks[chunk_id]["content"], chunk_id)}
        for chunk_id in chunk_ids
    ]
    chunk_by_id = {item["id"]: item for item in rendered_chunks}
    relations: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for result in document.get("chunk_results") or []:
        for edge in result.get("edges") or []:
            for record in edge.get("records") or []:
                chunk_id = str(record.get("source_id") or "")
                if chunk_id not in chunk_by_id:
                    raise ValueError(f"Assertion refers to unselected chunk: {chunk_id}")
                source = str(record.get("semantic_src_id") or edge.get("source") or "")
                target = str(record.get("semantic_tgt_id") or edge.get("target") or "")
                predicate = str(record.get("relation_type") or "")
                description = str(record.get("description") or "")
                signature = (chunk_id, source, predicate, target, description)
                if signature in seen:
                    continue
                seen.add(signature)
                content = chunks[chunk_id]["content"]
                span = propose_relation_span(
                    content, source, target,
                    description=description,
                    evidence_quote=str(record.get("evidence_quote") or ""),
                )
                linked = []
                if span is not None:
                    midpoint = (int(span["start"]) + int(span["end"])) // 2
                    linked = [
                        sentence["id"] for sentence in chunk_by_id[chunk_id]["sentences"]
                        if sentence["start"] <= midpoint < sentence["end"]
                    ]
                relation_id = f"r{len(relations) + 1:04d}"
                for sentence in chunk_by_id[chunk_id]["sentences"]:
                    if sentence["id"] in linked:
                        sentence["relations"].append(relation_id)
                relations.append({
                    "id": relation_id,
                    "chunk_id": chunk_id,
                    "source": source,
                    "predicate": predicate,
                    "target": target,
                    "description": description,
                    "directionality": str(record.get("directionality") or ""),
                    "match_status": str(span["status"]) if span else "unlocated",
                    "sentence_ids": linked,
                })
    status_counts = Counter(relation["match_status"] for relation in relations)
    linked_sentences = sum(
        bool(sentence["relations"])
        for chunk in rendered_chunks for sentence in chunk["sentences"]
    )
    return {
        "schema_version": 1,
        "artifact_profile": str(artifact.get("profile_file") or "unknown"),
        "document_id": document["doc_id"],
        "document_name": Path(document.get("file_path") or "unknown").name,
        "fingerprint": hashlib.sha256(json.dumps(artifact, sort_keys=True).encode()).hexdigest()[:16],
        "chunks": rendered_chunks,
        "relations": relations,
        "summary": {
            "chunks": len(rendered_chunks),
            "sentences": sum(len(item["sentences"]) for item in rendered_chunks),
            "sentences_with_candidate_links": linked_sentences,
            "assertions": len(relations),
            "link_statuses": dict(status_counts),
        },
    }


_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Extraction coverage review</title>
<style>
:root{font-family:Arial,sans-serif;color:#1c2627;background:#f8faf9;font-size:14px}
*{box-sizing:border-box}body{margin:0}button,input,select,textarea{font:inherit}
header{padding:16px 22px;border-bottom:1px solid #d4dedb;background:#fff;position:sticky;top:0;z-index:2}
h1{font-size:18px;margin:0 0 5px}h2{font-size:15px;margin:0 0 12px}.muted{color:#506461}
.toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:12px}
button,select{border:1px solid #bdccca;background:#fff;padding:7px 10px;border-radius:4px;cursor:pointer}
button:hover{background:#e9f3f0}button.primary{background:#0b725f;color:white;border-color:#0b725f}
main{display:grid;grid-template-columns:220px minmax(320px,1fr) 370px;min-height:calc(100vh - 120px)}
nav,aside{padding:18px;border-right:1px solid #d4dedb;background:#fff}aside{border-right:0;border-left:1px solid #d4dedb}
nav,aside{position:sticky;top:115px;height:calc(100vh - 115px);overflow:auto}
#text{padding:20px 28px;max-width:1000px;width:100%;margin:auto}
.chunk{margin:0 0 34px}.sentence{white-space:pre-wrap;line-height:1.6;padding:5px 8px;margin:0 0 2px;border-left:3px solid transparent;cursor:pointer}
.sentence:hover,.sentence.active{background:#e4f4ef}.sentence.linked{border-left-color:#38a380}.sentence.reviewed{border-left-color:#d28726}
.sentence-id{color:#667976;font-size:11px;display:inline-block;width:55px}.relation{border-bottom:1px solid #e1e8e6;padding:10px 0;overflow-wrap:anywhere}
.relation strong{display:block}.status{color:#506461;font-size:12px;margin-top:4px}.small{font-size:12px}
label{display:block;margin:11px 0 4px;font-weight:600}input,textarea{width:100%;border:1px solid #bdccca;border-radius:4px;padding:8px;background:white}textarea{min-height:70px}
.chunk-link{display:block;width:100%;text-align:left;border:0;border-radius:0}.chunk-link.active{background:#d8f0e8}
.warning{color:#965400}.success{color:#176b4e}#selected{white-space:pre-wrap;line-height:1.5}
@media(max-width:900px){main{grid-template-columns:1fr}nav,aside{position:static;height:auto;border:0;border-bottom:1px solid #d4dedb}#text{padding:16px}}
</style></head><body>
<header><h1 id="title"></h1><div id="summary" class="muted small"></div>
<div class="toolbar"><label style="margin:0"><input type="checkbox" id="gaps" style="width:auto"> Show unlinked sentences only</label>
<button id="export" class="primary">Export annotations JSON</button><span id="progress" class="small muted"></span></div></header>
<main><nav><h2>Chunks</h2><div id="chunks"></div></nav><section id="text"></section><aside>
<h2>Selected sentence</h2><div id="selected" class="muted">Choose a sentence in the extracted text.</div>
<h2 style="margin-top:20px">Candidate relations</h2><div id="relations"></div>
<div id="review" hidden><h2 style="margin-top:22px">Sentence review</h2>
<label for="verdict">Finding</label><select id="verdict"><option value="">Not reviewed</option><option value="no_missing">No missing important relation</option><option value="missing">Missing important relation</option><option value="unclear">Unclear</option></select>
<label for="src">Missing source</label><input id="src" maxlength="200">
<label for="predicate">Missing relation type</label><input id="predicate" maxlength="100">
<label for="tgt">Missing target</label><input id="tgt" maxlength="200">
<label for="importance">Importance</label><select id="importance"><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select>
<label><input type="checkbox" id="intermediate" style="width:auto"> Missing intermediate step</label>
<button id="add">Add missing relation</button><div id="missing-list" class="small"></div>
<label for="note">Note</label><textarea id="note" maxlength="2000"></textarea>
<button id="save">Save sentence review</button><p id="saved" class="small success"></p></div></aside></main>
<script id="coverage" type="application/json">__DATA__</script>
<script>
const data=JSON.parse(document.getElementById('coverage').textContent);
const key='pem-coverage:'+data.fingerprint+':'+data.document_id;
let annotations={};try{annotations=JSON.parse(localStorage.getItem(key)||'{}')}catch{}
let selected=null,draftRelations=[];const byRelation=new Map(data.relations.map(r=>[r.id,r]));
const $=id=>document.getElementById(id);
function node(tag,cls,value){const el=document.createElement(tag);if(cls)el.className=cls;if(value!=null)el.textContent=value;return el}
function progress(){const count=Object.keys(annotations).length;$('progress').textContent=`${count} sentences reviewed locally`}
function render(){
 $('title').textContent=data.document_name+' - '+data.artifact_profile;
 const s=data.summary;$('summary').textContent=`${s.chunks} chunks | ${s.sentences} extracted-text segments | ${s.assertions} assertions | ${s.sentences_with_candidate_links} segments with candidate links. This is not extraction recall or verified evidence.`;
 const nav=$('chunks'),area=$('text');nav.replaceChildren();area.replaceChildren();
 for(const chunk of data.chunks){
  const link=node('button','chunk-link',chunk.id.split('-').slice(-2).join('-'));link.onclick=()=>document.getElementById('chunk-'+chunk.id)?.scrollIntoView();nav.append(link);
  const section=node('section','chunk');section.id='chunk-'+chunk.id;section.append(node('h2','',chunk.id));
  for(const sentence of chunk.sentences){
   if($('gaps').checked&&sentence.relations.length)continue;
   const row=node('p','sentence'+(sentence.relations.length?' linked':'')+(annotations[sentence.id]?' reviewed':'')+(selected===sentence.id?' active':''));
   row.dataset.id=sentence.id;row.append(node('span','sentence-id',sentence.id.split(':').pop()));
   row.append(document.createTextNode(sentence.text));row.onclick=()=>select(sentence.id);section.append(row);
  }area.append(section);
 }progress();
}
function select(id){
 selected=id;document.querySelectorAll('.sentence').forEach(row=>row.classList.toggle('active',row.dataset.id===id));
 const sentence=data.chunks.flatMap(c=>c.sentences).find(s=>s.id===id);if(!sentence)return;
 $('selected').textContent=sentence.text;
 const list=$('relations');list.replaceChildren();
 if(!sentence.relations.length)list.append(node('p','muted small','No assertion was linked to this segment. This does not prove an omission.'));
 for(const ref of sentence.relations){const r=byRelation.get(ref);const card=node('div','relation');
  card.append(node('strong','',`${r.source} [${r.predicate}] ${r.target}`));
  card.append(node('div','small',r.description));card.append(node('div','status',`Link: ${r.match_status} (candidate only)`));list.append(card)}
 const saved=annotations[id]||{};$('review').hidden=false;$('verdict').value=saved.verdict||'';$('src').value='';
 $('predicate').value='';$('tgt').value='';$('note').value=saved.note||'';$('saved').textContent='';
 draftRelations=[...(saved.missing_relations||[])];renderMissingList();
}
function renderMissingList(){const list=$('missing-list');list.replaceChildren();for(const [index,item] of draftRelations.entries()){
 const row=node('div','relation',`${item.source} [${item.predicate}] ${item.target} | ${item.importance}${item.intermediate?' | intermediate':''} `);
 const remove=node('button','small','Remove');remove.onclick=()=>{draftRelations.splice(index,1);renderMissingList()};row.append(remove);list.append(row)}}
$('gaps').onchange=render;
$('add').onclick=()=>{if(!selected||!['src','predicate','tgt'].every(id=>$(id).value.trim())){$('saved').textContent='Enter source, relation and target.';return}
 draftRelations.push({source:$('src').value.trim(),predicate:$('predicate').value.trim(),target:$('tgt').value.trim(),importance:$('importance').value,intermediate:$('intermediate').checked});
 for(const id of ['src','predicate','tgt'])$(id).value='';$('intermediate').checked=false;$('verdict').value='missing';$('saved').textContent='';renderMissingList()};
$('save').onclick=()=>{if(!selected)return;const verdict=$('verdict').value;
 if(verdict==='missing'&&!draftRelations.length){$('saved').textContent='Add at least one missing relation.';return}
 if(!verdict)delete annotations[selected];else annotations[selected]={verdict,missing_relations:verdict==='missing'?[...draftRelations]:[],note:$('note').value.trim()};
 try{localStorage.setItem(key,JSON.stringify(annotations));$('saved').textContent='Saved in this browser.'}catch{$('saved').textContent='Browser storage unavailable; export now.'}render()};
$('export').onclick=()=>{const payload={schema_version:1,document_id:data.document_id,artifact_fingerprint:data.fingerprint,artifact_profile:data.artifact_profile,
 annotations:Object.entries(annotations).map(([sentence_id,v])=>({sentence_id,...v}))};
 const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);
 a.download=`coverage-review-${data.fingerprint}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};
render();
</script></body></html>"""


def render_html(data: dict[str, Any]) -> str:
    encoded = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return _HTML.replace("__DATA__", encoded).replace(
        "<title>Extraction coverage review</title>",
        f"<title>{html.escape(data['document_name'])} - coverage review</title>",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("chunks", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
    chunks = json.loads(args.chunks.read_text(encoding="utf-8"))
    data = build_coverage(artifact, chunks)
    args.output.write_text(render_html(data), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "summary": data["summary"]}, indent=2))


if __name__ == "__main__":
    main()
