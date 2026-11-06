"""Render a private PDF-passage sample as an offline human-review page."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


_PAGE = r"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Relationsabdeckung: Textstichprobe</title>
<style>
:root{font:14px Arial,sans-serif;color:#202a2d;background:#f4f7f6}*{box-sizing:border-box}
body{margin:0}button,input,select,textarea{font:inherit}button,select{cursor:pointer}
header{background:#fff;border-bottom:1px solid #d6dedc;padding:13px 22px;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}
h1{font-size:18px;margin:0 0 4px}h2{font-size:16px;margin:0 0 14px}p{line-height:1.5}
.muted{color:#586b69}.small{font-size:12px}.toolbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
button,.file-label{background:#fff;border:1px solid #b7c7c3;border-radius:4px;padding:7px 10px}
button:hover,.file-label:hover{background:#e7f2ee}button.primary{background:#08735f;color:#fff;border-color:#08735f}
.file-label{cursor:pointer}.file-label input{display:none}
main{display:grid;grid-template-columns:300px minmax(420px,1fr);min-height:calc(100vh - 75px)}
nav{background:#fff;border-right:1px solid #d6dedc;padding:16px;overflow:auto;max-height:calc(100vh - 75px);position:sticky;top:0}
.case{display:block;width:100%;text-align:left;margin:4px 0;border:0;border-left:3px solid transparent;border-radius:0;line-height:1.35;overflow-wrap:anywhere}
.case.active{background:#dcefe8;border-left-color:#08735f}.case.done{border-left-color:#d78d27}
.case small{display:block;color:#586b69;margin-top:3px}
article{padding:24px;max-width:1050px;width:100%;margin:auto}.panel{background:#fff;border:1px solid #d6dedc;border-radius:4px;padding:22px;margin-bottom:14px}
.quote{border-left:3px solid #08735f;background:#f1f7f5;padding:12px 15px;white-space:pre-wrap;line-height:1.6;font-size:15px}
.context{color:#4d6260;white-space:pre-wrap;line-height:1.5}.fields{display:grid;grid-template-columns:1fr 1fr;gap:12px}
label{display:block;font-weight:600;margin:12px 0 5px}input[type=text],select,textarea{width:100%;padding:8px;border:1px solid #b7c7c3;border-radius:4px;background:#fff}
textarea{min-height:80px}.assertion{border:1px solid #d6dedc;padding:12px;margin:10px 0;border-radius:4px}
.triple{display:grid;grid-template-columns:1fr 150px 1fr;gap:8px}.hide{display:none}.warning{color:#a54a22}
@media(max-width:850px){main{display:block}nav{position:static;max-height:220px;border-right:0;border-bottom:1px solid #d6dedc}.fields,.triple{grid-template-columns:1fr}article{padding:12px}}
</style></head><body>
<header><div><h1>Relationsabdeckung: Textstichprobe</h1><div id="progress" class="muted small"></div></div>
<div class="toolbar"><label style="margin:0;font-weight:400"><input id="unreviewed" type="checkbox"> Nur offene</label>
<label class="file-label">Review importieren<input id="import" type="file" accept="application/json"></label>
<button id="export" class="primary">Review exportieren</button></div></header>
<main><nav id="navigation"></nav><article><div id="detail"></div></article></main>
<script id="sample" type="application/json">__DATA__</script>
<script>
const data=JSON.parse(document.getElementById('sample').textContent);
const entries=data.documents.flatMap(d=>d.sample.map(s=>({...s,document:d.file_name,pdf_url:d.pdf_url||''})));
const key='pem-relation-sample:'+data.seed+':'+data.documents.map(d=>d.sha256).join(':');
let reviews={};try{reviews=JSON.parse(localStorage.getItem(key)||'{}')}catch{}
let selected=entries[0]?.id||null;const $=id=>document.getElementById(id);
function el(tag,cls,value){const node=document.createElement(tag);if(cls)node.className=cls;if(value!=null)node.textContent=value;return node}
function save(){try{localStorage.setItem(key,JSON.stringify(reviews))}catch{alert('Browser-Speicherung nicht verfügbar. Bitte Review exportieren.')}}
function field(parent,label,value,placeholder=''){const wrapper=el('div');const name=el('label','',label);const input=el('input');input.type='text';input.value=value||'';input.placeholder=placeholder;wrapper.append(name,input);parent.append(wrapper);return input}
function navigation(){const nav=$('navigation');nav.replaceChildren();let done=0;
 for(const d of data.documents){nav.append(el('h2','',d.file_name));for(const s of d.sample){const review=reviews[s.id];if(review?.eligible_fact)done++;
  if($('unreviewed').checked&&review?.eligible_fact)continue;const b=el('button','case'+(selected===s.id?' active':'')+(review?.eligible_fact?' done':''),`Seite ${s.page} | ${s.text.slice(0,75)}`);
  b.append(el('small','',review?.eligible_fact?`Bewertet: ${review.eligible_fact}`:'Offen'));b.onclick=()=>{selected=s.id;render()};nav.append(b)}}
 $('progress').textContent=`${done}/${entries.length} Stellen bewertet | ${data.documents.length} Dokumente | Seed ${data.seed}. Lokaler Review, kein Graph-Update.`}
function render(){navigation();const host=$('detail');host.replaceChildren();const entry=entries.find(x=>x.id===selected);if(!entry)return;
 const review=reviews[entry.id]||{eligible_fact:'',gold_assertions:[],notes:''};const source=el('section','panel');source.append(el('h2','',entry.document));
 const location=el('p','muted',`Seite ${entry.page} | ${entry.id}`);source.append(location);
 if(entry.pdf_url){const link=el('a','', 'PDF auf dieser Seite öffnen');link.href=entry.pdf_url+'#page='+entry.page;link.target='_blank';link.rel='noopener';source.append(link)}
 if(entry.context_before){source.append(el('label','','Vorher'));source.append(el('div','context',entry.context_before))}
 source.append(el('label','','Zu bewertende Textstelle'));source.append(el('div','quote',entry.text));
 if(entry.context_after){source.append(el('label','','Danach'));source.append(el('div','context',entry.context_after))}host.append(source);
 const form=el('section','panel');form.append(el('h2','','Bewertung'));const eligibleLabel=el('label','','Enthält die Stelle eine wichtige, belegte fachliche Aussage?');form.append(eligibleLabel);
 const verdict=el('select');for(const [value,label] of [['','Noch nicht bewertet'],['yes','Ja'],['no','Nein'],['unclear','Unklar']]){const option=el('option','',label);option.value=value;verdict.append(option)}verdict.value=review.eligible_fact||'';form.append(verdict);
 const rows=el('div');function drawRows(){rows.replaceChildren();for(const [index,a] of (review.gold_assertions||[]).entries()){
  const card=el('div','assertion');card.append(el('strong','',`Aussage ${index+1}`));const triple=el('div','triple');
  for(const [key,label] of [['source','Ausgangskonzept'],['predicate','Relation'],['target','Zielkonzept']]){
   const input=field(triple,label,a[key]);input.oninput=()=>{a[key]=input.value;save()}}card.append(triple);
  const details=el('div','fields');for(const [key,label] of [['conditions','Bedingungen / Vorzeichen'],['evidence','Beleg (kurzer Wortlaut oder Fundstelle)']]){
   const input=field(details,label,a[key]);input.oninput=()=>{a[key]=input.value;save()}}card.append(details);
  const remove=el('button','','Aussage entfernen');remove.onclick=()=>{review.gold_assertions.splice(index,1);drawRows();persist()};card.append(remove);rows.append(card)}}
 function persist(){review.eligible_fact=verdict.value;reviews[entry.id]=review;save();navigation()}
 verdict.onchange=()=>{if(verdict.value!=='yes'&&review.gold_assertions.length){
  if(!confirm('Eingetragene Aussagen entfernen, da die Stelle nicht als Ja bewertet wird?')){verdict.value=review.eligible_fact||'';return}
  review.gold_assertions=[]}persist();drawRows()};form.append(rows);drawRows();const add=el('button','','+ Aussage hinzufügen');add.onclick=()=>{review.gold_assertions.push({source:'',predicate:'',target:'',conditions:'',evidence:''});verdict.value='yes';persist();drawRows()};form.append(add);
 form.append(el('label','','Notiz / Unsicherheit'));const notes=el('textarea');notes.value=review.notes||'';notes.oninput=()=>{review.notes=notes.value;persist()};form.append(notes);
 const controls=el('p');for(const [label,delta] of [['← Zurück',-1],['Weiter →',1]]){const b=el('button','',label);b.style.marginRight='8px';b.onclick=()=>{const index=entries.findIndex(x=>x.id===selected);selected=entries[Math.max(0,Math.min(entries.length-1,index+delta))].id;render();window.scrollTo(0,0)};controls.append(b)}form.append(controls);host.append(form)}
 $('unreviewed').onchange=navigation;
 $('export').onclick=()=>{const clean=Object.fromEntries(Object.entries(reviews).map(([id,r])=>[id,{...r,gold_assertions:r.eligible_fact==='yes'?(r.gold_assertions||[]):[]}]));
 const payload={schema_version:1,seed:data.seed,documents:data.documents.map(d=>({sha256:d.sha256,file_name:d.file_name})),reviews:clean};const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'});const a=el('a');a.href=URL.createObjectURL(blob);a.download=`relation-coverage-review-${data.seed}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};
 $('import').onchange=async event=>{const file=event.target.files?.[0];if(!file)return;try{const loaded=JSON.parse(await file.text());if(loaded.seed!==data.seed||JSON.stringify(loaded.documents)!==JSON.stringify(data.documents.map(d=>({sha256:d.sha256,file_name:d.file_name}))))throw Error('Stichprobe stimmt nicht überein');reviews=loaded.reviews||{};save();render()}catch(error){alert('Review konnte nicht importiert werden: '+error.message)}};
 render();
</script></body></html>"""


def render_html(sample: dict, pdf_root: Path | None = None) -> str:
    data = json.loads(json.dumps(sample))
    if pdf_root is not None:
        for document in data["documents"]:
            path = (pdf_root / document["file_name"]).resolve()
            if path.is_file():
                document["pdf_url"] = path.as_uri()
    encoded = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return _PAGE.replace("__DATA__", encoded)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample_json", type=Path)
    parser.add_argument("output_html", type=Path)
    parser.add_argument("--pdf-root", type=Path)
    args = parser.parse_args()
    data = json.loads(args.sample_json.read_text(encoding="utf-8"))
    args.output_html.write_text(render_html(data, args.pdf_root), encoding="utf-8")
    print(args.output_html)


if __name__ == "__main__":
    main()
