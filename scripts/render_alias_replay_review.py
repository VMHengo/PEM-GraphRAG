"""Render a private offline alias-path result as a standalone review page."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Alias Path Review</title>
<style>
:root{font-family:system-ui,Arial,sans-serif;color:#17252b;background:#f5f7f8;font-size:14px}
*{box-sizing:border-box}body{margin:0}button,input,select,textarea{font:inherit}
header{background:#fff;border-bottom:1px solid #dce4e6;padding:18px 24px;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}
h1{font-size:21px;margin:0}h2{font-size:16px;margin:0 0 10px}small,.muted{color:#61757c}
.stats{display:flex;gap:20px;flex-wrap:wrap}.stats strong{display:block;font-size:21px;color:#153d45}
.layout{display:grid;grid-template-columns:minmax(280px,360px) minmax(0,1fr);height:calc(100vh - 89px)}
aside{border-right:1px solid #dce4e6;background:#fff;display:flex;flex-direction:column;min-height:0}
.filters{padding:16px;border-bottom:1px solid #e1e8e9;display:grid;gap:10px}
input,select,textarea{background:#fff;border:1px solid #c9d5d8;border-radius:5px;padding:9px;color:#17252b;min-width:0}
input:focus,select:focus,textarea:focus,button:focus-visible{outline:2px solid #16858a;outline-offset:1px}
.filters input{width:100%}.filterrow{display:flex;gap:8px}.filterrow>*{flex:1}
#items{overflow:auto;min-height:0}.item{width:100%;text-align:left;background:#fff;border:0;border-bottom:1px solid #edf1f2;padding:13px 16px;cursor:pointer;display:grid;gap:6px;line-height:1.35}
.item:hover,.item.active{background:#e9f4f2}.item.active{border-left:3px solid #078b72;padding-left:13px}
.item .line{font-weight:600;overflow-wrap:anywhere}.badge{display:inline-block;font-size:11px;padding:3px 6px;border-radius:4px;background:#e3e9ea;color:#354c54;width:max-content}
.badge.mixed{background:#fff0d6;color:#8a5200}.badge.causal{background:#d9f1e8;color:#087455}
main{overflow:auto;padding:22px 28px;min-width:0}.detail{max-width:1050px;margin:auto}.topline{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.chain{font-size:17px;font-weight:650;line-height:1.5;overflow-wrap:anywhere;margin:12px 0 22px}.chain em{font-size:13px;color:#0d736b;font-style:normal;font-weight:500}
.hop{border-top:1px solid #dce4e6;padding:17px 0}.hop h3{font-size:15px;margin:0 0 8px;overflow-wrap:anywhere}
.hop p{margin:8px 0;line-height:1.5;white-space:pre-wrap}.source{color:#49616a;font-size:12px;overflow-wrap:anywhere}
.bridge{background:#e7f2f0;border-left:3px solid #078b72;padding:8px 12px;margin:5px 0;color:#245454}
.review{border-top:1px solid #dce4e6;margin-top:10px;padding-top:18px;display:grid;gap:10px}.review textarea{width:100%;min-height:85px;resize:vertical}
.actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}button.command{background:#176a68;border:1px solid #176a68;color:white;border-radius:5px;padding:9px 12px;cursor:pointer}
button.secondary{background:#fff;color:#176a68}.empty{padding:24px;color:#61757c}
@media(max-width:760px){.layout{display:block;height:auto}aside{max-height:42vh;border-right:0;border-bottom:1px solid #dce4e6}main{padding:18px}}
</style></head><body>
<header><div><h1>Alias Path Review</h1><small>Offline candidates · source claims require review</small></div><div class="stats" id="stats"></div><button class="command secondary" id="export">Export reviews</button></header>
<div class="layout"><aside><div class="filters"><input id="search" type="search" placeholder="Search nodes, relations, documents" aria-label="Search paths"><div class="filterrow"><select id="category" aria-label="Path category"><option value="all">All paths</option><option value="causal">Causal</option><option value="mixed">Mixed</option><option value="other">Other</option></select><select id="status" aria-label="Review status"><option value="all">All statuses</option><option value="unreviewed">Unreviewed</option><option value="accepted">Accepted</option><option value="rejected">Rejected</option><option value="uncertain">Uncertain</option></select></div><small id="count"></small></div><div id="items"></div></aside><main><div class="detail" id="detail"><p class="empty">Select a path.</p></div></main></div>
<script type="application/json" id="data">__DATA__</script>
<script>
const data=JSON.parse(document.getElementById('data').textContent);
const paths=data.additional_paths||[];
const storageKey='pem-alias-review-'+data.alias_version+'-'+data.edge_count+'-'+data.additional_path_count;
let reviews={};try{reviews=JSON.parse(localStorage.getItem(storageKey)||'{}')}catch(e){reviews={}}
let active=null;
const $=id=>document.getElementById(id);
const node=(tag,cls,value)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(value!==undefined)e.textContent=String(value);return e};
const key=p=>p.hops.map(h=>h.id).join('|');
const type=p=>p.causal_only?'causal':p.mixed_causal?'mixed':'other';
const save=()=>localStorage.setItem(storageKey,JSON.stringify(reviews));
function filtered(){const q=$('search').value.toLocaleLowerCase().trim(),cat=$('category').value,status=$('status').value;return paths.filter(p=>(cat==='all'||type(p)===cat)&&(status==='all'||(reviews[key(p)]?.verdict||'unreviewed')===status)&&(!q||p.hops.some(h=>[h.source,h.target,h.relation_type,h.file_path,h.source_id].some(v=>String(v||'').toLocaleLowerCase().includes(q)))))}
function renderList(){const list=filtered(),box=$('items');box.replaceChildren();$('count').textContent=list.length+' of '+paths.length+' paths';
  list.forEach(p=>{const button=node('button','item'+(active===key(p)?' active':''));button.type='button';button.append(node('span','badge '+type(p),type(p)+' · '+p.hops.length+' hops'),node('span','line',p.hops[0].source+' → '+p.hops.at(-1).target),node('small','',p.hops.map(h=>h.relation_type).join(' · ')+'  |  '+(reviews[key(p)]?.verdict||'unreviewed')));button.onclick=()=>{active=key(p);renderList();renderDetail(p)};box.append(button)});
  if(!list.length)box.append(node('div','empty','No paths match these filters.'));
}
function renderDetail(p){const box=$('detail');box.replaceChildren();const title=node('div','topline');title.append(node('h2','',p.hops[0].source+' → '+p.hops.at(-1).target),node('span','badge '+type(p),type(p)+' candidate'));box.append(title);
  const route=node('div','chain');p.hops.forEach((h,i)=>{if(i)route.append(node('span','',' → '));route.append(node('span','',h.source+' '));route.append(node('em','', '['+h.relation_type+']'));if(i===p.hops.length-1)route.append(node('span','',' → '+h.target))});box.append(route);
  p.hops.forEach((h,i)=>{if(i&&p.hops[i-1].target!==h.source)box.append(node('div','bridge','Alias bridge: '+p.hops[i-1].target+' ≈ '+h.source));const section=node('section','hop');section.append(node('h3','',`Hop ${i+1}: ${h.source} [${h.relation_type}] ${h.target}`),node('div','source',(h.file_path||'Unknown document')+' · '+(h.source_id||'Source missing')),node('p','',h.description||'No description stored.'));box.append(section)});
  const form=node('div','review');form.append(node('h2','','Review'));const select=node('select');[['unreviewed','Select verdict'],['accepted','Supported and composable'],['rejected','Not supported / invalid bridge'],['uncertain','Needs source check']].forEach(([v,label])=>{const o=node('option','',label);o.value=v;select.append(o)});select.value=reviews[key(p)]?.verdict||'unreviewed';const note=node('textarea');note.placeholder='Why? Record missing evidence, incorrect direction, condition mismatch, or a useful connection.';note.value=reviews[key(p)]?.note||'';const actions=node('div','actions');const saveButton=node('button','command','Save review');saveButton.onclick=()=>{reviews[key(p)]={verdict:select.value,note:note.value,updated_at:new Date().toISOString()};save();renderList();saveButton.textContent='Saved'};actions.append(saveButton);form.append(select,note,actions);box.append(form);
}
$('stats').append(...[['Baseline',data.baseline_path_count],['Projected',data.projected_path_count],['New',data.additional_path_count],['Causal',data.causal_additional_count],['Mixed',data.mixed_additional_count]].map(([label,value])=>{const e=node('div');e.append(node('small','',label),node('strong','',value));return e}));
['search','category','status'].forEach(id=>$(id).addEventListener(id==='search'?'input':'change',renderList));
$('export').onclick=()=>{const payload={alias_version:data.alias_version,edge_count:data.edge_count,generated_at:new Date().toISOString(),reviews};const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='alias_path_reviews.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};
renderList();if(paths.length){active=key(paths[0]);renderList();renderDetail(paths[0])}
</script></body></html>"""


def render(data: dict) -> str:
    if not isinstance(data.get("additional_paths"), list):
        raise ValueError("Expected an offline alias replay result")
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
    return PAGE.replace("__DATA__", payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    data = json.loads(args.result.read_text(encoding="utf-8"))
    args.output.write_text(render(data), encoding="utf-8")
    print(f"Rendered {len(data['additional_paths'])} paths to {args.output}")


if __name__ == "__main__":
    main()
