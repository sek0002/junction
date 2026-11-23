/* Local mRNA batch design, comparisons, and nucleotide-resolved fold exploration. */
(function(root,factory){const lib=factory();if(typeof module==='object'&&module.exports)module.exports=lib;else root.JunctionMRNA=lib.setup(root,document);})(typeof window==='object'?window:globalThis,()=>{
 'use strict';
 const escape=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const normalize=s=>String(s).replace(/\s/g,'').toUpperCase().replace(/U/g,'T');
 function hamming(a,b){a=normalize(a);b=normalize(b);if(a.length!==b.length||!a.length)return null;let n=0;for(let i=0;i<a.length;i++)if(a[i]!==b[i])n++;return n/a.length;}
 function csvRows(text,delimiter=','){
  const rows=[];let row=[],field='',quoted=false;
  for(let i=0;i<text.length;i++){const c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){field+='"';i++;}else quoted=!quoted;}else if(c===delimiter&&!quoted){row.push(field);field='';}else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&text[i+1]==='\n')i++;row.push(field);if(row.some(x=>x.trim()))rows.push(row);row=[];field='';}else field+=c;}
  if(quoted)throw Error('Unclosed quoted field in CSV.');row.push(field);if(row.some(x=>x.trim()))rows.push(row);return rows;
 }
 function parse(text,filename='sequences.fasta'){
  text=String(text).replace(/^\uFEFF/,'').trim();if(!text)throw Error('The input file is empty.');
  const infer=seq=>/^[ACGTU\s]+$/i.test(seq)?'nucleotide':'protein';
  if(text.startsWith('>')){const records=[];let current=null;for(const line of text.split(/\r?\n/)){if(line.startsWith('>')){current={name:line.slice(1).trim()||'Sequence '+(records.length+1),sequence:''};records.push(current);}else if(line.trim()&&!line.startsWith(';')){if(!current)throw Error('FASTA sequence is missing a header.');current.sequence+=line.trim();}}return records.map(r=>({...r,kind:/\.faa$/i.test(filename)?'protein':infer(r.sequence)}));}
  const delimiter=/\.tsv$/i.test(filename)||text.split(/\r?\n/)[0].includes('\t')?'\t':',';
  if(text.split(/\r?\n/)[0].includes(delimiter)){const rows=csvRows(text,delimiter),header=rows.shift().map(x=>x.trim().toLowerCase()),si=header.findIndex(x=>['sequence','cds','cds_sequence','protein'].includes(x)),ni=header.findIndex(x=>['name','id','tx_id'].includes(x)),ki=header.indexOf('kind'),gi=header.indexOf('group');if(si<0)throw Error('CSV needs a sequence or cds column; name, kind and group are optional.');return rows.map((row,i)=>({name:row[ni]?.trim()||'Sequence '+(i+1),sequence:row[si]||'',kind:row[ki]?.trim()||infer(row[si]||''),group:row[gi]?.trim()||'Multiplex 1'}));}
  return [{name:filename.replace(/\.[^.]+$/,''),sequence:text,kind:infer(text)}];
 }
 function csvCell(value){if(typeof value==='number'&&Number.isFinite(value))return String(value);let s=String(value??'');if(/^[=+@\-\t\r]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"';}
 function stabilityColor(score,low,high){
  if(!Number.isFinite(score))return '#aab7b0';
  const t=high>low?Math.max(0,Math.min(1,(score-low)/(high-low))):.5;
  const stops=[[42,157,143],[234,214,141],[215,106,89]],a=t<=.5?stops[0]:stops[1],b=t<=.5?stops[1]:stops[2],f=t<=.5?t*2:(t-.5)*2;
  return '#'+a.map((x,i)=>Math.round(x+(b[i]-x)*f).toString(16).padStart(2,'0')).join('');
 }
 function foldRange(row,start,end){
  const offset=row.fold_scope==='transcript'?row.regions.cds[0]-1:0;
  start=Math.max(1,Math.min(row.cds.length,Math.round(start)));end=Math.max(start,Math.min(row.cds.length,Math.round(end)));
  return {start,end,fold_start:start+offset,fold_end:end+offset};
 }
 function gcWindowForBase(row,position){
  const offset=row.fold_scope==='transcript'?row.regions.cds[0]-1:0,cdsPosition=position-offset;
  if(cdsPosition<1||cdsPosition>row.cds.length)return null;
  const window=Math.min(row.gc_window,row.cds.length),start=Math.max(1,Math.min(row.cds.length-window+1,Math.round(cdsPosition-(window-1)/2)));
  return {...foldRange(row,start,start+window-1),focus:position,gc:row.gc_profile.find(p=>p[0]===start)?.[1]??null};
 }
 const metricSpecs=[['length','CDS nt'],['gc','GC %'],['cai','CAI'],['tai','tAI'],['mfe','MFE'],['mfe_density','MFE / nt'],['predicted_half_life','Pred. half-life'],['csc','CSC'],['translation','Translation'],['hamming_ratio','Δ input']];
 function columnStats(rows,getValue){
  const values=rows.map(getValue).filter(Number.isFinite),n=values.length;
  if(!n)return {n:0,mean:0,sd:0,min:null,max:null};
  const mean=values.reduce((a,b)=>a+b,0)/n,sd=Math.sqrt(values.reduce((sum,x)=>sum+(x-mean)**2,0)/n);
  return {n,mean,sd,min:Math.min(...values),max:Math.max(...values)};
 }
 const zScore=(value,stats)=>Number.isFinite(value)&&stats.n?(stats.sd>1e-12?(value-stats.mean)/stats.sd:0):null;
 function zColor(z){if(!Number.isFinite(z))return 'transparent';const t=Math.min(1,Math.abs(z)/2),a=[245,245,239],b=z<0?[134,183,210]:[214,145,139];return '#'+a.map((x,i)=>Math.round(x+(b[i]-x)*t).toString(16).padStart(2,'0')).join('');}
 function matchedPairs(rows){return rows.filter(r=>r.strategy!=='input').map(after=>({after,before:rows.find(r=>r.strategy==='input'&&r.input_name===after.input_name&&r.group===after.group)})).filter(p=>p.before);}
 function gcSeries(rows,grouped=false){
  if(!grouped)return rows.map(r=>({id:r.id,name:r.name,group:r.group,strategy:r.strategy,rows:[r],points:r.gc_profile.map(([start,gc])=>({x:start+(r.gc_window-1)/2,gc,start,end:start+r.gc_window-1,n:1,min:gc,max:gc}))}));
  const groups=new Map();
  for(const r of rows){const key=JSON.stringify([r.group,r.strategy]);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(r);}
  return [...groups].map(([key,members])=>{const points=new Map();for(const r of members)for(const [start,gc]of r.gc_profile){const x=start+(r.gc_window-1)/2;if(!points.has(x))points.set(x,[]);points.get(x).push({gc,start,end:start+r.gc_window-1});}return {id:'group:'+key,name:members[0].group+' · '+members[0].strategy,group:members[0].group,strategy:members[0].strategy,rows:members,points:[...points].sort((a,b)=>a[0]-b[0]).map(([x,p])=>({x,gc:p.reduce((n,q)=>n+q.gc,0)/p.length,n:p.length,min:Math.min(...p.map(q=>q.gc)),max:Math.max(...p.map(q=>q.gc)),start:Math.min(...p.map(q=>q.start)),end:Math.max(...p.map(q=>q.end))}))};});
 }
 function arcGeometry(row,position=1,size=150){
  const length=row.fold_sequence.length,width=size==='all'?length:Math.min(length,Number(size)||150),start=Math.max(1,Math.min(length-width+1,Math.round(position-width/2))),end=start+width-1,step=size==='all'?900/Math.max(1,length-1):6;
  const x=p=>36+(p-start)*step,maxSpan=Math.max(1,...row.pairs.filter(([a,b])=>a<=end&&b>=start).map(([a,b])=>Math.min(b,end)-Math.max(a,start)));
  return {start,end,width,step,x,maxSpan,box:[0,0,Math.max(180,(width-1)*step+72),340]};
 }
 function setup(win,doc){
  const $=id=>doc.getElementById('mrna-'+id), host=$('records');
  const fields=['name','organism','objective','gc-min','gc-max','window','local-min','local-max','repeat','au-run','cg-run','hairpin-stem','hairpin-window','enzymes','motifs','uridine','slip','manufacture','utr5','utr3','poly-a','fold-scope','temperature','candidates','seed','translation'];
  const defaults=Object.fromEntries(fields.map(id=>[id,$(id).type==='checkbox'?$(id).checked:$(id).value]));
  let knownRows=new Set();
  let records=[],results={rows:[],errors:[]},selected=new Set(),focus=null,job=null,tab='batch',timer=null,generation=0,cap=null,opening=null,sequenceId=0,sort={key:'name',direction:1},busy=false,base=1,viewbox=null,coords=[],linkedHover=null;
  const profileRequests=new Map(),profileStatus=new WeakMap();
  let gcHidden=new Set(),overlaySeries=[],overlayMax=1,radarKeys=new Set(['gc','cai','tai','mfe_density','predicted_half_life','csc']),radarCandidate='',arcRange=null;
  const colors=['#338d78','#c08d41','#7e6db5','#4094bb','#b56676','#7c994b','#cc754a','#6477a1'];
  const value=id=>$(id).type==='checkbox'?$(id).checked:$(id).value;
  const n=id=>$(id).value===''?null:Number($(id).value);
  const showError=message=>{$('error').textContent=message||'';$('error').hidden=!message;};
  const number=(x,d=3)=>x===null||x===undefined?'—':Number(x).toLocaleString(undefined,{maximumFractionDigits:d});
  const save=()=>win.JunctionSandbox?.schedule();
  async function request(url,options={}){const response=await win.fetch(url,options);let data;try{data=await response.json();}catch{throw Error('The server returned an invalid response.');}if(!response.ok){const detail=data.detail;throw Error(typeof detail==='string'?detail:Array.isArray(detail)?detail.map(x=>x.msg).join(' '):'The request failed.');}return data;}
  const post=data=>({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  function add(record={}){records.push({id:'input-'+(++sequenceId),name:'Sequence '+sequenceId,sequence:'',kind:'nucleotide',group:'Multiplex 1',override:false,organism:'',objective:'',gc_min:'',gc_max:'',utr5:'',utr3:'',custom_utrs:false,preserve:'',...record,id:'input-'+sequenceId});}
  function renderRecords(){host.innerHTML=records.map(r=>`<article class="mrna-record" data-record="${escape(r.id)}"><div class="mrna-record-heading"><label>Name<input data-field="name" maxlength="120" value="${escape(r.name)}" aria-label="Sequence name"></label><label>Input type<select data-field="kind"><option value="nucleotide" ${r.kind==='nucleotide'?'selected':''}>DNA / RNA</option><option value="protein" ${r.kind==='protein'?'selected':''}>Protein</option></select></label><button data-remove type="button" aria-label="Remove ${escape(r.name)}">×</button></div><textarea data-field="sequence" rows="4" spellcheck="false" aria-label="Coding sequence for ${escape(r.name)}" placeholder="Paste a complete coding sequence">${escape(r.sequence)}</textarea><div class="mrna-record-info"><span data-length>${normalize(r.sequence).length.toLocaleString()} ${r.kind==='protein'?'aa':'nt'}</span><span>CDS only</span></div><details><summary>Input-specific parameters</summary><label>Multiplex set<input data-field="group" value="${escape(r.group)}" maxlength="100"></label><label class="mrna-check"><input type="checkbox" data-field="override" ${r.override?'checked':''}>Override batch optimisation</label><div class="mrna-fields"><label>Organism<select data-field="organism"><option value="">Batch setting</option><option value="homo-sapiens" ${r.organism==='homo-sapiens'?'selected':''}>Human</option><option value="mus-musculus" ${r.organism==='mus-musculus'?'selected':''}>Mouse</option></select></label><label>Objective<select data-field="objective"><option value="">Batch setting</option><option value="cai" ${r.objective==='cai'?'selected':''}>MaxCAI</option><option value="tai" ${r.objective==='tai'?'selected':''}>MaxtAI · human</option></select></label><label>Global GC min (%)<input type="number" min="0" max="100" data-field="gc_min" placeholder="Batch setting" value="${escape(r.gc_min)}"></label><label>Global GC max (%)<input type="number" min="0" max="100" data-field="gc_max" placeholder="Batch setting" value="${escape(r.gc_max)}"></label></div><label>Preserve CDS regions<input data-field="preserve" value="${escape(r.preserve)}" placeholder="1-60, 301-360 · inclusive codon-aligned nt"></label><label class="mrna-check"><input type="checkbox" data-field="custom_utrs" ${r.custom_utrs?'checked':''}>Use input-specific UTRs</label><label>5′ UTR + Kozak<textarea data-field="utr5" rows="2">${escape(r.utr5)}</textarea></label><label>3′ UTR<textarea data-field="utr3" rows="2">${escape(r.utr3)}</textarea></label></details></article>`).join('');}
  host.addEventListener('input',event=>{const item=event.target.closest('[data-record]'),key=event.target.dataset.field;if(!item||!key)return;const record=records.find(r=>r.id===item.dataset.record);record[key]=event.target.type==='checkbox'?event.target.checked:event.target.value;item.querySelector('[data-length]').textContent=normalize(record.sequence).length.toLocaleString()+' '+(record.kind==='protein'?'aa':'nt');save();});
  host.addEventListener('change',event=>{if(event.target.matches('select'))event.target.dispatchEvent(new Event('input',{bubbles:true}));});
  host.addEventListener('click',event=>{if(event.target.closest('[data-remove]')){records=records.filter(r=>r.id!==event.target.closest('[data-record]').dataset.record);renderRecords();save();}});
  function parameters(){return {organism:value('organism'),objective:value('objective'),gc_global_min:n('gc-min')/100,gc_global_max:n('gc-max')/100,gc_window_min:n('local-min')/100,gc_window_max:n('local-max')/100,gc_window_size:n('window'),avoid_repeat_length:n('repeat'),avoid_poly_a:n('au-run'),avoid_poly_t:n('au-run'),avoid_poly_c:n('cg-run'),avoid_poly_g:n('cg-run'),hairpin_stem_size:n('hairpin-stem'),hairpin_window:n('hairpin-window'),enable_uridine_depletion:value('uridine'),avoid_ribosome_slip:value('slip'),avoid_manufacture_restriction_sites:value('manufacture'),avoid_restriction_sites:value('enzymes').split(/[,;\s]+/).filter(Boolean),avoid_sequences:value('motifs').split(/[,;\s]+/).filter(Boolean)};}
  function payload(mode){const common=parameters();return {name:value('name')||'mRNA design batch',mode,parameters:common,candidates:n('candidates'),five_prime_utr:value('utr5'),three_prime_utr:value('utr3'),poly_a:n('poly-a'),fold_scope:value('fold-scope'),temperature:n('temperature'),seed:n('seed'),predict_translation:value('translation'),records:records.map(r=>{let ranges=[];if(r.preserve.trim())ranges=r.preserve.split(',').map(x=>{const match=x.trim().match(/^(\d+)\s*-\s*(\d+)$/);if(!match)throw Error('Preserved regions must look like 1-60, 301-360.');return [Number(match[1]),Number(match[2])];});return {name:r.name,sequence:r.sequence,kind:r.kind,group:r.group,preserve_regions:ranges,five_prime_utr:r.custom_utrs?r.utr5:null,three_prime_utr:r.custom_utrs?r.utr3:null,parameters:r.override?{...common,organism:r.organism||common.organism,objective:r.objective||common.objective,...(r.gc_min!==''?{gc_global_min:Number(r.gc_min)/100}:{}),...(r.gc_max!==''?{gc_global_max:Number(r.gc_max)/100}:{})}:null};})};}
  function switchTab(next){tab=['batch','compare','structure'].includes(next)?next:'batch';for(const t of ['batch','compare','structure']){$(t+'-panel').hidden=t!==tab;$(t+'-tab').classList.toggle('active',t===tab);$(t+'-tab').setAttribute('aria-selected',String(t===tab));}if(tab==='structure')drawStructure();save();}
  doc.querySelectorAll('[data-mrna-tab]').forEach((button,index,list)=>{button.onclick=()=>switchTab(button.dataset.mrnaTab);button.onkeydown=e=>{if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();const target=list[(index+(e.key==='ArrowRight'?1:list.length-1))%list.length];target.focus();target.click();}};});
  function setBusy(on){busy=on;for(const id of ['run','analyse'])$(id).disabled=on||!cap?.ready;$('cancel').classList.toggle('hidden',!on);}
  async function loadHistory(){const previous=value('history'),data=await request('/api/mrna/jobs');$('history').innerHTML='<option value="">Choose a saved batch</option>'+data.items.map(x=>`<option value="${escape(x.id)}">${escape(x.name)} · ${escape(x.status)} · ${escape(x.created_at)}</option>`).join('');$('history').value=previous;return data;}
  async function open(){if(opening)return opening;opening=(async()=>{try{cap=await request('/api/mrna/capabilities');$('engine-status').textContent=cap.message||'Local models';$('models').innerHTML=Object.entries({mRNArchitect:'mRNArchitect '+(cap.versions?.mRNArchitect||''),viennarna:'ViennaRNA '+(cap.versions?.ViennaRNA||''),degscore:'DegScore · half-life',csc:'Codon stability',ribonn:'RiboNN · translation'}).map(([key,label])=>`<span class="${cap.models?.[key]?'ready':''}">${escape(label)}${cap.models?.[key]?'':' · not connected'}</span>`).join('');$('translation').disabled=!cap.models?.ribonn;$('translation-help').textContent=cap.models?.ribonn?'Local RiboNN ensemble. Select a UTR preset or provide both UTRs; include a terminal stop codon.':'RiboNN trained model is not connected. Other metrics are available.';if(!cap.models?.ribonn)$('translation').checked=false;$('preset').innerHTML='<option value="">Custom / no UTRs</option>'+(cap.elements||[]).map((x,i)=>`<option value="${i}">${escape(x.name)}</option>`).join('');setBusy(busy);const history=await loadHistory();if(job&&history.items.some(x=>x.id===job&&['queued','running'].includes(x.status))){setBusy(true);poll(generation);}}catch(error){showError(error.message);opening=null;}})();return opening;}
  async function start(mode){showError('');if(busy)return;try{if(!records.length)throw Error('Add at least one sequence.');const data=payload(mode);setBusy(true);$('progress').textContent='Starting batch…';const run=await request('/api/mrna/jobs',post(data));generation++;job=run.id;results={rows:[],errors:[]};selected=new Set();gcHidden.clear();knownRows=new Set();focus=null;renderResults();save();poll(generation);}catch(error){setBusy(false);showError(error.message);}}
  async function poll(token){clearTimeout(timer);try{const data=await request('/api/mrna/jobs/'+encodeURIComponent(job));if(token!==generation)return;const active=['queued','running'].includes(data.status);results=data.result||{rows:[],errors:[]};results.rows??=[];results.errors??=[];for(const r of results.rows)if(!knownRows.has(r.id)){selected.add(r.id);knownRows.add(r.id);}if(!focus&&results.rows.length)focus=results.rows[0].id;$('progress').textContent=data.status==='complete'?'Batch complete':data.status==='partial'?'Batch complete with sequence errors':data.status==='failed'?'Batch failed':data.status==='cancelled'?'Batch cancelled':`${data.completed} / ${data.total} inputs · ${data.status}`;$('progress-detail').textContent=active?'Local calculations continue if you leave this page.':`${results.rows.length} sequences scored. Inputs and settings are saved with this workbench.`;renderResults();setBusy(active);save();if(active)timer=win.setTimeout(()=>poll(token),1000);else{await loadHistory();if(results.rows.length)switchTab('compare');if(data.error)showError(data.error);}}catch(error){if(token===generation){setBusy(false);showError(error.message);}}}
  const activeRow=()=>results.rows.find(r=>r.id===focus)||results.rows[0];
  const translationValue=row=>value('translation-cell')?row.tissue_predictions?.[value('translation-cell')]??null:row.metrics.translation;
  function renderResults(){if(!results.rows.some(r=>r.id===focus))focus=results.rows[0]?.id||null;const oldCell=value('translation-cell'),cells=[...new Set(results.rows.flatMap(r=>Object.keys(r.tissue_predictions||{})))].sort();$('translation-cell').innerHTML='<option value="">Translation: mean across cells</option>'+cells.map(cell=>`<option value="${escape(cell)}">${escape(cell.replace('predicted_TE_',''))}</option>`).join('');$('translation-cell').value=cells.includes(oldCell)?oldCell:'';$('translation-cell').hidden=!cells.length;const stats=Object.fromEntries(metricSpecs.map(([key])=>[key,columnStats(results.rows,r=>metricValue(r,key))]));let rows=[...results.rows];rows.sort((a,b)=>{const x=sort.key==='name'?a.name:sort.key==='translation'?translationValue(a):a.metrics[sort.key],y=sort.key==='name'?b.name:sort.key==='translation'?translationValue(b):b.metrics[sort.key];if(x==null)return y==null?0:1;if(y==null)return -1;return (typeof x==='string'?x.localeCompare(y):x-y)*sort.direction;});$('result-count').textContent=rows.length;$('export').disabled=!rows.length;$('results').innerHTML=rows.length?rows.map(r=>{const m=r.metrics;return `<tr class="${r.id===focus?'mrna-focused':''}"><td><input type="checkbox" data-result="${escape(r.id)}" ${selected.has(r.id)?'checked':''} aria-label="Select ${escape(r.name)}"></td><td><button data-explore="${escape(r.id)}">${escape(r.name)}</button><small>${escape(r.group)}${r.warnings?.length?' · '+r.warnings.length+' notes':''}</small></td><td>${escape(r.strategy)}</td>${metricSpecs.map(([key])=>metricCell(r,key,stats[key])).join('')}<td>${m.protein_preserved?'Preserved':'Changed'}</td></tr>`;}).join(''):'<tr><td colspan="14" class="mrna-empty">Compare or design a batch to see its metrics.</td></tr>';$('focus').innerHTML=results.rows.map(r=>`<option value="${escape(r.id)}">${escape(r.name)}</option>`).join('');$('focus').value=focus||'';$('sequence-errors').innerHTML=(results.errors||[]).map(x=>`<p class="mrna-error"><strong>${escape(x.name)}</strong>: ${escape(x.error)}</p>`).join('');$('select-all').checked=rows.length>0&&rows.every(r=>selected.has(r.id));drawComparison();if(tab==='structure')drawStructure();}
  function gcSVG(rows,detail=false){if(!rows.length)return '<p class="small muted">Select calculated sequences to show their GC profiles.</p>';const w=650,h=210,left=42,right=18,top=14,bottom=32,max=Math.max(...rows.map(r=>r.cds.length)),x=p=>left+(p-1)/Math.max(1,max-1)*(w-left-right),y=v=>top+(1-v)*(h-top-bottom),p=rows[0].parameters;let html=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Sliding-window GC content across coding sequences"><rect x="${left}" y="${top}" width="${w-left-right}" height="${y(p.gc_window_max)-top}" fill="#d6a05a" opacity=".10"/><rect x="${left}" y="${y(p.gc_window_min)}" width="${w-left-right}" height="${h-bottom-y(p.gc_window_min)}" fill="#6398b6" opacity=".10"/>`;for(const v of [0,.25,.5,.75,1])html+=`<path class="grid" d="M${left},${y(v)}H${w-right}"/><text x="${left-8}" y="${y(v)+3}" text-anchor="end">${v*100}%</text>`;for(const p of [1,Math.round(max/2),max])html+=`<text x="${x(p)}" y="${h-10}" text-anchor="middle">${p} nt</text>`;rows.forEach((r,i)=>{const points=r.gc_profile.filter((_,j)=>j%Math.max(1,Math.floor(r.gc_profile.length/1200))===0).map(([start,gc])=>`${x(start+(r.gc_window-1)/2)},${y(gc)}`).join(' ');html+=`<polyline points="${points}" fill="none" stroke="${colors[results.rows.indexOf(r)%colors.length]}" stroke-width="${detail?2.3:1.8}"><title>${escape(r.name)} · ${r.gc_window} nt windows</title></polyline>`;});if(detail)html+='<g data-gc-hover="true" pointer-events="none"></g>';if(detail&&activeRow()){const r=activeRow(),cdsPos=base-(r.fold_scope==='transcript'?r.regions.cds[0]-1:0);if(cdsPos>=1&&cdsPos<=r.cds.length)html+=`<path class="gc-selection-cursor" d="M${x(cdsPos)},${top}V${h-bottom}" stroke="var(--green)" stroke-dasharray="4 3"/>`;}return html+'</svg>';}
  const metricValue=(row,key)=>key==='translation'?translationValue(row):row.metrics[key];
  function metricCell(row,key,stats){
    const v=metricValue(row,key),z=zScore(v,stats),heat=value('heatmap'),digits=key==='length'?0:key==='gc'||key==='hamming_ratio'?1:key==='csc'?4:['mfe','predicted_half_life'].includes(key)?2:3;
    const text=number(Number.isFinite(v)&&['gc','hamming_ratio'].includes(key)?v*100:v,digits)+(key==='hamming_ratio'&&Number.isFinite(v)?'%':'');
    return `<td data-metric="${key}" ${z===null?'':`data-z="${z}"`} ${heat&&z!==null?`style="background:${zColor(z)};color:#243b3d"`:''} title="${escape(metricSpecs.find(m=>m[0]===key)[1])}: ${text}${z===null?' · unavailable':` · column z = ${number(z,3)} · n = ${stats.n}`}">${text}</td>`;
  }
  function drawComparison(){const rows=results.rows.filter(r=>selected.has(r.id));drawLandscape(rows);drawRadar();if(!rows.length){$('hamming').innerHTML='<p class="small muted">Select sequences above.</p>';return;}let html='<table class="mrna-hamming"><thead><tr><th></th>'+rows.map(r=>`<th scope="col" title="${escape(r.name)}">${escape(r.name)}</th>`).join('')+'</tr></thead><tbody>';for(const a of rows){html+=`<tr><th scope="row">${escape(a.name)}</th>`;for(const b of rows){const v=hamming(a.cds,b.cds),same=a.protein===b.protein;html+=`<td style="background:${v===null?'var(--subtle,#f5f7f3)':`rgba(61,143,118,${.06+v*.9})`}" title="${escape(a.name+' vs '+b.name)} · ${same?'same protein':'different proteins'}">${v===null?'n/a':v.toFixed(3)}${!same&&v!==null?'*':''}</td>`;}html+='</tr>';}$('hamming').innerHTML=html+'</tbody></table><small class="muted">* Different encoded proteins; divergence includes protein-changing differences.</small>';}
  const rowColor=r=>colors[Math.max(0,results.rows.indexOf(r))%colors.length];
  function drawLandscape(rows){
    const grouped=value('gc-mode')==='groups',visible=rows.filter(r=>!gcHidden.has(r.id));
    overlaySeries=gcSeries(visible,grouped);overlayMax=Math.max(1,...rows.map(r=>r.cds.length));
    const x=p=>42+(p-1)/Math.max(1,overlayMax-1)*590,y=v=>14+(1-v)*164;
    let svg='<svg viewBox="0 0 650 210" role="img" aria-label="GC landscape. Toggle samples in the legend. Hover a line to inspect its GC values.">';
    for(const v of [0,.25,.5,.75,1])svg+=`<path class="grid" d="M42,${y(v)}H632"/><text x="34" y="${y(v)+3}" text-anchor="end">${v*100}%</text>`;
    for(const p of [1,Math.round(overlayMax/2),overlayMax])svg+=`<text x="${x(p)}" y="200" text-anchor="middle">${p} nt</text>`;
    overlaySeries.forEach((series,i)=>{series.color=grouped?colors[[...new Set(results.rows.map(r=>r.group))].indexOf(series.group)%colors.length]:rowColor(series.rows[0]);const points=series.points.filter((_,j)=>j%Math.max(1,Math.floor(series.points.length/1500))===0).map(p=>`${x(p.x)},${y(p.gc)}`).join(' '),dash=grouped&&series.strategy==='input'?' stroke-dasharray="6 4"':'';svg+=`<polyline data-gc-series="${i}" points="${points}" fill="none" stroke="${series.color}" stroke-width="2"${dash}><title>${escape(series.name)}</title></polyline>`;});
    for(const series of overlaySeries)if(series.points.length===1){const p=series.points[0];svg+=`<circle cx="${x(p.x)}" cy="${y(p.gc)}" r="3" fill="${series.color}"/>`;}
    svg+='<g data-landscape-hover pointer-events="none"></g></svg>';
    $('overlay').innerHTML=rows.length?svg:'<p class="small muted">Select sequences in the table to show GC profiles.</p>';
    $('overlay-info').textContent=visible.length?`${visible.length} of ${rows.length} selected samples visible. ${grouped?'Group means separate input (dashed) and optimisation strategies (solid); each window reports its contributing sample count.':'Hover a line for its window, value and sample-specific target.'}`:'All selected samples are hidden. Enable a sample or group below.';
    const groups=[...new Set(rows.map(r=>r.group))];
    $('overlay-legend').innerHTML=groups.map((group,index)=>{const members=rows.filter(r=>r.group===group),count=members.filter(r=>!gcHidden.has(r.id)).length;return `<fieldset class="mrna-gc-group"><legend><label><input type="checkbox" data-gc-group="${index}" ${count===members.length?'checked':''}>${escape(group)} <small>${count}/${members.length}</small></label></legend>${members.map(r=>`<label><input type="checkbox" data-gc-sample="${escape(r.id)}" ${gcHidden.has(r.id)?'':'checked'}><i style="background:${grouped?colors[index%colors.length]:rowColor(r)}"></i><span>${escape(r.name)}</span><small>${escape(r.strategy)}</small></label>`).join('')}</fieldset>`;}).join('');
    for(const input of $('overlay-legend').querySelectorAll('[data-gc-group]')){const group=groups[Number(input.dataset.gcGroup)],members=rows.filter(r=>r.group===group),n=members.filter(r=>!gcHidden.has(r.id)).length;input.indeterminate=n>0&&n<members.length;input.dataset.groupName=group;}
  }
  $('overlay-legend').onchange=e=>{const hit=e.target;if(hit.dataset.gcSample){if(hit.checked)gcHidden.delete(hit.dataset.gcSample);else gcHidden.add(hit.dataset.gcSample);}else if(hit.dataset.gcGroup!==undefined){for(const r of results.rows.filter(r=>selected.has(r.id)&&r.group===hit.dataset.groupName)){if(hit.checked)gcHidden.delete(r.id);else gcHidden.add(r.id);}}else return;drawLandscape(results.rows.filter(r=>selected.has(r.id)));save();};
  $('gc-mode').onchange=()=>{drawLandscape(results.rows.filter(r=>selected.has(r.id)));save();};
  $('gc-show-all').onclick=()=>{gcHidden.clear();drawLandscape(results.rows.filter(r=>selected.has(r.id)));save();};
  function landscapeHover(event){
    const svg=$('overlay').querySelector('svg');if(!svg)return;
    const point=svg.createSVGPoint();point.x=event.clientX;point.y=event.clientY;const matrix=svg.getScreenCTM();if(!matrix)return;const p=point.matrixTransform(matrix.inverse()),layer=svg.querySelector('[data-landscape-hover]');
    if(p.x<42||p.x>632||p.y<14||p.y>178){clearLandscapeHover();return;}
    const cdsPosition=1+(p.x-42)/590*(overlayMax-1),hits=[];
    overlaySeries.forEach((series,i)=>{if(!series.points.length)return;const first=series.points[0],last=series.points.at(-1);if(cdsPosition<first.x-.5||cdsPosition>last.x+.5)return;let lo=0,hi=series.points.length-1;while(lo<hi){const mid=Math.floor((lo+hi)/2);if(series.points[mid].x<cdsPosition)lo=mid+1;else hi=mid;}let item=series.points[lo];if(lo>0&&Math.abs(series.points[lo-1].x-cdsPosition)<Math.abs(item.x-cdsPosition))item=series.points[lo-1];hits.push({series,i,item,distance:Math.abs(14+(1-item.gc)*164-p.y)});});
    hits.sort((a,b)=>a.distance-b.distance);const hit=hits[0];
    if(!hit){clearLandscapeHover();return;}
    for(const line of svg.querySelectorAll('[data-gc-series]')){line.classList.toggle('gc-active',Number(line.dataset.gcSeries)===hit.i);line.classList.toggle('gc-dimmed',Number(line.dataset.gcSeries)!==hit.i);}
    const {series,item}=hit,x=42+(item.x-1)/Math.max(1,overlayMax-1)*590,y=14+(1-item.gc)*164;
    layer.innerHTML=`<path class="mrna-gc-crosshair" d="M${x},14V178"/><circle cx="${x}" cy="${y}" r="4" fill="${series.color}" stroke="var(--surface,#fff)" stroke-width="2"/>`;
    const target=series.rows[0].parameters;
    $('overlay-info').innerHTML=`<strong>${escape(series.name)}</strong> · ${escape(series.group)} · CDS window ${item.start}–${item.end} · <strong>${number(item.gc*100,2)}% GC</strong>${value('gc-mode')==='groups'?` · n=${item.n} · range ${number(item.min*100,1)}–${number(item.max*100,1)}%`:` · ${escape(series.strategy)} · target ${number(target.gc_window_min*100,0)}–${number(target.gc_window_max*100,0)}%`}`;
  }
  function clearLandscapeHover(){const svg=$('overlay').querySelector('svg');if(!svg)return;svg.querySelector('[data-landscape-hover]')?.replaceChildren();svg.querySelectorAll('.gc-active,.gc-dimmed').forEach(line=>line.classList.remove('gc-active','gc-dimmed'));}
  $('overlay').onpointermove=landscapeHover;$('overlay').onpointerleave=clearLandscapeHover;
  $('heatmap').onchange=()=>{renderResults();save();};
  function drawRadar(){
    const pairs=matchedPairs(results.rows),old=value('radar-pair')||radarCandidate;
    $('radar-pair').innerHTML=pairs.map(p=>`<option value="${escape(p.after.id)}">${escape(p.after.group+' · '+p.after.name)}</option>`).join('');
    radarCandidate=pairs.some(p=>p.after.id===old)?old:pairs[0]?.after.id||'';$('radar-pair').value=radarCandidate;
    $('radar-parameters').innerHTML=metricSpecs.filter(([k])=>k!=='hamming_ratio').map(([key,label])=>`<label><input type="checkbox" data-radar-key="${key}" ${radarKeys.has(key)?'checked':''}>${escape(label)}</label>`).join('');
    const pair=pairs.find(p=>p.after.id===radarCandidate);
    if(!pair){$('radar-chart').innerHTML='<p class="mrna-empty">Design candidates to compare each optimised sequence with its matched input.</p>';$('radar-values').innerHTML='';$('radar-note').textContent='Candidates match to the original input name and multiplex set.';return;}
    const requested=metricSpecs.filter(([key])=>radarKeys.has(key)),axes=requested.filter(([key])=>Number.isFinite(metricValue(pair.before,key))&&Number.isFinite(metricValue(pair.after,key))),missing=requested.filter(a=>!axes.includes(a));
    $('radar-note').textContent=`${pair.before.input_name} · ${pair.before.group}. Each axis uses the full batch minimum–maximum; constant columns are centred. Larger radius means a larger value, not necessarily a better score.${missing.length?' Unavailable for this pair: '+missing.map(m=>m[1]).join(', ')+'.':''}`;
    $('radar-values').innerHTML='<table class="mrna-radar-values"><thead><tr><th>Parameter</th><th>Before</th><th>After</th><th>Δ</th></tr></thead><tbody>'+axes.map(([key,label])=>{const a=metricValue(pair.before,key),b=metricValue(pair.after,key),factor=key==='gc'?100:1;return `<tr><th>${escape(label)}</th><td>${number(a*factor,4)}</td><td>${number(b*factor,4)}</td><td>${b>a?'+':''}${number((b-a)*factor,4)}</td></tr>`;}).join('')+'</tbody></table>';
    if(axes.length<3){$('radar-chart').innerHTML='<p class="mrna-empty">Select at least three parameters with scores available for both sequences.</p>';return;}
    const center=[260,215],radius=140,point=(i,r)=>[center[0]+Math.cos(-Math.PI/2+i*2*Math.PI/axes.length)*radius*r,center[1]+Math.sin(-Math.PI/2+i*2*Math.PI/axes.length)*radius*r];
    let svg='<svg viewBox="0 0 520 430" role="img" aria-label="Matched input and optimised candidate radar comparison">';
    for(const level of [.25,.5,.75,1])svg+=`<polygon points="${axes.map((_,i)=>point(i,level).join(',')).join(' ')}" class="radar-grid"/>`;
    axes.forEach(([key,label],i)=>{const p=point(i,1),q=point(i,1.20);svg+=`<path class="radar-grid" d="M${center}L${p}"/><text x="${q[0]}" y="${q[1]}" text-anchor="${q[0]<245?'end':q[0]>275?'start':'middle'}">${escape(label)}</text>`;});
    for(const level of [.5,1]){const p=point(0,level);svg+=`<text class="radar-scale" x="${p[0]+7}" y="${p[1]+12}">${level*100}%</text>`;}
    for(const [row,kind]of [[pair.before,'before'],[pair.after,'after']]){
      const points=axes.map(([key],i)=>{const stats=columnStats(results.rows,r=>metricValue(r,key)),v=metricValue(row,key),r=stats.max>stats.min?(v-stats.min)/(stats.max-stats.min):.5;return point(i,r);});
      svg+=`<polygon class="radar-${kind}" points="${points.map(p=>p.join(',')).join(' ')}"><title>${escape(row.name)}</title></polygon>`;
      points.forEach((p,i)=>{const [key,label]=axes[i],v=metricValue(row,key);svg+=`<circle class="radar-dot-${kind}" cx="${p[0]}" cy="${p[1]}" r="4"><title>${escape(row.name+' · '+label)}: ${number(key==='gc'?v*100:v,5)}</title></circle>`;});
    }
    $('radar-chart').innerHTML=svg+'</svg>';
  }
  $('radar-pair').onchange=()=>{radarCandidate=value('radar-pair');drawRadar();save();};
  $('radar-parameters').onchange=e=>{const key=e.target.dataset.radarKey;if(!key)return;if(e.target.checked)radarKeys.add(key);else radarKeys.delete(key);drawRadar();save();};

  function choose(id,openStructure=true){focus=id;base=1;viewbox=null;$('focus').value=id;renderResults();if(openStructure)switchTab('structure');save();}
  let baseNodes=[],hoverNodes=[];
  function scoresFor(row){const values=row?.stability_profile;return Array.isArray(values)&&values.length===row.fold_sequence.length&&values.every(Number.isFinite)?values:null;}
  function stabilityExtent(){let low=Infinity,high=-Infinity;for(const row of results.rows){const values=scoresFor(row);if(values)for(const v of values){low=Math.min(low,v);high=Math.max(high,v);}}return Number.isFinite(low)?[low,high]:[0,1];}
  async function ensureProfile(row){
    if(scoresFor(row)||profileStatus.get(row)?.loading||profileStatus.get(row)?.error)return;
    const token=generation,key=row.sha256+'|'+row.temperature+'|'+row.structure;
    profileStatus.set(row,{loading:true});
    try{
      if(!profileRequests.has(key))profileRequests.set(key,request('/api/mrna/stability',post({sequence:row.fold_sequence,structure:row.structure})));
      const response=await profileRequests.get(key);
      if(!response.available||!Array.isArray(response.scores)||response.scores.length!==row.fold_sequence.length||!response.scores.every(Number.isFinite))throw Error(response.message||'The stability profile is unavailable.');
      row.stability_profile=response.scores;profileStatus.set(row,{loading:false});
      if(token===generation&&activeRow()===row){drawStructure();save();}
    }catch(error){profileRequests.delete(key);profileStatus.set(row,{loading:false,error:error.message});if(token===generation&&activeRow()===row)$('stability-legend').textContent='Stability profile unavailable. '+error.message;}
  }
  function drawDetails(r){
    $('model-details').innerHTML=`<div class="mrna-checks"><p>${escape(Object.entries(r.model_versions).map(([k,v])=>k+': '+v).join(' · '))}</p><dl>${Object.entries(r.metrics).map(([key,v])=>`<dt>${escape(key.replace(/_/g,' '))}</dt><dd>${typeof v==='boolean'?(v?'Yes':'No'):number(v,5)}</dd>`).join('')}</dl>${Object.keys(r.tissue_predictions||{}).length?`<details><summary>RiboNN cell-type predictions</summary><dl>${Object.entries(r.tissue_predictions).map(([cell,score])=>`<dt>${escape(cell.replace('predicted_TE_',''))}</dt><dd>${number(score,4)}</dd>`).join('')}</dl></details>`:''}<p>Transcript SHA-256: ${escape(r.sha256)}</p><ul>${(r.warnings||[]).map(x=>`<li>${escape(x)}</li>`).join('')}</ul><details><summary>Parameters used</summary><pre>${escape(JSON.stringify(r.parameters,null,2))}</pre></details>${r.optimization?`<details><summary>Optimisation report</summary><pre>${escape(r.optimization.solution?.constraints_summary||'')}\n${escape(r.optimization.solution?.objectives_summary||'')}</pre></details>`:''}</div>`;
  }
  function drawStructure(){
    const r=activeRow();if(!r){$('structure').innerHTML='<div class="mrna-empty">Calculate a batch to explore its structure.</div>';for(const id of ['stability-legend','sequence-track','gc-detail','hotspots','model-details','gc-hover-info','base-info','fold-meta','gc-meta'])$(id).replaceChildren();$('arc-controls').hidden=true;baseNodes=[];hoverNodes=[];linkedHover=null;return;}
    linkedHover=null;hoverNodes=[];delete $('structure').dataset.linkStart;delete $('structure').dataset.linkEnd;
    const arc=value('layout')==='arc',seq=r.fold_sequence.replace(/T/g,'U'),scores=scoresFor(r),[low,high]=stabilityExtent();
    $('arc-controls').hidden=!arc;$('structure').classList.toggle('is-arc',arc);
    arcRange=arc?arcGeometry(r,base,value('arc-size')):null;
    coords=arc?Array.from(seq,(_,i)=>[arcRange.x(i+1),270]):r.coordinates;
    const visible=arc?coords.slice(arcRange.start-1,arcRange.end):coords;
    const xs=visible.map(p=>p[0]),ys=visible.map(p=>p[1]);
    if(!viewbox)viewbox=arc?[...arcRange.box]:[Math.min(...xs)-20,Math.min(...ys)-20,Math.max(80,Math.max(...xs)-Math.min(...xs)+40),Math.max(80,Math.max(...ys)-Math.min(...ys)+40)];
    let inner='<desc>RNA structure coloured by per-nucleotide DegScore degradation contribution. Lower scores indicate greater predicted stability. Colours are relative across the available profiles in this batch.</desc>'+`<polyline class="backbone" points="${visible.map(p=>p.join(',')).join(' ')}"/>`;
    let continuations=0;
    for(const [a,b]of r.pairs){
      if(arc){
        if(a>arcRange.end||b<arcRange.start)continue;
        const aa=Math.max(a,arcRange.start),bb=Math.min(b,arcRange.end),p=[arcRange.x(aa),270],q=[arcRange.x(bb),270],height=16+210*Math.sqrt((bb-aa)/arcRange.maxSpan),outside=a<arcRange.start||b>arcRange.end;
        if(outside)continuations++;
        inner+=`<path class="pair${outside?' pair-continuation':''}" data-pair="${a},${b}" d="M${p} Q${(p[0]+q[0])/2},${270-height*2} ${q}"><title>Pair ${a}–${b}${outside?' · continues beyond this window':''}</title></path>`;
      }else{const p=coords[a-1],q=coords[b-1];inner+=`<line class="pair" data-pair="${a},${b}" x1="${p[0]}" y1="${p[1]}" x2="${q[0]}" y2="${q[1]}"/>`;}
    }
    coords.forEach(([x,y],i)=>{if(arc&&(i+1<arcRange.start||i+1>arcRange.end))return;const score=scores?.[i],radius=arc&&value('arc-size')==='all'?Math.max(.6,Math.min(4.5,arcRange.step*.45)):4.5;inner+=`<circle class="base" data-base="${i+1}" ${score===undefined?'':`data-stability-score="${score}"`} cx="${x}" cy="${y}" r="${radius}" fill="${stabilityColor(score,low,high)}"><title>Nucleotide ${i+1}${score===undefined?'':` · DegScore contribution ${number(score,4)}`}</title></circle>`;});
    if(arc){
      const step=Math.max(10,10**Math.floor(Math.log10(arcRange.width/6))),ticks=[arcRange.start];for(let p=Math.ceil((arcRange.start+1)/step)*step;p<arcRange.end-step/3;p+=step)ticks.push(p);if(arcRange.end>arcRange.start)ticks.push(arcRange.end);
      for(const p of ticks)inner+=`<path class="arc-tick" d="M${arcRange.x(p)},280V287"/><text class="arc-label" x="${arcRange.x(p)}" y="300">${p}</text>`;
      $('arc-meta').textContent=`Nucleotides ${arcRange.start}–${arcRange.end} of ${seq.length}. ${continuations?continuations+' dashed pairs continue outside this window.':'All displayed pair endpoints are in this window.'}`;
      $('arc-prev').disabled=arcRange.start===1;$('arc-next').disabled=arcRange.end===seq.length;
    }
    $('structure').innerHTML=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="${viewbox.join(' ')}">${inner}</svg>`;
    baseNodes=[];for(const node of $('structure').querySelectorAll('.base'))baseNodes[Number(node.dataset.base)-1]=node;
    $('stability-legend').innerHTML=scores?`<span>Higher predicted stability</span><span class="mrna-stability-ramp" aria-hidden="true"></span><span>Lower predicted stability</span><small>DegScore contribution ${number(low,3)}–${number(high,3)} · relative batch scale</small>`:escape(profileStatus.get(r)?.error||'Loading per-nucleotide stability…');
    $('fold-meta').textContent=`${r.name} · ${r.fold_scope==='cds'?'CDS':'Full transcript'} · ${seq.length.toLocaleString()} nt · ${r.temperature} °C · MFE ${number(r.metrics.mfe,2)} kcal/mol · ${number(r.metrics.paired_ratio*100,1)}% paired`;
    $('position').max=seq.length;
    $('gc-meta').textContent=`CDS coordinates · ${r.gc_window} nt window · ${number(r.parameters.gc_window_min*100,0)}–${number(r.parameters.gc_window_max*100,0)}% target`;
    $('hotspots').innerHTML=r.gc_hotspots.length?r.gc_hotspots.map(h=>`<button data-hotspot="${h.start}" data-hotspot-end="${h.end}">${h.kind==='high'?'High':'Low'} GC · ${h.start}–${h.end} · ${number(h.peak*100,1)}%</button>`).join(''):'<span class="small muted">All windows meet the selected GC bounds.</span>';
    drawDetails(r);inspect(base,false);if(!scores)ensureProfile(r);
  }
  function describePosition(r,position){const pair=r.pairs.find(p=>p.includes(position)),partner=pair?(pair[0]===position?pair[1]:pair[0]):null,score=scoresFor(r)?.[position-1];return `Nucleotide ${position} · ${r.fold_sequence[position-1].replace('T','U')} · ${partner?'paired with '+partner:'unpaired'}${score===undefined?'':` · DegScore contribution ${number(score,4)}`}`;}
  function renderTrack(r,position,range=null,keepWindow=false){
    const track=$('sequence-track'),same=track.dataset.row===r.id&&track.dataset.hash===r.sha256;
    let start=Number(track.dataset.start)||0,end=Number(track.dataset.end)||0;
    if(!keepWindow||!same||position<=start||position>end){
      const width=Math.min(600,Math.max(180,range?range.fold_end-range.fold_start+81:180));
      start=Math.max(0,Math.min(r.fold_sequence.length-width,Math.round(position-width/2)));end=Math.min(r.fold_sequence.length,start+width);
      track.innerHTML=`<span class="muted">${start+1}–${end} </span>`+Array.from(r.fold_sequence.slice(start,end).replace(/T/g,'U'),(letter,i)=>`<button data-sequence-base="${i+start+1}" title="Nucleotide ${i+start+1}">${letter}</button>`).join('');
      track.dataset.row=r.id;track.dataset.hash=r.sha256;track.dataset.start=start;track.dataset.end=end;
    }
    for(const node of track.querySelectorAll('[data-sequence-base]')){const n=Number(node.dataset.sequenceBase);node.classList.toggle('active',n===position);node.classList.toggle('range-highlight',!!range&&n>=range.fold_start&&n<=range.fold_end);}
  }
  function drawGCHover(r,range){
    const overlay=$('gc-detail').querySelector('[data-gc-hover]');if(!overlay)return;
    const selection=$('gc-detail').querySelector('.gc-selection-cursor');if(selection)selection.style.display=range?'none':'';
    if(!range||range.start==null){overlay.replaceChildren();return;}
    const x=p=>42+(p-1)/Math.max(1,r.cds.length-1)*590,left=x(range.start),right=x(range.end);
    overlay.innerHTML=`<rect class="mrna-gc-range" x="${left}" y="14" width="${Math.max(2,right-left)}" height="164"/><path d="M${x((range.start+range.end)/2)},14V178" class="mrna-gc-crosshair"/>`;
  }
  function highlightRange(range,source,position){
    const r=activeRow();if(!r)return;
    position=Math.max(1,Math.min(r.fold_sequence.length,Math.round(position)));
    const key=[source,range?.fold_start,range?.fold_end,position].join(':');if(linkedHover?.key===key)return;
    for(const node of hoverNodes)node.classList.remove('range-highlight','hovered-base');hoverNodes=[];
    linkedHover={...range,key,source,position};
    if(range)for(let i=range.fold_start;i<=range.fold_end;i++){const node=baseNodes[i-1];if(node){node.classList.add('range-highlight');hoverNodes.push(node);}}
    const focused=baseNodes[position-1];if(focused){focused.classList.add('hovered-base');if(!hoverNodes.includes(focused))hoverNodes.push(focused);}
    $('structure').dataset.linkStart=range?.fold_start??position;$('structure').dataset.linkEnd=range?.fold_end??position;
    $('base-info').textContent=describePosition(r,position);
    renderTrack(r,position,range,source==='sequence');drawGCHover(r,range);
    $('gc-hover-info').textContent=range?.start!=null?`Linked CDS ${range.start}–${range.end}${Number.isFinite(range.gc)?` · ${number(range.gc*100,1)}% GC`:''} · structure ${range.fold_start}–${range.fold_end}`:'This nucleotide is outside the CDS GC profile.';
    for(const chip of $('hotspots').querySelectorAll('[data-hotspot]'))chip.classList.toggle('linked',!!range&&range.start<=Number(chip.dataset.hotspotEnd)&&range.end>=Number(chip.dataset.hotspot));
  }
  function clearHover(){
    if(!linkedHover)return;linkedHover=null;
    for(const node of hoverNodes)node.classList.remove('range-highlight','hovered-base');hoverNodes=[];
    delete $('structure').dataset.linkStart;delete $('structure').dataset.linkEnd;
    $('hotspots').querySelectorAll('.linked').forEach(node=>node.classList.remove('linked'));
    const r=activeRow();if(r){$('base-info').textContent=describePosition(r,base);renderTrack(r,base,null,true);drawGCHover(r,null);}
    $('gc-hover-info').textContent='Hover a GC window, hotspot or structure nucleotide to link the views.';
  }
  function inspect(position,center=false){
    const r=activeRow();if(!r)return;clearHover();base=Math.max(1,Math.min(r.fold_sequence.length,Number(position)||1));
    const pair=r.pairs.find(p=>p.includes(base)),partner=pair?(pair[0]===base?pair[1]:pair[0]):null;
    for(const node of baseNodes.filter(Boolean)){node.classList.toggle('selected',Number(node.dataset.base)===base);node.classList.toggle('partner',Number(node.dataset.base)===partner);}
    for(const node of $('structure').querySelectorAll('.pair'))node.classList.toggle('selected',node.dataset.pair.split(',').map(Number).includes(base));
    $('position').value=base;$('base-info').textContent=describePosition(r,base);renderTrack(r,base);$('gc-detail').innerHTML=gcSVG([r],true);
    $('gc-hover-info').textContent='Hover a GC window, hotspot or structure nucleotide to link the views.';
    if(center&&value('layout')==='arc'&&arcRange&&(base<arcRange.start||base>arcRange.end)){viewbox=null;drawStructure();return;}
    if(center&&value('layout')!=='arc'&&coords[base-1]){const [x,y]=coords[base-1];viewbox[0]=x-viewbox[2]/2;viewbox[1]=y-viewbox[3]/2;applyViewbox();}
  }
  function applyViewbox(){const svg=$('structure').querySelector('svg');if(svg&&viewbox)svg.setAttribute('viewBox',viewbox.join(' '));}
  function zoom(factor){if(!viewbox)return;const [x,y,w,h]=viewbox,nw=Math.max(30,Math.min(200000,w*factor)),nh=h*nw/w;viewbox=[x+(w-nw)/2,y+(h-nh)/2,nw,nh];applyViewbox();}
  let drag=null,moved=false;
  $('structure').onpointerdown=e=>{if(!viewbox)return;clearHover();drag={x:e.clientX,y:e.clientY,box:[...viewbox]};moved=false;$('structure').setPointerCapture(e.pointerId);};
  $('structure').onpointermove=e=>{
    if(!drag){const hit=e.target.closest('[data-base]'),r=activeRow();if(hit&&r){const position=Number(hit.dataset.base);highlightRange(gcWindowForBase(r,position),'structure',position);}else if(linkedHover?.source==='structure')clearHover();return;}
    const rect=$('structure').getBoundingClientRect(),scale=Math.max(drag.box[2]/rect.width,drag.box[3]/rect.height),dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>3)moved=true;viewbox=[drag.box[0]-dx*scale,drag.box[1]-dy*scale,drag.box[2],drag.box[3]];applyViewbox();
  };
  $('structure').onpointerleave=()=>{if(!drag&&linkedHover?.source==='structure')clearHover();};
  $('structure').onpointerup=e=>{drag=null;if(!moved){const target=doc.elementFromPoint(e.clientX,e.clientY),hit=target?.closest('[data-base]'),pair=target?.closest('[data-pair]');if(hit)inspect(hit.dataset.base);else if(pair){const endpoints=pair.dataset.pair.split(',').map(Number);inspect(endpoints.find(p=>!arcRange||(p>=arcRange.start&&p<=arcRange.end))||endpoints[0]);}}};
  $('structure').onpointercancel=()=>{drag=null;clearHover();};
  $('structure').addEventListener('wheel',e=>{if(!viewbox)return;e.preventDefault();zoom(e.deltaY>0?1.15:1/1.15);},{passive:false});
  $('structure').onkeydown=e=>{if(['ArrowLeft','ArrowRight','+','-','=','Home'].includes(e.key)){e.preventDefault();if(e.key==='ArrowLeft'||e.key==='ArrowRight')inspect(base+(e.key==='ArrowRight'?1:-1),true);else if(e.key==='Home'){viewbox=null;drawStructure();}else zoom(e.key==='-'?1.3:1/1.3);}};
  $('position').onchange=()=>inspect(value('position'),true);
  $('sequence-track').onclick=e=>{const hit=e.target.closest('[data-sequence-base]');if(hit)inspect(hit.dataset.sequenceBase,true);};
  $('sequence-track').onpointermove=e=>{const hit=e.target.closest('[data-sequence-base]'),r=activeRow();if(hit&&r){const pos=Number(hit.dataset.sequenceBase);highlightRange(gcWindowForBase(r,pos),'sequence',pos);}};
  $('sequence-track').onpointerleave=()=>{if(linkedHover?.source==='sequence')clearHover();};
  function hoverHotspot(event){const hit=event.target.closest('[data-hotspot]'),r=activeRow();if(hit&&r){const range=foldRange(r,Number(hit.dataset.hotspot),Number(hit.dataset.hotspotEnd));highlightRange(range,'hotspot',Math.round((range.fold_start+range.fold_end)/2));}}
  $('hotspots').onpointerover=hoverHotspot;$('hotspots').onfocusin=hoverHotspot;$('hotspots').onpointerleave=()=>{if(linkedHover?.source==='hotspot')clearHover();};$('hotspots').onfocusout=()=>{if(linkedHover?.source==='hotspot')clearHover();};
  $('hotspots').onclick=e=>{const hit=e.target.closest('[data-hotspot]'),r=activeRow();if(hit&&r){const range=foldRange(r,Number(hit.dataset.hotspot),Number(hit.dataset.hotspotEnd));inspect(Math.round((range.fold_start+range.fold_end)/2),true);hoverHotspot(e);}};
  function gcPointerWindow(event){
    const r=activeRow(),svg=$('gc-detail').querySelector('svg');if(!r||!svg)return null;
    const pt=svg.createSVGPoint();pt.x=event.clientX;pt.y=event.clientY;const matrix=svg.getScreenCTM();if(!matrix)return null;const local=pt.matrixTransform(matrix.inverse());
    if(local.x<42||local.x>632||local.y<14||local.y>178)return null;
    const center=1+(local.x-42)/590*(r.cds.length-1),position=Math.max(1,Math.min(r.cds.length,Math.round(center))),offset=r.fold_scope==='transcript'?r.regions.cds[0]-1:0;
    return gcWindowForBase(r,position+offset);
  }
  $('gc-detail').onpointermove=e=>{const range=gcPointerWindow(e);if(range)highlightRange(range,'gc',range.focus);else if(linkedHover?.source==='gc')clearHover();};
  $('gc-detail').onpointerleave=()=>{if(linkedHover?.source==='gc')clearHover();};
  $('gc-detail').onclick=e=>{const range=gcPointerWindow(e);if(range)inspect(range.focus,true);};
  function download(content,name,type='text/plain'){const url=URL.createObjectURL(new Blob([content],{type})),a=doc.createElement('a');a.href=url;a.download=name;a.click();win.setTimeout(()=>URL.revokeObjectURL(url),1000);}
  function exportBatch(){const format=value('export-format'),rows=results.rows;if(!rows.length)return;let text,type='text/plain';if(format==='json'){text=JSON.stringify({...results,comparison_view:{translation_target:value('translation-cell')||'mean'}},null,2);type='application/json';}else if(format==='fasta')text=rows.map(r=>'>'+r.name.replace(/[\r\n]/g,' ')+'\n'+r.transcript.replace(/T/g,'U').match(/.{1,80}/g).join('\n')).join('\n')+'\n';else if(format==='dbn')text=rows.map(r=>'>'+r.name+' | '+r.fold_scope+' | '+r.metrics.mfe+' kcal/mol\n'+r.fold_sequence.replace(/T/g,'U')+'\n'+r.structure).join('\n')+'\n';else{const keys=['name','input_name','group','strategy','length','transcript_length','gc','cai','tai','mfe','mfe_density','paired_ratio','degscore','predicted_half_life','csc','translation','translation_mean','translation_target','hamming_ratio','protein_preserved','fold_scope','temperature','sha256','cds','transcript','model_versions','parameters','seed'];text=keys.map(csvCell).join(',')+'\n'+rows.map(r=>{const flat={...r,...r.metrics,translation:translationValue(r),translation_mean:r.metrics.translation,translation_target:value('translation-cell')||'mean',model_versions:JSON.stringify(r.model_versions),parameters:JSON.stringify(r.parameters)};return keys.map(k=>csvCell(flat[k])).join(',');}).join('\n');type='text/csv';}download(text,'junction-mrna.'+format,type);}
  $('translation-cell').onchange=()=>{renderResults();save();};
  $('export').onclick=exportBatch;$('svg-export').onclick=()=>{const svg=$('structure').querySelector('svg');if(!svg)return;const clone=svg.cloneNode(true);clone.insertAdjacentHTML('afterbegin','<style>.backbone,.pair{fill:none;stroke:#73847c;stroke-width:1;opacity:.5}.pair-continuation{stroke-dasharray:5 4}.arc-tick{stroke:#73847c;stroke-width:1}.base{stroke:#fff;stroke-width:.7}text{font:8px monospace;text-anchor:middle;dominant-baseline:central;fill:#18312e}.selected,.partner{stroke:#18312e;stroke-width:2}</style>');download(new XMLSerializer().serializeToString(clone),'junction-mrna-structure.svg','image/svg+xml');};
  $('add').onclick=()=>{if(records.length>=32){showError('Use up to 32 sequences per batch.');return;}add();renderRecords();save();};
  function importText(text,name){const incoming=parse(text,name);if(records.length===1&&!records[0].sequence.trim())records=[];if(records.length+incoming.length>32)throw Error('Use at most 32 sequences per batch.');for(const record of incoming){let name=record.name||'Sequence';let suffix=2;while(records.some(r=>r.name===name))name=record.name+' '+suffix++;add({...record,name});}renderRecords();save();}
  $('files').onchange=async e=>{showError('');try{for(const file of e.target.files){if(file.size>2*1024*1024)throw Error('Input files must be smaller than 2 MB.');importText(await file.text(),file.name);}}catch(error){showError(error.message);}e.target.value='';};$('import-paste').onclick=()=>{try{importText(value('bulk'),'pasted.fasta');$('bulk').value='';showError('');}catch(error){showError(error.message);}};
  $('example').onclick=async()=>{await open();if(records.some(r=>r.sequence.trim())&&!win.confirm('Replace the current input sequences with the reporter example?'))return;const protein=cap?.examples?.eGFP;if(!protein){showError('The example is unavailable until the local engine connects.');return;}records=[];add({name:'eGFP · MaxCAI',sequence:protein,kind:'protein',group:'Reporter panel'});add({name:'eGFP · MaxtAI',sequence:protein,kind:'protein',group:'Reporter panel',override:true,organism:'homo-sapiens',objective:'tai'});renderRecords();save();};
  $('preset').onchange=()=>{const preset=cap?.elements?.[Number(value('preset'))];if(value('preset')===''||!preset)return;$('utr5').value=preset.utr5;$('utr3').value=preset.utr3;$('poly-a').value=preset.poly_a;save();};
  $('analyse').onclick=()=>start('compare');$('run').onclick=()=>start('design');$('cancel').onclick=async()=>{try{if(job)await request('/api/mrna/jobs/'+encodeURIComponent(job)+'/cancel',post({}));}catch(error){showError(error.message);}};
  $('results').onchange=e=>{if(!e.target.dataset.result)return;if(e.target.checked)selected.add(e.target.dataset.result);else selected.delete(e.target.dataset.result);drawComparison();save();};$('results').onclick=e=>{const b=e.target.closest('[data-explore]');if(b)choose(b.dataset.explore);};
  $('select-all').onchange=()=>{selected=new Set(value('select-all')?results.rows.map(r=>r.id):[]);renderResults();save();};
  doc.querySelectorAll('[data-mrna-sort]').forEach(th=>th.querySelector('button').onclick=()=>{const key=th.dataset.mrnaSort;sort={key,direction:sort.key===key?-sort.direction:1};renderResults();});
  $('arc-size').onchange=()=>{viewbox=null;drawStructure();save();};
  function moveArc(direction){const r=activeRow();if(!r||!arcRange)return;base=Math.max(1,Math.min(r.fold_sequence.length,Math.round((arcRange.start+arcRange.end)/2)+direction*arcRange.width));viewbox=null;drawStructure();}
  $('arc-prev').onclick=()=>moveArc(-1);$('arc-next').onclick=()=>moveArc(1);
  $('focus').onchange=()=>choose(value('focus'),false);$('layout').onchange=()=>{viewbox=null;drawStructure();save();};$('zoom-in').onclick=()=>zoom(1/1.4);$('zoom-out').onclick=()=>zoom(1.4);$('fit').onclick=()=>{viewbox=null;drawStructure();};
  $('history').onchange=async()=>{if(!value('history'))return;generation++;clearTimeout(timer);job=value('history');results={rows:[],errors:[]};selected=new Set();gcHidden.clear();knownRows=new Set();focus=null;viewbox=null;await poll(generation);};
  function snapshot(){return {draft:{fields:Object.fromEntries(fields.map(id=>[id,value(id)])),records},result:results,job_id:job,tab,focus,translation_cell:value('translation-cell'),selected:[...selected],comparison:{gc_hidden:[...gcHidden],gc_mode:value('gc-mode'),heatmap:value('heatmap'),radar_keys:[...radarKeys],radar_candidate:radarCandidate},structure_view:{layout:value('layout'),arc_size:value('arc-size')}};}
  function validRow(r){
   if(!r||!['id','name','input_name','group','strategy','cds','transcript','fold_sequence','structure','sha256'].every(k=>typeof r[k]==='string'))return false;
   const len=r.fold_sequence.length;if(!len||len>10000||!/^[ACGT]+$/.test(r.cds)||!/^[ACGT]+$/.test(r.fold_sequence)||!/^[().]+$/.test(r.structure)||r.structure.length!==len)return false;
   if(r.stability_profile!=null&&(!Array.isArray(r.stability_profile)||r.stability_profile.length!==len||!r.stability_profile.every(Number.isFinite)))return false;
   if(!Array.isArray(r.coordinates)||r.coordinates.length!==len||!r.coordinates.every(p=>Array.isArray(p)&&p.length===2&&p.every(x=>typeof x==='number'&&Number.isFinite(x))))return false;
   if(!Array.isArray(r.pairs)||!r.pairs.every(p=>Array.isArray(p)&&p.length===2&&p.every(x=>Number.isInteger(x)&&x>=1&&x<=len)))return false;
   if(!Array.isArray(r.gc_profile)||!r.gc_profile.every(p=>Array.isArray(p)&&p.length===2&&p.every(x=>typeof x==='number'&&Number.isFinite(x))))return false;
   return r.metrics&&r.parameters&&r.regions&&Array.isArray(r.regions.cds)&&r.regions.cds.every(Number.isFinite)&&Array.isArray(r.gc_hotspots)&&r.gc_hotspots.every(h=>h&&[h.start,h.end,h.peak].every(Number.isFinite))&&[r.parameters.gc_window_min,r.parameters.gc_window_max,r.temperature,r.gc_window].every(Number.isFinite)&&r.model_versions&&typeof r.model_versions==='object'&&(!r.warnings||Array.isArray(r.warnings));
  }
  function restore(saved){gcHidden=new Set(Array.isArray(saved?.comparison?.gc_hidden)?saved.comparison.gc_hidden:[]);$('gc-mode').value=saved?.comparison?.gc_mode==='groups'?'groups':'samples';$('heatmap').checked=saved?.comparison?.heatmap!==false;radarKeys=new Set(Array.isArray(saved?.comparison?.radar_keys)?saved.comparison.radar_keys:['gc','cai','tai','mfe_density','predicted_half_life','csc']);radarCandidate=saved?.comparison?.radar_candidate||'';$('radar-pair').innerHTML='';$('layout').value=saved?.structure_view?.layout==='arc'?'arc':'fold';$('arc-size').value=['150','300','600','all'].includes(saved?.structure_view?.arc_size)?saved.structure_view.arc_size:'150';arcRange=null;generation++;clearTimeout(timer);records=[];const draft=saved?.draft;for(const id of fields){if($(id).type==='checkbox')$(id).checked=Boolean(draft?.fields?.[id]??defaults[id]);else $(id).value=draft?.fields?.[id]??defaults[id];}for(const record of (Array.isArray(draft?.records)?draft.records:[]).slice(0,32)){if(record&&typeof record.sequence==='string')add(record);}if(!records.length)add();results=saved?.result&&Array.isArray(saved.result.rows)?saved.result:{rows:[],errors:[]};results.rows=results.rows.filter(validRow).slice(0,128);knownRows=new Set(results.rows.map(r=>r.id));selected=new Set(Array.isArray(saved?.selected)?saved.selected:results.rows.map(r=>r.id));focus=saved?.focus||results.rows[0]?.id;job=saved?.job_id||null;viewbox=null;setBusy(false);renderRecords();renderResults();if(saved?.translation_cell){$('translation-cell').value=saved.translation_cell;renderResults();}switchTab(saved?.tab||'batch');}
  add();renderRecords();
  return {open,snapshot,restore};
 }
 return {parse,csvRows,csvCell,normalize,hamming,stabilityColor,foldRange,gcWindowForBase,columnStats,zScore,zColor,matchedPairs,gcSeries,arcGeometry,setup};
});
