/* Independent second fold/GC/sequence viewer, sharing the stability scale. */
(function(root,factory){const lib=factory();if(typeof module==='object'&&module.exports)module.exports=lib;else root.JunctionMRNAStructureCompare=lib;})(typeof window==='object'?window:globalThis,()=>{
 'use strict';
 const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const fmt=(v,d=3)=>Number.isFinite(v)?v.toLocaleString(undefined,{maximumFractionDigits:d}):'—';
 function create(win,doc,{compactGC,gcLabels,drawGCHover,bindGC,gcWindowForBase,describePosition,gcRangeLabel,getRows,getPrimary,extent,ensureProfile,stabilityColor,contrastColor,sequenceRange,selectedPositions,onChange,onLayout}){
  const $=id=>doc.getElementById('mrna-secondary-'+id),root=doc.getElementById('mrna-structure-panel'),toggle=doc.getElementById('mrna-compare-structure');
  let enabled=false,focus='',selection=null,view=null,row=null,drawn=null,drawnScores=null,drawnExtent='',anchor=null,pan=null,profilePending=new WeakSet(),optionKey='';
  const scores=()=>Array.isArray(row?.stability_profile)&&row.stability_profile.length===row.fold_sequence.length?row.stability_profile:null;
  function currentRange(){return row&&selection?.row===row.id&&selection.hash===row.sha256&&selection.scope===row.fold_scope?sequenceRange(row,selection.start,selection.end):null;}
  function snapshot(){return {enabled,focus,selection,viewbox:view};}
  function restore(saved={}){enabled=Boolean(saved?.enabled);focus=typeof saved?.focus==='string'?saved.focus:'';selection=saved?.selection||null;view=Array.isArray(saved?.viewbox)&&saved.viewbox.length===4&&saved.viewbox.every(Number.isFinite)&&saved.viewbox[2]>0&&saved.viewbox[3]>0?saved.viewbox:null;drawn=null;position=1;toggle.checked=enabled;root.classList.toggle('is-comparing',enabled);$('panel').hidden=!enabled;}
  function fitBox(){const points=row.coordinates,x=points.map(p=>p[0]),y=points.map(p=>p[1]),loX=Math.min(...x)-20,loY=Math.min(...y)-20;return [loX,loY,Math.max(60,Math.max(...x)-loX+20),Math.max(60,Math.max(...y)-loY+20)];}
  function setView(){const svg=$('structure').querySelector('svg');if(svg&&view)svg.setAttribute('viewBox',view.join(' '));}
  function zoom(factor){if(!row)return;view??=fitBox();const [x,y,w,h]=view,nw=Math.max(20,Math.min(50000,w*factor)),nh=h*nw/w;view=[x+(w-nw)/2,y+(h-nh)/2,nw,nh];setView();onChange();}
  let position=1, bases=[], marked=[], hoverSource='';
  function showRange(range,source,nt){
    for(const node of marked)node.classList.remove('is-selected');
    marked=range?bases.slice(range.fold_start-1,range.fold_end):[];
    for(const node of marked)node.classList.add('is-selected');
    drawGCHover(row,range,$('gc'));
    for(const chip of $('hotspots').querySelectorAll('[data-hotspot]')){
      chip.classList.toggle('linked',range?.start!=null&&range.start<=Number(chip.dataset.hotspotEnd)&&range.end>=Number(chip.dataset.hotspot));
    }
    hoverSource=source;
    $('gc-info').textContent=source?gcRangeLabel(range,source):'Select a sequence range to keep it highlighted, or hover the GC and structure views.';
    if(row)$('base-info').textContent=describePosition(row,nt||position);
  }
  function restoreRange(){
    const range=currentRange();
    showRange(range,range?'selection':'',position);
  }
  function refreshGC(){
    if(enabled&&row&&$('gc').clientWidth){
      compactGC(row,$('gc'),position);
      restoreRange();
    }
  }
  function highlight(){const range=currentRange();restoreRange();for(const node of $('sequence').querySelectorAll('[data-sequence-base]')){const n=Number(node.dataset.sequenceBase);node.classList.toggle('sequence-selected',Boolean(range)&&n>=range.fold_start&&n<=range.fold_end);}$('from').value=range?.fold_start??1;$('to').value=range?.fold_end??1;$('clear').disabled=!range;$('selection-info').textContent=range?`Selected ${range.fold_start}–${range.fold_end} · ${range.fold_end-range.fold_start+1} nt${range.start==null?' · outside the CDS GC profile':` · CDS ${range.start}–${range.end} · ${fmt(range.gc*100,1)}% GC`}`:'Select bases, shift-click a range or enter coordinates to highlight this panel’s structure and GC profile.';}
  function select(start,end){if(!row)return;const range=sequenceRange(row,start,end);selection={row:row.id,hash:row.sha256,scope:row.fold_scope,start:range.fold_start,end:range.fold_end};highlight();onChange();}
  function draw(){
   const values=scores(),[low,high]=extent(),coords=row.coordinates,points=coords.map(p=>p.join(',')).join(' ');view??=fitBox();
   let svg=`<svg viewBox="${view.join(' ')}" role="img" aria-label="Comparison RNA structure for ${escape(row.name)}"><g class="mrna-secondary-pairs">`;
   for(const [a,b] of row.pairs)svg+=`<line x1="${coords[a-1][0]}" y1="${coords[a-1][1]}" x2="${coords[b-1][0]}" y2="${coords[b-1][1]}"/>`;
   svg+=`</g><polyline class="mrna-secondary-backbone" points="${points}"/><g>`;
   coords.forEach(([x,y],i)=>{const color=stabilityColor(values?.[i],low,high);svg+=`<circle data-secondary-base="${i+1}" cx="${x}" cy="${y}" r="2.7" fill="${color}"><title>Nucleotide ${i+1}${values?' · DegScore '+fmt(values[i],4):''}</title></circle>`;});
   $('structure').innerHTML=svg+'</g></svg>';
   bases=Array.from($('structure').querySelectorAll('[data-secondary-base]'));
   gcLabels(row,$('gc-meta'),$('hotspots'));
   compactGC(row,$('gc'),position);
   $('sequence').innerHTML=Array.from(row.fold_sequence.replace(/T/g,'U'),(base,i)=>{const color=stabilityColor(values?.[i],low,high);return `<span class="mrna-sequence-base" data-sequence-base="${i+1}" title="Nucleotide ${i+1}" style="--stability-color:${color};--stability-text:${contrastColor(color)}">${base}</span>`;}).join('');
   $('from').max=row.fold_sequence.length;$('to').max=row.fold_sequence.length;$('sequence-count').textContent=`${row.fold_sequence.length.toLocaleString()} nt · ${row.fold_scope==='cds'?'CDS':'transcript'} coordinates`;$('stability-note').textContent=values?'Stability · Inferno · shared relative scale with the primary panel':'Stability profile unavailable; bases are shown in grey.';highlight();
  }
  function render(){
   toggle.checked=enabled;root.classList.toggle('is-comparing',enabled);$('panel').hidden=!enabled;$('focus').disabled=!enabled;
   const rows=getRows(),key=rows.map(r=>r.id+'|'+r.name).join('\n');if(key!==optionKey){optionKey=key;$('focus').innerHTML=rows.map(r=>`<option value="${escape(r.id)}">${escape(r.name)}</option>`).join('');}
   if(!enabled)return;
   if(!rows.some(r=>r.id===focus)){const primary=getPrimary(),candidates=rows.filter(r=>r.id!==primary?.id),same=candidates.filter(r=>r.input_name===primary?.input_name&&r.group===primary?.group);focus=(same.find(r=>r.fragment_matching)||same.find(r=>r.strategy!=='input')||same[0]||candidates[0]||rows[0])?.id||'';}
   $('focus').value=focus;row=rows.find(r=>r.id===focus);if(!row){for(const id of ['gc','gc-meta','gc-info','hotspots','sequence','sequence-count','meta','selection-info','base-info','stability-note'])$(id).replaceChildren();bases=[];drawn=null;$('structure').innerHTML='<p class="mrna-empty">Calculate sequences to compare structures.</p>';return;}
   const values=scores(),scale=extent().join('|');$('meta').textContent=`${row.fold_scope==='cds'?'CDS':'Full transcript'} · ${row.fold_sequence.length.toLocaleString()} nt · ${row.temperature} °C · MFE ${fmt(row.metrics.mfe,2)} kcal/mol`;
   if(drawn!==row||drawnScores!==values||drawnExtent!==scale){if(drawn&&drawn!==row)view=null;drawn=row;drawnScores=values;drawnExtent=scale;draw();}
   if(!values&&!profilePending.has(row)){const selected=row;profilePending.add(row);Promise.resolve(ensureProfile(row)).then(()=>{if(enabled&&row===selected&&scores())render();}).catch(()=>{});}
  }
  toggle.onchange=()=>{enabled=toggle.checked;render();onLayout();onChange();};$('focus').onchange=()=>{focus=$('focus').value;position=1;view=null;selection=null;anchor=null;drawn=null;render();onChange();};
  $('zoom-in').onclick=()=>zoom(1/1.4);$('zoom-out').onclick=()=>zoom(1.4);$('fit').onclick=()=>{if(!row)return;view=fitBox();setView();onChange();};$('apply').onclick=()=>select(Number($('from').value),Number($('to').value));$('clear').onclick=()=>{selection=null;highlight();onChange();};
  bindGC($('gc'),$('hotspots'),()=>row,showRange,
    source=>{if(hoverSource===source)restoreRange();},
    range=>{anchor=range.fold_start;select(range.fold_start,range.fold_end);},
    nt=>{
      position=nt;
      const [x,y]=row.coordinates[nt-1];
      view=[x-view[2]/2,y-view[3]/2,view[2],view[3]];
      setView();refreshGC();onChange();
    });
  function readSelection(){if(!row)return false;const range=selectedPositions(win.getSelection(),$('sequence'));if(!range)return false;anchor=range[0];select(...range);return true;}
  $('sequence').onpointerup=()=>win.requestAnimationFrame(readSelection);$('sequence').onkeyup=readSelection;$('sequence').onclick=e=>{const hit=e.target.closest('[data-sequence-base]');if(!hit||readSelection())return;const n=Number(hit.dataset.sequenceBase);select(e.shiftKey&&anchor!=null?anchor:n,n);if(!e.shiftKey)anchor=n;};
  $('structure').onpointerdown=e=>{if(e.button!==0||!row)return;pan={x:e.clientX,y:e.clientY,view:[...(view||fitBox())]};$('structure').setPointerCapture(e.pointerId);};
  $('structure').onpointermove=e=>{const hit=e.target.closest('[data-secondary-base]');if(!pan&&row&&hit){
    const nt=Number(hit.dataset.secondaryBase);
    showRange(gcWindowForBase(row,nt),'structure',nt);
  }else if(hoverSource==='structure')restoreRange();
  if(pan){const box=$('structure').getBoundingClientRect();view=[pan.view[0]-(e.clientX-pan.x)*pan.view[2]/box.width,pan.view[1]-(e.clientY-pan.y)*pan.view[3]/box.height,pan.view[2],pan.view[3]];setView();}};
  $('structure').onpointerleave=()=>{if(hoverSource==='structure')restoreRange();};
  $('structure').onpointerup=()=>{if(pan){pan=null;onChange();}};$('structure').onpointercancel=()=>{pan=null;};$('structure').addEventListener('wheel',e=>{if(!row)return;e.preventDefault();zoom(e.deltaY>0?1.12:1/1.12);},{passive:false});$('structure').onkeydown=e=>{if(['+','=','-','Home'].includes(e.key)){e.preventDefault();if(e.key==='Home'){$('fit').click();}else zoom(e.key==='-'?1.3:1/1.3);}};
  return {render,snapshot,restore,refreshGC};
 }
 return {create};
});
