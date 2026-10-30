/* Private, persistent fragment design; generated DNA never changes inventory. */
(function(root){
  'use strict';
  const dna=text=>String(text||'').split(/\r?\n/).filter(line=>!line.startsWith('>')).join('').replace(/\s/g,'').toUpperCase();
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function addSection(sections,sequence,start,end,name,mode='constant'){
    if(!Number.isInteger(start)||!Number.isInteger(end)||start<0||end<=start||end>sequence.length)throw Error('Select bases within the insert.');
    if(sections.some(section=>start<section.end&&end>section.start))throw Error('The selected section overlaps another section.');
    return [...sections,{name:name.trim()||'Part '+(sections.length+1),start,end,mode}].sort((a,b)=>a.start-b.start);
  }
  function parseVariants(text){
    const lines=String(text||'').split(/\r?\n/);if(!lines.some(line=>line.startsWith('>')))return dna(text)?[{name:'Variant 1',sequence:dna(text)}]:[];
    const variants=[];let record=null;
    for(const line of lines){if(line.startsWith('>')){if(record)variants.push(record);record={name:line.slice(1).trim()||'Variant '+(variants.length+1),sequence:''};}else if(record)record.sequence+=line;else if(line.trim())throw Error('Place sequence data after a FASTA header.');}
    if(record)variants.push(record);return variants.map(record=>({...record,sequence:dna(record.sequence)}));
  }
  function exportPayload(design,reverse=false,example=false){
    const body=JSON.parse(JSON.stringify(design));delete body.id;body.reverse_output=reverse;
    if(example){body.use_table=false;body.table_rows=[];body.entries=body.entries.map(item=>({...item,sections:item.sections?.map(section=>({...section,variants:[]}))}));}
    return body;
  }
  function fragmentRcTag(item,node){
    if(item.kind!=='fragment'||!(node?.digest?.reverse_complement??node?.reverse))return '';
    return '<span class="fragment-rc" role="img" aria-label="Reverse complement" title="Reverse complement · whole fragment assembled in reverse orientation"><svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M4 7h16m-5-4 5 4-5 4M20 17H4m5-4-5 4 5 4"/></svg><span>RC</span></span>';
  }
  function moveEntry(entries,from,to){
    if(from<0||from>=entries.length||to<0||to>=entries.length)return entries;
    const copy=entries.slice(),[entry]=copy.splice(from,1);copy.splice(to,0,entry);return copy;
  }
  if(typeof module==='object'&&module.exports){module.exports={dna,addSection,moveEntry,parseVariants,exportPayload,fragmentRcTag};return;}
  const $=id=>document.getElementById(id),uid=()=>crypto.randomUUID();
  let saved={designs:[],activeId:null},activeEntry=null,refs=null,refsEnzyme=null,refRevision=0,
    revision=0,requestRevision=0,checkTimer,saveTimer,lastResult=null,preview=null,ready=false,dragId=null,generating=false,assemblyPreview=null,searchRevision=0,searchTimer;
  const current=()=>saved.designs.find(design=>design.id===saved.activeId);
  const entry=()=>current()?.entries.find(item=>item.id===activeEntry);
  const tableUI=root.DesignTable.create({getDesign:current,getContext:()=>preview?.entries||[],onChange:()=>{dirty();renderSections();},report:message=>note(message)});
  function fresh(){return{id:uid(),name:'New design',enzyme:'BsaI',adapter_enzyme:'BsaI',left_adapter_enzyme:null,right_adapter_enzyme:null,include_re_sites:true,reverse_output:false,make_twist_compatible:false,use_table:false,table_rows:[],backbone_id:null,slot_id:null,entries:[],left_overhang:'',right_overhang:'',window:20,avoid_sites:[],excluded_overhangs:[]};}
  function note(message,error=false){$('design-save-status').textContent=message;$('design-save-status').classList.toggle('reaction-warning',error);}
  function persist(){
    note('Saving…');root.JunctionSandbox?.schedule();
    clearTimeout(saveTimer);const changed=revision;
    saveTimer=setTimeout(async()=>{try{if(root.JunctionSandbox?.ready){await root.JunctionSandbox.flush();if(changed===revision)note('Saved · Private sandbox');}}catch(error){note('Not saved · '+error.message,true);}},650);
  }
  function clearAssemblyPreview(){assemblyPreview?.destroy();assemblyPreview=null;}
  function dirty(){
    clearAssemblyPreview();
    revision++;requestRevision++;generating=false;lastResult=null;tableUI.clear();$('design-download').disabled=true;$('design-generate').disabled=false;
    $('design-output').innerHTML='<span class="small muted">Generate to update fragments</span>';
    persist();
    clearTimeout(checkTimer);checkTimer=setTimeout(()=>check(false),450);
  }
  function payload(){const d=current();return{...d,entries:d.entries.map(item=>({...item})),id:undefined};}
  async function request(url,body){
    const response=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});
    if(!response.ok){const data=await response.json();const detail=data.detail;throw Error(typeof detail==='string'?detail:detail?.errors?.join(' ')||detail?.message||(Array.isArray(detail)?detail.map(item=>item.msg).join(' '):'Check the design fields.'));}
    return response;
  }
  const label=(value,backbone=false)=>`<span class="design-fusion${backbone?' backbone':''}${root.Overhangs.isPalindromic(value)?' palindrome':''}" title="${root.Overhangs.isPalindromic(value)?'Palindromic overhang':backbone?'Backbone overhang':'Fusion overhang'}">${esc(value||'????')}</span>`;
  function chosenBackbone(){return refs?.backbones.find(bb=>bb.id===Number(current().backbone_id));}
  function chosenSlot(){return chosenBackbone()?.slots.find(slot=>slot.id===current().slot_id);}
  function renderSaved(){
    $('design-saved').innerHTML=saved.designs.map(design=>`<option value="${esc(design.id)}">${esc(design.name)}</option>`).join('');$('design-saved').value=saved.activeId;
  }
  function renderFields(){
    const d=current();if(!d)return;renderSaved();
    for(const[id,key]of Object.entries({'design-name':'name','design-enzyme':'enzyme','design-left':'left_overhang','design-right':'right_overhang','design-window':'window','design-adapter':'adapter_enzyme','design-left-enzyme':'left_adapter_enzyme','design-right-enzyme':'right_adapter_enzyme'}))$(id).value=d[key]??'';
    $('design-card-title').textContent=d.name;
    $('design-add-re').checked=d.include_re_sites!==false;
    $('design-export-rc').checked=!!d.reverse_output;
    $('design-twist-compatible').checked=!!d.make_twist_compatible;
    $('design-twist-help').hidden=!d.make_twist_compatible;
    $('design-excluded').value=d.excluded_overhangs.join(', ');
    $('design-left').disabled=$('design-right').disabled=!!d.backbone_id;
  }
  const viewIcon='<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>';
  function renderReferences(){
    if(!refs)return;const d=current();
    $('design-backbone').innerHTML='<option value="">No backbone</option>'+refs.backbones.map(bb=>`<option value="${bb.id}">${esc(bb.name)} · ${bb.length.toLocaleString()} bp${bb.slots.length?'':' · No '+esc(d.enzyme)+' cassette'}</option>`).join('');
    $('design-backbone').value=d.backbone_id||'';
    const slots=chosenBackbone()?.slots||[];
    $('design-slot').innerHTML='<option value="">Choose cassette</option>'+slots.map(slot=>`<option value="${esc(slot.id)}">${esc(slot.label)}</option>`).join('');$('design-slot').value=d.slot_id||'';$('design-slot').disabled=!d.backbone_id;
    $('design-backbone-cards').innerHTML=refs.backbones.map(bb=>`<div class="design-backbone-card${bb.id===d.backbone_id?' selected':''}"><button type="button" class="icon-button design-backbone-view" data-design-view-bb="${bb.id}" aria-label="View ${esc(bb.name)}" title="View backbone" aria-haspopup="dialog">${viewIcon}</button><strong>${esc(bb.name)}</strong><small>${bb.length.toLocaleString()} bp</small><div>${Object.entries(bb.all_slots).flatMap(([mode,options])=>options.filter(slot=>mode!=='BsmBI + BsaI'||slot.enzyme===mode).map(slot=>`<button type="button" class="design-cassette-choice" data-design-bb="${bb.id}" data-mode="${esc(mode)}" data-slot="${esc(slot.id)}" title="${esc(slot.errors.join(' ')||slot.label)}"><span>${esc(mode)}</span>${label(slot.left_overhang,true)}<span>→</span>${label(slot.right_overhang,true)}</button>`)).join('')||'<small>No cassette</small>'}</div></div>`).join('')||'<span class="small muted">No backbone templates</span>';
    $('design-avoid').innerHTML=refs.enzymes.map(enzyme=>`<label><input type="checkbox" value="${esc(enzyme)}" ${d.avoid_sites.includes(enzyme)?'checked':''}>${esc(enzyme)}</label>`).join('');
  }
  async function loadReferences(){
    const token=++refRevision,enzyme=current().enzyme;
    try{
      const response=await request('/api/design/references?enzyme='+encodeURIComponent(enzyme));const data=await response.json();
      if(token!==refRevision||enzyme!==current().enzyme)return;
      refs=data;refsEnzyme=enzyme;renderReferences();renderChain();renderSearch();check(false);
    }catch(error){if(token===refRevision)note(error.message,true);}
  }
  function ends(item){
    if(item.kind==='fragment'){
      const fragment=refs?.fragments.find(f=>f.id===item.fragment_id),variant=preview?.entries.find(node=>node.id===item.id)?.digest||fragment?.variants[0];
      return variant||{};
    }
    const node=preview?.entries.find(n=>n.id===item.id),run=preview?.runs.find(r=>r.index===node?.run);
    return run||{};
  }
  function renderChain(){
    const d=current(),slot=chosenSlot();if(!d)return;
    const add=index=>`<button class="design-gap" type="button" data-placeholder-at="${index}" aria-label="Add placeholder at position ${index+1}" title="Add placeholder">+</button>`;
    $('design-chain').innerHTML=(slot?label(slot.left_overhang,true):'')+add(0)+d.entries.map((item,index)=>{
      const fusion=ends(item),known=item.kind==='fragment',selected=item.id===activeEntry,node=preview?.entries.find(node=>node.id===item.id);
      return `<div class="design-node ${known?'existing':'placeholder'}${selected?' selected':''}" draggable="true" data-entry-id="${esc(item.id)}">${fragmentRcTag(item,node)}<button type="button" class="design-node-main" data-design-entry="${esc(item.id)}" title="${known?'Existing fragment · Alt+Left/Right to reorder':'Edit insert · Alt+Left/Right to reorder'}"><strong>${esc(known?(refs?.fragments.find(f=>f.id===item.fragment_id)?.name||item.name):item.name)}</strong><small>${known?'Existing':(dna(item.sequence).length.toLocaleString()+' nt · '+item.sections.length+' sections')}</small><span>${label(fusion.left_overhang)}${label(fusion.right_overhang)}</span></button><span class="design-card-tools"><button type="button" class="icon-button design-view" data-design-view="${esc(item.id)}" aria-label="View ${esc(item.name)}" title="View sequence" aria-haspopup="dialog">${viewIcon}</button></span><button class="design-remove" data-design-remove="${esc(item.id)}" aria-label="Remove ${esc(item.name)}">×</button></div>${add(index+1)}`;
    }).join('')+(slot?label(slot.right_overhang,true):'');
  }
  async function renderSearch(){
    const token=++searchRevision,query=$('design-fragment-search').value.trim(),box=$('design-search-results'),enzyme=current().enzyme,designId=current().id;
    if(!query||!refs||refsEnzyme!==enzyme){box.classList.add('hidden');return;}
    box.innerHTML='<span class="small muted">Searching…</span>';box.classList.remove('hidden');
    try{
      const response=await request('/api/fragments?'+new URLSearchParams({q:query,enzyme,limit:'30'})),matches=await response.json();
      if(token!==searchRevision||current().id!==designId||current().enzyme!==enzyme||$('design-fragment-search').value.trim()!==query)return;
      box.innerHTML=matches.map(fragment=>{const variant=fragment.digest;return `<button type="button" data-design-add="${fragment.id}" ${!variant.valid?'disabled':''} title="${esc(variant.errors?.join(' ')||root.FragmentSearch.location(fragment)+' · Auto orientation')}"><span><strong>${esc(fragment.name)}</strong>${root.FragmentSearch.badge(fragment)}<small>${esc(root.FragmentSearch.location(fragment))} · ${fragment.length.toLocaleString()} nt</small></span><span>${label(variant.left_overhang)}${label(variant.right_overhang)}</span></button>`;}).join('')||'<span class="small muted">No matches</span>';
    }catch(error){if(token===searchRevision){box.innerHTML='<span class="small muted">'+esc(error.message)+'</span>';}}
  }
  function sequenceHtml(sequence,sections,sites=[]){
    const points=[...new Set([0,sequence.length,...sections.flatMap(s=>[s.start,s.end]),...sites.flatMap(s=>[s.start,s.end])])].filter(p=>p>=0&&p<=sequence.length).sort((a,b)=>a-b);
    return points.slice(0,-1).map((start,index)=>{const end=points[index+1],section=sections.findIndex(s=>s.start<=start&&s.end>=end),hits=sites.filter(s=>s.start<end&&s.end>start);
      return `<span class="${section>=0?'design-section-'+section%6:''}${hits.length?' design-site':''}" title="${esc((section>=0?sections[section].name+' · '+(sections[section].mode==='dynamic'?'Dynamic':'Constant')+' · ':'')+(start+1)+'–'+end+(hits.length?' · '+hits.map(s=>s.enzyme).join(', '):''))}">${esc(sequence.slice(start,end))}</span>`;
    }).join('');
  }
  function renderSequence(){
    const item=entry();if(!item||item.kind!=='placeholder')return;
    const sequence=dna(item.sequence),node=preview?.entries.find(n=>n.id===item.id);
    $('design-sequence').innerHTML=sequenceHtml(sequence,item.sections,node?.sites||[]);$('design-sequence-size').textContent=sequence.length.toLocaleString()+' nt';
  }
  function renderEditor(){
    const item=entry(),editor=$('design-editor');editor.classList.toggle('hidden',!item||item.kind!=='placeholder');if(!item||item.kind!=='placeholder'){tableUI.render();return;}
    editor.innerHTML=`<div class="panel-heading"><h2>Insert</h2><div class="design-actions"><input id="design-placeholder-name" aria-label="Placeholder name" maxlength="100" value="${esc(item.name)}"></div></div><label class="field-label" for="design-insert">Full insert sequence</label><textarea id="design-insert" rows="4" maxlength="100000" spellcheck="false" placeholder="Paste DNA or FASTA" title="Paste the payload between the surrounding fusion labels. Free ends use the insert’s own terminal bases.">${esc(item.sequence)}</textarea><div id="design-insert-sites" class="design-sites"></div><div class="design-sequence-heading"><h3>Sections</h3><small id="design-sequence-size"></small></div><pre id="design-sequence" class="design-sequence" tabindex="0" aria-label="Select insert bases" title="Drag across bases, then add a section"></pre><div class="design-section-controls"><label>Name<input id="design-section-name" placeholder="Part ${item.sections.length+1}" maxlength="100"></label><label>Region<select id="design-section-mode"><option value="constant">Constant</option><option value="dynamic">Dynamic</option></select></label><label>Start<input id="design-section-start" aria-label="Section start" type="number" min="1" step="1"></label><label>End<input id="design-section-end" aria-label="Section end" type="number" min="1" step="1"></label><button id="design-section-add" class="secondary compact" type="button">Add section</button></div><div id="design-section-error" class="reaction-warning" role="alert"></div><div id="design-sections"></div>`;
    renderSequence();renderSections();renderSites();tableUI.render();
    $('design-placeholder-name').oninput=event=>{item.name=event.target.value;dirty();renderChain();tableUI.render();};
    $('design-insert').oninput=event=>{const changed=dna(item.sequence)!==dna(event.target.value);item.sequence=event.target.value;if(changed)item.sections=[];preview=null;dirty();renderSequence();renderSections();renderChain();tableUI.render();$('design-insert-sites').textContent='Checking…';};
    $('design-sequence').onmouseup=captureSelection;$('design-sequence').onkeyup=captureSelection;
    $('design-section-add').onmousedown=event=>event.preventDefault();
    $('design-section-add').onclick=()=>{try{item.sections=addSection(item.sections,dna(item.sequence),Number($('design-section-start').value)-1,Number($('design-section-end').value),$('design-section-name').value,$('design-section-mode').value);$('design-section-error').textContent='';dirty();renderEditor();renderChain();}catch(error){$('design-section-error').textContent=error.message;}};
  }
  function captureSelection(){
    const selection=window.getSelection(),pre=$('design-sequence');if(!selection?.rangeCount||selection.isCollapsed)return;
    const range=selection.getRangeAt(0);if(!pre.contains(range.startContainer)||!pre.contains(range.endContainer))return;
    const prefix=range.cloneRange();prefix.selectNodeContents(pre);prefix.setEnd(range.startContainer,range.startOffset);
    const start=prefix.toString().replace(/\s/g,'').length,end=start+range.toString().replace(/\s/g,'').length;
    $('design-section-start').value=start+1;$('design-section-end').value=end;
  }
  function renderSections(){
    const item=entry();if(!$('design-sections')||!item)return;
    $('design-sections').innerHTML=item.sections.map((section,index)=>`<div class="design-section-row design-section-${index%6}"><strong>${esc(section.name)}</strong><select data-region-mode="${index}" aria-label="Region mode for ${esc(section.name)}"><option value="constant" ${section.mode!=='dynamic'?'selected':''}>Constant</option><option value="dynamic" ${section.mode==='dynamic'?'selected':''}>Dynamic</option></select><span>${section.start+1}–${section.end} · ${section.end-section.start} nt${section.variants?.length?' · '+section.variants.length+' variants':''}</span><button type="button" class="text-button" data-section-remove="${index}" aria-label="Remove section ${esc(section.name)}">×</button></div>${section.mode==='dynamic'?`<details class="design-variants"><summary>Pasted variants · ${esc(section.name)}</summary><textarea rows="3" spellcheck="false" data-variant-section="${index}" ${current().use_table?'disabled':''} aria-label="Variants for ${esc(section.name)}" placeholder=">Variant A\nACGT…\n>Variant B\nACGT…" title="Each record replaces only this highlighted dynamic region. Constant flanks and order are preserved.">${esc(section.variant_text||'')}</textarea><small class="muted">FASTA · One record per alternative</small></details>`:''}`).join('');
    $('design-sections').querySelectorAll('[data-region-mode]').forEach(input=>input.onchange=()=>{const section=item.sections[Number(input.dataset.regionMode)];if(input.value==='constant'&&section.variants?.length){input.value='dynamic';$('design-section-error').textContent='Remove pasted variants before making this region Constant.';return;}section.mode=input.value;dirty();renderEditor();});
    $('design-sections').querySelectorAll('[data-variant-section]').forEach(input=>input.oninput=()=>{const section=item.sections[Number(input.dataset.variantSection)];section.variant_text=input.value;try{section.variants=parseVariants(input.value);$('design-section-error').textContent='';dirty();}catch(error){$('design-section-error').textContent=error.message;lastResult=null;$('design-download').disabled=true;}});
    $('design-sections').querySelectorAll('[data-section-remove]').forEach(button=>button.onclick=()=>{item.sections.splice(Number(button.dataset.sectionRemove),1);dirty();renderEditor();renderChain();});
  }
  function renderSites(){
    if(!$('design-insert-sites'))return;const node=preview?.entries.find(n=>n.id===activeEntry),sites=node?.sites||[];
    $('design-insert-sites').innerHTML=sites.length?sites.map(site=>`<button class="design-site-tag" type="button" data-site-start="${site.start}" data-site-end="${site.end}" title="${esc(site.motif)} · ${site.strand===1?'Forward':'Reverse'}">${esc(site.enzyme)} · ${site.start+1}–${site.end}</button>`).join(''):'<span class="small muted">'+(node?'No sites in the common Type II panel':'')+'</span>';
    $('design-insert-sites').querySelectorAll('[data-site-start]').forEach(button=>button.onclick=()=>{$('design-section-start').value=Number(button.dataset.siteStart)+1;$('design-section-end').value=button.dataset.siteEnd;$('design-sequence').focus();});
  }
  function renderChecks(result){
    $('design-checks').innerHTML=[...(result.errors||[]).map(message=>`<div class="reaction-warning">${esc(message)}</div>`),...(result.warnings||[]).map(message=>`<div class="small muted">${esc(message)}</div>`)].join('');
    renderChain();renderSites();tableUI.refreshConstants();tableUI.setResult(result);
    const selection=window.getSelection();if(!$('design-sequence')?.contains(selection?.anchorNode)||selection?.isCollapsed)renderSequence();
  }
  function renderOutput(result){
    clearAssemblyPreview();
    const assembly=result.assembly;
    const summary=assembly?`<div class="design-result-summary"><strong class="${result.valid?'design-pass':'reaction-warning'}">${result.valid?'✓ Pass':'! Fail'}</strong><span>${assembly.length.toLocaleString()} bp · ${assembly.circular?'Circular':'Linear'} · ${assembly.gc.toFixed(2)}% GC</span><span>${result.generated.length} new fragments · ${result.assemblies?.length||1} assemblies</span></div><div id="design-assembly-preview"></div>`:'';
    $('design-output').innerHTML=root.DesignOverhangs.render(result.overhang_report,label)+summary+(result.generated.length?`<div class="table-scroll"><table class="design-generated"><thead><tr><th>Fragment</th><th>Region</th><th>Target / Full nt</th><th>GC %</th><th>5′</th><th>3′</th><th>Reference bases</th><th>Sequence</th></tr></thead><tbody>${result.generated.map((row,index)=>`<tr><td>${esc(row.name)}</td><td>${row.region_mode==='dynamic'?'Dynamic':'Constant'}${row.variant_name?' · '+esc(row.variant_name):''}</td><td>${row.target_length??row.target.length} / ${row.length}${row.padding_length?'<small class="muted"> · +'+row.padding_length+' bp padding</small>':''}</td><td>${row.gc.toFixed(2)}</td><td>${label(row.left_overhang)}</td><td>${label(row.right_overhang)}</td><td>${row.source_start+1}–${row.source_end}</td><td><details><summary>Target</summary><pre>${esc(row.target_sequence??row.target)}</pre></details><details><summary>Full${row.padding_length?' · includes 3′ padding':''}</summary><pre>${esc(row.full_sequence??row.sequence)}</pre><button type="button" class="text-button" data-design-copy="${index}">Copy</button></details></td></tr>`).join('')}</tbody></table></div>`:'<span class="small muted">No generated fragments</span>')+(result.boundary_shifts.length?`<details><summary>Boundaries</summary><div class="design-boundary-list">${result.boundary_shifts.map(b=>`<span>${b.requested+1} → ${b.actual+1} ${label(b.overhang)}${b.actual!==b.requested?' · '+(b.actual-b.requested>0?'+':'')+(b.actual-b.requested)+' nt':''}</span>`).join('')}</div></details>`:'')+(result.assemblies?.length>1?`<details><summary>Variant assemblies (${result.assemblies.length})</summary>${result.assemblies.map(item=>`<details class="design-product"><summary>${esc(item.name)} · ${item.length.toLocaleString()} bp</summary><pre class="design-final-sequence">${esc(item.sequence)}</pre></details>`).join('')}</details>`:'')+(assembly?`<details><summary>Assembly sequence</summary><pre class="design-final-sequence">${esc(assembly.sequence)}</pre></details>`:'');
    $('design-output').querySelectorAll('[data-design-copy]').forEach(button=>button.onclick=async()=>{try{await navigator.clipboard.writeText(result.generated[Number(button.dataset.designCopy)].sequence);button.textContent='Copied';}catch{note('Select the sequence to copy.',true);}});
    if(assembly?.sequence)assemblyPreview=root.JunctionSequenceViewer.preview($('design-assembly-preview'),root.DesignPreview.assembly(result));
    $('design-download').disabled=!result.valid;
  }
  async function check(generate){
    if(!ready||!current()||(!generate&&(generating||lastResult)))return;clearTimeout(checkTimer);const token=++requestRevision,designId=current().id;
    if(generate){generating=true;$('design-generate').disabled=true;note('Generating…');}
    try{
      const response=await request('/api/design/preview?generate='+generate,payload()),result=await response.json();
      if(token!==requestRevision||designId!==current().id)return;
      preview=result;renderChecks(result);if(generate){lastResult=result;renderOutput(result);if(result.valid&&!result.generated.length)$('design-export-format').value='gb';note(result.valid?'Generated · Private sandbox':'Resolve design errors',!result.valid);}
    }catch(error){if(token===requestRevision){$('design-checks').textContent=error.message;note(error.message,true);}}
    finally{if(token===requestRevision){generating=false;$('design-generate').disabled=false;}}
  }
  function render(){renderFields();renderReferences();renderChain();renderEditor();$('design-download').disabled=!lastResult?.valid;}
  function addPlaceholder(at=current().entries.length){
    const item={id:uid(),kind:'placeholder',name:'Insert '+(current().entries.filter(e=>e.kind==='placeholder').length+1),sequence:'',sections:[]};current().entries.splice(at,0,item);activeEntry=item.id;preview=null;dirty();render();
  }
  function chooseDesign(id){saved.activeId=id;activeEntry=current().entries.find(item=>item.kind==='placeholder')?.id||null;lastResult=null;preview=null;dirty();render();loadReferences();}
  $('design-new').onclick=()=>{if(saved.designs.length>=20){note('Use at most 20 designs in one sandbox.',true);return;}const d=fresh();saved.designs.push(d);chooseDesign(d.id);};
  $('design-saved').onchange=event=>chooseDesign(event.target.value);
  $('design-name').oninput=event=>{current().name=event.target.value||'New design';dirty();renderSaved();$('design-card-title').textContent=current().name;};
  $('design-enzyme').onchange=event=>{current().enzyme=event.target.value;current().slot_id=null;refs=null;preview=null;dirty();render();loadReferences();};
  $('design-backbone').onchange=event=>{const d=current();d.backbone_id=Number(event.target.value)||null;d.slot_id=chosenBackbone()?.slots[0]?.id||null;preview=null;dirty();render();};
  $('design-slot').onchange=event=>{current().slot_id=event.target.value||null;preview=null;dirty();renderChain();tableUI.render();};
  $('design-backbone-cards').onclick=event=>{const view=event.target.closest('[data-design-view-bb]');if(view){root.JunctionSequenceViewer.openPlasmid(Number(view.dataset.designViewBb));return;}const button=event.target.closest('[data-design-bb]');if(!button)return;const d=current();d.backbone_id=Number(button.dataset.designBb);d.enzyme=button.dataset.mode;d.slot_id=button.dataset.slot;refs=null;preview=null;dirty();renderFields();loadReferences();};
  $('design-add-placeholder').onclick=()=>addPlaceholder();
  $('design-fragment-search').oninput=()=>{searchRevision++;clearTimeout(searchTimer);if(!$('design-fragment-search').value.trim())$('design-search-results').classList.add('hidden');else searchTimer=setTimeout(renderSearch,150);};
  $('design-fragment-search').onkeydown=event=>{if(event.key==='ArrowDown'){$('design-search-results').querySelector('button:not(:disabled)')?.focus();event.preventDefault();}if(event.key==='Escape'){searchRevision++;clearTimeout(searchTimer);$('design-search-results').classList.add('hidden');}};
  $('design-search-results').onclick=event=>{const button=event.target.closest('[data-design-add]');if(!button)return;const fragment=refs.fragments.find(f=>f.id===Number(button.dataset.designAdd));searchRevision++;current().entries.push({id:uid(),kind:'fragment',fragment_id:fragment.id,name:fragment.name});$('design-fragment-search').value='';$('design-search-results').classList.add('hidden');preview=null;dirty();renderChain();tableUI.render();};
  async function viewEntry(id){
    const designId=current().id,version=revision,item=current().entries.find(entry=>entry.id===id),body=payload();
    body.use_table=false;body.table_rows=[];body.entries=body.entries.map(entry=>({...entry,sections:entry.sections?.map(section=>({...section,variants:[]}))}));
    try{
      const response=await request('/api/design/preview',body),result=await response.json();
      if(current().id!==designId||revision!==version)return;
      const node=result.entries.find(node=>node.id===id),fusion=result.runs.find(run=>run.index===node?.run)||{};
      await root.JunctionSequenceViewer.open(root.DesignPreview.record({...item,reverse:node.kind==='fragment'&&!!node.reverse},node,current().enzyme,fusion));
    }catch(error){note(error.message,true);}
  }
  $('design-chain').onclick=event=>{
    const view=event.target.closest('[data-design-view]');if(view){viewEntry(view.dataset.designView);return;}
    const gap=event.target.closest('[data-placeholder-at]');if(gap){addPlaceholder(Number(gap.dataset.placeholderAt));return;}
    const remove=event.target.closest('[data-design-remove]'),select=event.target.closest('[data-design-entry]');
    if(remove){current().entries=current().entries.filter(item=>item.id!==remove.dataset.designRemove);preview=null;dirty();renderChain();renderEditor();}
    else if(select){activeEntry=select.dataset.designEntry;renderChain();renderEditor();}
  };
  $('design-chain').ondragstart=event=>{dragId=event.target.closest('[data-entry-id]')?.dataset.entryId;if(dragId)event.dataTransfer.setData('text/plain',dragId);};
  $('design-chain').ondragover=event=>{if(event.target.closest('[data-entry-id]'))event.preventDefault();};
  $('design-chain').ondrop=event=>{event.preventDefault();const target=event.target.closest('[data-entry-id]')?.dataset.entryId,items=current().entries;if(!dragId||!target)return;current().entries=moveEntry(items,items.findIndex(item=>item.id===dragId),items.findIndex(item=>item.id===target));dragId=null;preview=null;dirty();renderChain();tableUI.render();};
  $('design-chain').onkeydown=event=>{if(!event.altKey||!['ArrowLeft','ArrowRight'].includes(event.key))return;const id=event.target.closest('[data-entry-id]')?.dataset.entryId,index=current().entries.findIndex(item=>item.id===id);if(index<0)return;event.preventDefault();current().entries=moveEntry(current().entries,index,index+(event.key==='ArrowRight'?1:-1));preview=null;dirty();renderChain();tableUI.render();$('design-chain').querySelector(`[data-design-entry="${CSS.escape(id)}"]`)?.focus();};
  for(const[id,key]of Object.entries({'design-left':'left_overhang','design-right':'right_overhang','design-window':'window','design-adapter':'adapter_enzyme'})){const field=$(id);field.onchange=event=>{current()[key]=key==='window'?Number(event.target.value):event.target.value.toUpperCase();if(key==='adapter_enzyme')current()[key]=event.target.value;dirty();};if(field.tagName==='INPUT')field.oninput=field.onchange;}
  $('design-excluded').onchange=event=>{current().excluded_overhangs=event.target.value.toUpperCase().split(/[\s,;]+/).filter(Boolean);dirty();};
  $('design-avoid').onchange=()=>{current().avoid_sites=[...$('design-avoid').querySelectorAll('input:checked')].map(input=>input.value);dirty();};
  $('design-twist-compatible').onchange=event=>{current().make_twist_compatible=event.target.checked;$('design-twist-help').hidden=!event.target.checked;dirty();};
  $('design-add-re').onchange=event=>{current().include_re_sites=event.target.checked;dirty();};
  for(const[id,key]of Object.entries({'design-left-enzyme':'left_adapter_enzyme','design-right-enzyme':'right_adapter_enzyme'}))$(id).onchange=event=>{current()[key]=event.target.value||null;dirty();};
  $('design-generate').onclick=()=>check(true);
  async function downloadDesign(format,example=false){
    if(!example&&!lastResult?.valid)return;
    const button=$(example?'design-example':'design-download'),body=exportPayload(current(),!!current().reverse_output,example);button.disabled=true;
    try{await root.JunctionSandbox.flush();const response=await request('/api/design/export?format='+format,body),blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1]||'Design.'+format;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),3000);}catch(error){note(error.message,true);}finally{button.disabled=example?false:!lastResult?.valid;}
  }
  $('design-export-rc').onchange=event=>{current().reverse_output=event.target.checked;persist();};
  $('design-example').onclick=()=>downloadDesign('example_gb',true);
  $('design-download').onclick=()=>downloadDesign($('design-export-format').value);
  document.addEventListener('click',event=>{if(!event.target.closest('.design-search-wrap')){searchRevision++;clearTimeout(searchTimer);$('design-search-results').classList.add('hidden');}});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'){searchRevision++;clearTimeout(searchTimer);$('design-search-results').classList.add('hidden');}});
  root.JunctionDesign={
    snapshot:()=>JSON.parse(JSON.stringify(saved)),
    restore(data){
      if(data&&Array.isArray(data.designs)&&data.designs.length){saved=JSON.parse(JSON.stringify(data));saved.designs=saved.designs.filter(d=>d&&typeof d.id==='string'&&Array.isArray(d.entries)).map(d=>({include_re_sites:true,reverse_output:false,make_twist_compatible:false,left_adapter_enzyme:null,right_adapter_enzyme:null,use_table:false,table_rows:[],...d}));}
      if(!saved.designs.length)saved={designs:[fresh()],activeId:null};
      if(!saved.designs.some(d=>d.id===saved.activeId))saved.activeId=saved.designs[0].id;
      activeEntry=current().entries.find(item=>item.kind==='placeholder')?.id||null;ready=true;render();
    },
    open(){if(!ready)return;render();loadReferences();}
  };
})(typeof window==='object'?window:globalThis);
