/* Shared donor layouts at fixed imported assembly coordinates. */
(function(root,factory){const lib=factory();if(typeof module==='object'&&module.exports)module.exports=lib;else root.JunctionMRNAMatches=lib;})(typeof window==='object'?window:globalThis,()=>{
 'use strict';
 const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const palette=[['#338d78','#ffffff'],['#7e6db5','#ffffff'],['#c08d41','#12231b'],['#4094bb','#12231b'],['#b56676','#ffffff'],['#7c994b','#12231b']];
 function layout(report){
  const entries=(Array.isArray(report?.library)?report.library:[]).filter(f=>f&&typeof f.id==='string'&&typeof f.name==='string'&&Number.isFinite(f.length)&&f.length>0&&Array.isArray(f.usages));
  const shared=entries.filter(f=>f.shared),colors=new Map(shared.map((f,i)=>[f.id,palette[i%palette.length]])),rows=new Map();
  for(const fragment of entries)for(const use of fragment.usages){if(!use||typeof use.input_name!=='string')continue;if(!rows.has(use.input_name))rows.set(use.input_name,{name:use.input_name,index:use.input_index??rows.size,parts:[]});rows.get(use.input_name).parts.push({id:fragment.id,name:fragment.name,sourceName:use.fragment_name||fragment.name,length:fragment.length,shared:Boolean(fragment.shared),index:use.fragment_index??0,start:use.assembled_start,end:use.assembled_end,total:use.assembled_length,orientation:use.assembly_orientation||1,color:colors.get(fragment.id)?.[0]||'var(--subtle,#eef3ef)',ink:colors.get(fragment.id)?.[1]||'var(--muted,#64756d)'});}
  const ordered=[...rows.values()].sort((a,b)=>a.index-b.index||a.name.localeCompare(b.name)),assembled=ordered.every(r=>r.parts.every(p=>Number.isFinite(p.start)&&Number.isFinite(p.end)&&p.start>=1&&p.end>=p.start&&Number.isFinite(p.total)&&p.total>=p.end));
  for(const row of ordered){row.parts.sort((a,b)=>a.index-b.index);let end=0;for(const p of row.parts){if(!assembled){p.start=end+1;p.end=end+p.length;p.total=0;}end=Math.max(end,p.end);}row.length=Math.max(end,...row.parts.map(p=>p.total));}
  return {rows:ordered,shared,maxLength:Math.max(1,...ordered.map(r=>r.length)),assembled,colors};
 }
 function render(report){
  const data=layout(report);if(!data.rows.length)return {svg:'<p class="small muted">No matched donor layouts are available.</p>',legend:'',note:''};
  const width=1000,left=220,right=980,top=55,gap=58,height=top+data.rows.length*gap+42,x=p=>left+(right-left)*p/data.maxLength;
  let svg=`<svg viewBox="0 0 ${width} ${height}" role="group" aria-label="Matched fragment layouts by assembly">`;
  for(let i=0;i<=4;i++){const pos=data.maxLength*i/4;svg+=`<line x1="${x(pos)}" y1="32" x2="${x(pos)}" y2="${height-34}" class="mrna-match-grid"/><text x="${x(pos)}" y="20" text-anchor="middle" class="mrna-match-coordinate">${Math.round(pos).toLocaleString()}</text>`;}
  data.rows.forEach((row,i)=>{const y=top+i*gap,label=row.name.length>27?row.name.slice(0,25)+'…':row.name;svg+=`<text x="${left-14}" y="${y+16}" text-anchor="end" class="mrna-match-row-name"><title>${escape(row.name)}</title>${escape(label)}</text>`;
   for(const part of row.parts){const start=x(part.start-1),size=Math.max(2,x(part.end)-start),description=`${row.name} · ${part.sourceName} · ${part.start}–${part.end} nt · ${part.length} bp donor · ${part.shared?'shared':'unique'}${part.orientation<0?' · reverse orientation':''}`;svg+=`<g data-match-fragment="${escape(part.id)}" data-match-input="${escape(row.name)}" class="mrna-match-block${part.shared?' is-shared':''}" tabindex="0" role="button" aria-label="${escape(description)}"><title>${escape(description)}</title><rect x="${start}" y="${y}" width="${size}" height="27" rx="3" fill="${part.color}"/>${size>82?`<text x="${start+size/2}" y="${y+17}" text-anchor="middle" fill="${part.ink}">${escape(part.sourceName.length>18?part.sourceName.slice(0,16)+'…':part.sourceName)}</text>`:''}${part.orientation<0&&size>22?`<path d="M${start+10},${y+8}l-5,5 5,5" fill="none" stroke="${part.ink}"/>`:''}</g>`;}
  });
  svg+=`<text x="${(left+right)/2}" y="${height-7}" text-anchor="middle" class="mrna-match-coordinate">${data.assembled?'Assembly position (nt)':'Cumulative donor length (nt, including adapters)'}</text></svg>`;
  const legend=data.shared.map(f=>`<button type="button" data-match-fragment="${escape(f.id)}" class="mrna-match-key"><i style="background:${data.colors.get(f.id)[0]}" aria-hidden="true"></i>${escape(f.name)} <small>${new Set(f.usages.map(u=>u.input_name)).size} assemblies</small></button>`).join('')+'<span class="mrna-match-unique-key">Grey · unique donors</span>';
  return {svg,legend,note:data.assembled?'Fixed imported positions. Shared colours identify the same donor DNA across assemblies; adjoining donor spans overlap at their overhangs.':'Donor lengths include adapters. Position metadata is unavailable for this older result.'};
 }
 return {layout,render};
});
