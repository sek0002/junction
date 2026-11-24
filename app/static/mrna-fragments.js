/* Fragment assembly input and donor exports for the mRNA workbench. */
(function(root,factory){const lib=factory();if(typeof module==='object'&&module.exports)module.exports=lib;else root.JunctionMRNAFragments=lib;})(typeof window==='object'?window:globalThis,()=>{
 'use strict';
 const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function validAssembly(a){return !!a&&['BsaI','BsmBI','BsmBI + BsaI'].includes(a.enzyme)&&[1,2,3,-1,-2,-3].includes(a.frame)&&Number.isInteger(a.cds_start)&&a.cds_start>0&&Number.isInteger(a.cds_end)&&a.cds_end>=a.cds_start&&Array.isArray(a.fragments)&&a.fragments.length>0&&a.fragments.length<=32&&a.fragments.every(f=>f&&typeof f.name==='string'&&typeof f.sequence==='string'&&/^[ACGT]+$/.test(f.sequence));}
 function exportRows(rows,selected){return rows.filter(r=>r.strategy!=='input'&&r.fragment_output?.junctions_preserved&&Array.isArray(r.fragment_output.fragments)&&(!selected||selected.has(r.id))).flatMap(r=>r.fragment_output.fragments.filter(f=>f&&typeof f.name==='string'&&typeof f.sequence==='string'&&/^[ACGT]+$/.test(f.sequence)).map(f=>({candidate:r.name,...f})));}
 function create(win,doc,{request,post,onAdd}){
  const $=id=>doc.getElementById('mrna-assembly-'+id);
  let parts=[],preview=null,searchVersion=0,previewVersion=0,timer=null,loading=false;
  function invalidate(){preview=null;previewVersion++;$('add').disabled=true;$('preview').hidden=true;$('error').textContent='';}
  function render(){
   $('parts').innerHTML=parts.map((p,i)=>`<li><span>${i+1}. ${escape(p.name)}</span><div><button type="button" data-up="${i}" ${i===0?'disabled':''} aria-label="Move ${escape(p.name)} up">↑</button><button type="button" data-down="${i}" ${i===parts.length-1?'disabled':''} aria-label="Move ${escape(p.name)} down">↓</button><button type="button" data-remove="${i}" aria-label="Remove ${escape(p.name)}">×</button></div></li>`).join('');
   $('empty').hidden=parts.length>0;
  }
  async function search(){const token=++searchVersion;try{const rows=await request('/api/fragments?limit=200&enzyme='+encodeURIComponent($('enzyme').value)+'&q='+encodeURIComponent($('search').value));if(token!==searchVersion)return;$('matches').innerHTML=rows.map(p=>`<option value="${p.id}" ${parts.some(x=>x.id===p.id)?'disabled':''}>${escape(p.name)} · ${escape(p.plate_id)} ${escape(p.well)} · ${escape(p.digest.left_overhang)} → ${escape(p.digest.right_overhang)}</option>`).join('');$('matches')._rows=rows;}catch(e){$('error').textContent=e.message;}}
  $('search').oninput=()=>{clearTimeout(timer);timer=win.setTimeout(search,200);};
  $('pick').onclick=()=>{const id=Number($('matches').value),part=$('matches')._rows?.find(p=>p.id===id);if(!part||parts.some(p=>p.id===id))return;if(parts.length>=32){$('error').textContent='Use up to 32 donor fragments.';return;}parts.push({id,name:part.name});invalidate();render();search();};
  $('parts').onclick=event=>{const b=event.target.closest('button');if(!b)return;const attr=['up','down','remove'].find(k=>b.dataset[k]!==undefined);if(!attr)return;const i=Number(b.dataset[attr]);if(attr==='remove')parts.splice(i,1);else{const j=i+(attr==='up'?-1:1);if(j<0||j>=parts.length)return;[parts[i],parts[j]]=[parts[j],parts[i]];}invalidate();render();search();};
  for(const id of ['start','end'])$(id).oninput=invalidate;
  $('frame').onchange=()=>{$('start').value='';$('end').value='';invalidate();};
  $('enzyme').onchange=()=>{invalidate();search();};
  async function build(){
   if(loading)return;const token=++previewVersion;loading=true;$('build').disabled=true;$('error').textContent='';$('add').disabled=true;
   try{const data=await request('/api/mrna/assemble',post({fragment_ids:parts.map(p=>p.id),enzyme:$('enzyme').value,frame:$('frame').value==='auto'?'auto':Number($('frame').value),cds_start:$('start').value?Number($('start').value):null,cds_end:$('end').value?Number($('end').value):null}));if(token!==previewVersion)return;preview=data;
    $('start').value=data.cds_start;$('end').value=data.cds_end;
    $('orfs').innerHTML=data.candidates.map((c,i)=>`<option value="${i}" ${c.start===data.cds_start&&c.end===data.cds_end&&c.frame===data.frame?'selected':''}>${c.complete?'Complete ORF':'Partial ORF'} · frame ${c.frame>0?'+':''}${c.frame} · ${c.start}–${c.end} · ${c.length} nt</option>`).join('');
    $('summary').textContent=`${parts.length} fragments → ${data.assembled_sequence.length.toLocaleString()} bp DNA · CDS ${data.cds_start}–${data.cds_end} · frame ${data.frame>0?'+':''}${data.frame} · ${data.sequence.length.toLocaleString()} nt. Protected CDS codons: ${data.preserve_regions.map(r=>r.join('–')).join(', ')||'overhangs lie outside CDS'}.`;
    $('warnings').textContent=data.warnings.join(' ');$('dna').value=data.assembled_sequence;$('preview').hidden=false;$('add').disabled=false;
   }catch(e){if(token===previewVersion){preview=null;$('preview').hidden=true;$('error').textContent=e.message;}}finally{loading=false;$('build').disabled=false;}
  }
  $('build').onclick=build;
  $('orfs').onchange=()=>{const c=preview?.candidates[Number($('orfs').value)];if(!c)return;$('frame').value=String(c.frame);$('start').value=c.start;$('end').value=c.end;invalidate();build();};
  $('auto').onclick=()=>{$('frame').value='auto';$('start').value='';$('end').value='';invalidate();build();};
  $('add').onclick=()=>{if(!preview)return;onAdd({...preview,name:$('name').value.trim()||'Fragment assembly'});};
  $('current').onclick=()=>{const source=win.JunctionAssemblyInputs?.current();if(!source?.parts?.length){$('error').textContent='Select donor fragments on the Assembly page first.';return;}if(source.nested){$('error').textContent='Nested replacements must first be exported and imported as donor fragments.';return;}parts=source.parts.slice(0,32);$('enzyme').value=source.enzyme;$('name').value=source.name||'Fragment assembly';invalidate();render();search();};
  $('builder').addEventListener('toggle',()=>{if($('builder').open)search();});
  render();return {reset(){parts=[];$('name').value='Fragment assembly';$('frame').value='auto';$('start').value='';$('end').value='';invalidate();render();searchVersion++;}};
 }
 return {exportRows,validAssembly,create};
});
