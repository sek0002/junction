/* Fragment assembly input and donor exports for the mRNA workbench. */
(function(root,factory){const lib=factory();if(typeof module==='object'&&module.exports)module.exports=lib;else root.JunctionMRNAFragments=lib;})(typeof window==='object'?window:globalThis,()=>{
 'use strict';
 const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function validAssembly(a){return !!a&&['BsaI','BsmBI','BsmBI + BsaI'].includes(a.enzyme)&&[1,2,3,-1,-2,-3].includes(a.frame)&&Number.isInteger(a.cds_start)&&a.cds_start>0&&Number.isInteger(a.cds_end)&&a.cds_end>=a.cds_start&&Array.isArray(a.fragments)&&a.fragments.length>0&&a.fragments.length<=32&&a.fragments.every(f=>f&&typeof f.name==='string'&&typeof f.sequence==='string'&&/^[ACGT]+$/.test(f.sequence));}
 function exportRows(rows,selected){return rows.filter(r=>r.strategy!=='input'&&r.fragment_output?.junctions_preserved&&Array.isArray(r.fragment_output.fragments)&&(!selected||selected.has(r.id))).flatMap(r=>r.fragment_output.fragments.filter(f=>f&&typeof f.name==='string'&&typeof f.sequence==='string'&&/^[ACGT]+$/.test(f.sequence)).map(f=>({candidate:r.name,...f})));}
 function partInfo(p){const oh=x=>typeof x==='string'&&/^[ACGT]{4}$/.test(x)?x:'';return {id:p.id,name:p.name,plate_id:typeof p.plate_id==='string'?p.plate_id:'',well:typeof p.well==='string'?p.well:'',length:Number.isFinite(p.physical_length||p.length)?p.physical_length||p.length:null,left:oh(p.left||p.digest?.left_overhang),right:oh(p.right||p.digest?.right_overhang)};}
 function mergeParts(parts,additions){const merged=[],ids=new Set();for(const p of [...parts,...additions]){if(!p||!Number.isInteger(p.id)||p.id<1||typeof p.name!=='string'||ids.has(p.id))continue;ids.add(p.id);merged.push(partInfo(p));}if(merged.length>32)throw Error('Use up to 32 donor fragments. Remove some selections before adding.');return merged;}
 function create(win,doc,{request,post,onAdd,onChange=()=>{}}){
  const $=id=>doc.getElementById('mrna-assembly-'+id);
  let parts=[],pending=new Map(),matches=[],preview=null,searchVersion=0,previewVersion=0,timer=null,loading=false;
  const details=new Map(),tip=$('tooltip');let tipAnchor=null,tipIndex=null;
  const rc=s=>String(s||'').split('').reverse().map(c=>({A:'T',T:'A',G:'C',C:'G'}[c]||c)).join('');
  function hideTooltip(){tipAnchor=null;tip.classList.add('hidden');}
  function endLabels(p,index){const info=details.get($('enzyme').value+':'+p.id),mapped=preview?.fragment_map?.[index],left=info?.digest?.left_overhang||p.left,right=info?.digest?.right_overhang||p.right;return mapped?.orientation<0?[rc(right),rc(left)]:[left,right];}
  function tooltipContent(index){
   if(index===null)return `<b>${escape($('name').value||'Fragment assembly')}</b><small>${escape($('enzyme').value)} · ${parts.length} fragments in ligation order</small><ol>${parts.map((p,i)=>{const [left,right]=endLabels(p,i);return `<li><div><strong>${escape(p.name)}</strong><small>${escape([p.plate_id,p.well].filter(Boolean).join(' / '))}${p.length?' · '+p.length.toLocaleString()+' bp':''}</small></div><code>5′ ${escape(left||'…')}<br>3′ ${escape(right||'…')}</code></li>`;}).join('')}</ol>${preview?`<small>CDS ${preview.cds_start}–${preview.cds_end} · frame ${preview.frame>0?'+':''}${preview.frame} · ${preview.sequence.length} nt</small>`:'<small>Preview assembly to resolve orientations and CDS.</small>'}`;
   const p=parts[index];if(!p)return '';const info=details.get($('enzyme').value+':'+p.id),dna=info?.construct_sequence||info?.sequence||'',gc=dna?100*(dna.match(/[GC]/g)||[]).length/dna.length:null,[left,right]=endLabels(p,index),mapped=preview?.fragment_map?.[index];
   return `<b>${escape(p.name)}</b><small>Fragment ${index+1} of ${parts.length} · ${escape($('enzyme').value)} · ${escape([p.plate_id,p.well].filter(Boolean).join(' / '))}</small><p>${dna.length||p.length||'—'} bp · GC ${gc===null?'…':gc.toFixed(1)+'%'} · ${mapped?(mapped.orientation<0?'Reverse complement':'Forward'):'Orientation resolved in preview'}</p><code>5′ ${escape(left||'…')} → 3′ ${escape(right||'…')}</code>${mapped?`<p>Assembly bp ${mapped.start}–${mapped.end}<br>Selected CDS ${preview.cds_start}–${preview.cds_end} · frame ${preview.frame>0?'+':''}${preview.frame}</p>`:''}${info?.digest?.errors?.length?`<small>${escape(info.digest.errors.join(' '))}</small>`:''}`;
  }
  function positionTooltip(){if(!tipAnchor?.isConnected){hideTooltip();return;}const r=tipAnchor.getBoundingClientRect(),b=tip.getBoundingClientRect();tip.style.left=Math.max(12,Math.min(r.left,win.innerWidth-b.width-12))+'px';tip.style.top=Math.max(12,Math.min(r.bottom+8+b.height<=win.innerHeight-12?r.bottom+8:r.top-b.height-8,win.innerHeight-b.height-12))+'px';}
  function showTooltip(anchor,index){tipAnchor=anchor;tipIndex=index;tip.innerHTML=tooltipContent(index);tip.classList.remove('hidden');positionTooltip();const part=parts[index];if(index===null||!part)return;const key=$('enzyme').value+':'+part.id;if(details.has(key))return;request('/api/fragments/'+part.id+'?enzyme='+encodeURIComponent($('enzyme').value)).then(info=>{details.set(key,info);if(tipAnchor===anchor&&tipIndex===index&&anchor.isConnected){tip.innerHTML=tooltipContent(index);positionTooltip();}}).catch(()=>{});}
  for(const event of ['pointerover','focusin'])$('parts').addEventListener(event,e=>{const card=e.target.closest('[data-part-preview]');if(card&&!(e.relatedTarget&&card.contains(e.relatedTarget)))showTooltip(card,Number(card.dataset.partPreview));});
  for(const event of ['pointerout','focusout'])$('parts').addEventListener(event,e=>{const card=e.target.closest('[data-part-preview]');if(card&&!(e.relatedTarget&&card.contains(e.relatedTarget)))hideTooltip();});
  $('parts').addEventListener('keydown',e=>{if(e.key==='Escape')hideTooltip();});
  doc.addEventListener('keydown',e=>{if(e.key==='Escape')hideTooltip();});
  $('parts').addEventListener('click',e=>{const button=e.target.closest('[data-preview-toggle]');if(button){const card=button.closest('[data-part-preview]');showTooltip(card,Number(card.dataset.partPreview));}});
  $('count').onmouseenter=()=>$('parts').children.length&&showTooltip($('count'),null);$('count').onmouseleave=hideTooltip;$('count').onfocus=$('count').onmouseenter;$('count').onblur=hideTooltip;$('count').onclick=$('count').onmouseenter;$('count').onkeydown=e=>{if(e.key==='Escape')hideTooltip();};
  win.addEventListener('scroll',hideTooltip,{passive:true,capture:true});win.addEventListener('resize',hideTooltip,{passive:true});doc.addEventListener('pointerdown',e=>{if(!e.target.closest('[data-part-preview],#mrna-assembly-count'))hideTooltip();});
  function invalidate(clearBounds=false){hideTooltip();preview=null;previewVersion++;$('add').disabled=true;$('preview').hidden=true;$('error').textContent='';if(clearBounds){$('start').value='';$('end').value='';}}
  function updatePick(){$('pick').disabled=!pending.size;$('pick').textContent=`Add selected (${pending.size}) to working list`;}
  function renderMatches(){
   $('matches').innerHTML=matches.length?matches.map(p=>{const added=parts.some(x=>x.id===p.id);return `<label class="mrna-fragment-match"><input type="checkbox" data-fragment="${p.id}" ${pending.has(p.id)?'checked':''} ${added?'disabled':''}><span>${escape(p.name)}<small>${escape(p.plate_id)} ${escape(p.well)} · ${escape(p.digest?.left_overhang)} → ${escape(p.digest?.right_overhang)}${added?' · In working list':''}</small></span></label>`;}).join(''):'<p class="small muted">No matching fragments.</p>';
   updatePick();
  }
  function render(){
   hideTooltip();$('parts').innerHTML=parts.map((p,i)=>{const [left,right]=endLabels(p,i);return `<li data-part-preview="${i}"><span class="mrna-fragment-number">${i+1}</span><button class="mrna-fragment-open" type="button" data-preview-toggle aria-describedby="mrna-assembly-tooltip"><strong>${escape(p.name)}</strong><small>${escape([p.plate_id,p.well].filter(Boolean).join(' / '))}${p.length?' · '+p.length.toLocaleString()+' bp':''}</small><span class="mrna-fragment-ends"><code>${escape(left||'5′')}</code> → <code>${escape(right||'3′')}</code>${preview?.fragment_map?.[i]?.orientation<0?'<b>RC</b>':''}</span></button><div><button type="button" data-up="${i}" ${i===0?'disabled':''} aria-label="Move ${escape(p.name)} up">↑</button><button type="button" data-down="${i}" ${i===parts.length-1?'disabled':''} aria-label="Move ${escape(p.name)} down">↓</button><button type="button" data-remove="${i}" aria-label="Remove ${escape(p.name)}">×</button></div></li>`;}).join('');
   $('empty').hidden=parts.length>0;
   $('count').textContent=`${parts.length} / 32 fragments`;$('clear').disabled=!parts.length;
   renderMatches();
  }
  async function search(){const token=++searchVersion;try{const rows=await request('/api/fragments?limit=200&enzyme='+encodeURIComponent($('enzyme').value)+'&q='+encodeURIComponent($('search').value));if(token!==searchVersion)return;matches=rows;renderMatches();}catch(e){if(token===searchVersion)$('error').textContent=e.message;}}
  $('search').oninput=()=>{clearTimeout(timer);searchVersion++;timer=win.setTimeout(search,200);onChange();};
  $('matches').onchange=event=>{const input=event.target.closest('[data-fragment]');if(!input)return;const id=Number(input.dataset.fragment),part=matches.find(p=>p.id===id);if(!part||parts.some(p=>p.id===id))return;if(input.checked){if(parts.length+pending.size>=32){input.checked=false;$('error').textContent='Use up to 32 donor fragments. Remove an existing fragment before selecting another.';return;}pending.set(id,partInfo(part));}else pending.delete(id);updatePick();onChange();};
  function append(additions){try{parts=mergeParts(parts,additions);for(const p of parts)pending.delete(p.id);invalidate(true);render();onChange();return true;}catch(e){$('error').textContent=e.message;return false;}}
  $('pick').onclick=()=>append([...pending.values()]);
  $('clear').onclick=()=>{parts=[];invalidate(true);render();onChange();};
  $('parts').onclick=event=>{const b=event.target.closest('button');if(!b)return;const attr=['up','down','remove'].find(k=>b.dataset[k]!==undefined);if(!attr)return;const i=Number(b.dataset[attr]);if(attr==='remove')parts.splice(i,1);else{const j=i+(attr==='up'?-1:1);if(j<0||j>=parts.length)return;[parts[i],parts[j]]=[parts[j],parts[i]];}invalidate(true);render();onChange();};
  for(const id of ['start','end'])$(id).oninput=()=>{invalidate();onChange();};
  $('name').oninput=onChange;
  $('frame').onchange=()=>{invalidate(true);onChange();};
  $('enzyme').onchange=()=>{invalidate(true);search();onChange();};
  async function build(){
   if(loading)return;const token=++previewVersion;loading=true;$('build').disabled=true;$('error').textContent='';$('add').disabled=true;
   try{const data=await request('/api/mrna/assemble',post({fragment_ids:parts.map(p=>p.id),enzyme:$('enzyme').value,frame:$('frame').value==='auto'?'auto':Number($('frame').value),cds_start:$('start').value?Number($('start').value):null,cds_end:$('end').value?Number($('end').value):null}));if(token!==previewVersion)return;preview=data;
    $('start').value=data.cds_start;$('end').value=data.cds_end;
    $('orfs').innerHTML=data.candidates.map((c,i)=>`<option value="${i}" ${c.start===data.cds_start&&c.end===data.cds_end&&c.frame===data.frame?'selected':''}>${c.complete?'Complete ORF':'Partial ORF'} · frame ${c.frame>0?'+':''}${c.frame} · ${c.start}–${c.end} · ${c.length} nt</option>`).join('');
    $('summary').textContent=`${parts.length} fragments → ${data.assembled_sequence.length.toLocaleString()} bp DNA · CDS ${data.cds_start}–${data.cds_end} · frame ${data.frame>0?'+':''}${data.frame} · ${data.sequence.length.toLocaleString()} nt. Protected CDS codons: ${data.preserve_regions.map(r=>r.join('–')).join(', ')||'overhangs lie outside CDS'}.`;
    $('warnings').textContent=data.warnings.join(' ');$('dna').value=data.assembled_sequence;$('preview').hidden=false;$('add').disabled=false;render();onChange();
   }catch(e){if(token===previewVersion){preview=null;$('preview').hidden=true;$('error').textContent=e.message;}}finally{loading=false;$('build').disabled=false;}
  }
  $('build').onclick=build;
  $('orfs').onchange=()=>{const c=preview?.candidates[Number($('orfs').value)];if(!c)return;$('frame').value=String(c.frame);$('start').value=c.start;$('end').value=c.end;invalidate();build();};
  $('auto').onclick=()=>{$('frame').value='auto';$('start').value='';$('end').value='';invalidate();build();};
  $('add').onclick=()=>{if(!preview)return;onAdd({...preview,name:$('name').value.trim()||'Fragment assembly'});};
  function importCurrent(){const source=win.JunctionAssemblyInputs?.current();$('builder').open=true;if(!source?.parts?.length){$('error').textContent='Select donor fragments on the Assembly page first.';return;}if(source.nested){$('error').textContent='Nested replacements must first be exported and imported as donor fragments.';return;}if(parts.length&&source.enzyme!==$('enzyme').value){$('error').textContent='Choose '+source.enzyme+' before adding the Assembly selection to this working list.';return;}if(!parts.length){$('enzyme').value=source.enzyme;$('name').value=source.name||'Fragment assembly';}if(append(source.parts))search();}
  $('current').onclick=importCurrent;
  $('builder').addEventListener('toggle',()=>{if($('builder').open)search();});
  function snapshot(){return {parts,pending:[...pending.values()],name:$('name').value,enzyme:$('enzyme').value,frame:$('frame').value,start:$('start').value,end:$('end').value,search:$('search').value};}
  function restore(saved={}){clearTimeout(timer);searchVersion++;parts=mergeParts([],Array.isArray(saved.parts)?saved.parts.slice(0,32):[]);pending=new Map(mergeParts([],Array.isArray(saved.pending)?saved.pending.slice(0,32):[]).filter(p=>!parts.some(x=>x.id===p.id)).map(p=>[p.id,p]));matches=[];$('name').value=typeof saved.name==='string'?saved.name:'Fragment assembly';$('enzyme').value=['BsaI','BsmBI','BsmBI + BsaI'].includes(saved.enzyme)?saved.enzyme:'BsaI';$('frame').value=['auto','1','2','3','-1','-2','-3'].includes(String(saved.frame))?String(saved.frame):'auto';for(const field of ['start','end'])$(field).value=/^[1-9]\d*$/.test(String(saved[field]))?String(saved[field]):'';$('search').value=typeof saved.search==='string'?saved.search:'';invalidate();render();if($('builder').open)search();}
  render();return {snapshot,restore,importCurrent};
 }
 return {exportRows,validAssembly,mergeParts,create};
});
