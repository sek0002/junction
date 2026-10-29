'use strict';
const $=id=>document.getElementById(id);
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const plateLabel=id=>state.plateLabels?.[id]??(/^pSHPs/i.test(String(id||''))?(String(id).slice(5).replace(/[^a-z0-9]/gi,'').slice(0,4)||id):String(id||''));
const spanLabel=(a,b)=>a===b?'gap after '+a:`${a+1}–${b}`;
const fmt=(x,n=2)=>x===null||x===undefined?'—':Number(x).toLocaleString(undefined,{maximumFractionDigits:n});
const state={worksheetIds:{},workbenchId:null,plateSelection:new Set(),plateMaps:[],plateView:null,plateWell:null,plateWellSelection:new Set(),plateArchiveBusy:false,plasmidDrafts:new Map(),plasmidSaving:new Set(),uploadRuleOverrides:readUploadRules(),nestedAssemblies:[],nestedParent:null,nestedCassette:null,nestedDraftMode:null,nestedDraftStocks:{},nestedFragments:new Map(),fragments:[],plasmids:[],recipes:[],parts:[],assemblyNameManual:false,assemblyNameRecommendation:'',result:null,assemblyResult:null,fragmentChecks:[],mapMode:'circular',selectedFeature:null,searchIndex:0,subtab:'assembly',resuspension:null,swapIndex:null,rules:null,plannerOverrides:readPlannerOverrides(),plannerStocks:{},buildList:[],activeBuildId:null,lastRemovedBuildId:null,buildSaveError:null,buildBusy:false,inventoryDrafts:new Map(),fragmentSelection:new Set(),plasmidSelection:new Set(),inventorySort:null,inventoryAutosaves:new Map()};
let toastTimer,searchTimer,previewTimer,assemblyCheckTimer,searchCounter=0,checkCounter=0,resuspCounter=0;
function toast(msg){$('toast').textContent=msg;$('toast').classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.remove('visible'),6000);}
function busy(text){$('busy-text').textContent=text;$('busy').classList.toggle('hidden',!text);}
async function api(url,options={}){const r=await fetch(url,options);if(!r.ok){let d;try{d=await r.json();}catch{d={detail:r.statusText};}let detail=d.detail||d;const error=Error(typeof detail==='string'?detail:detail.message?detail.message+(detail.errors?' '+detail.errors.join(' '):''):JSON.stringify(detail));error.sandboxId=Number(r.headers.get('X-Junction-Comparison-Id'))||null;throw error;}return r.json();}
const jsonBody=data=>({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
async function fileDownload(url,body,fallback){if(url.includes('worksheet')){const invalid=$('resuspension-body').querySelector('input[aria-invalid="true"]');if(invalid){invalid.reportValidity();toast('Enter positive stock values before exporting');return;}}busy('Preparing download…');try{const r=await fetch(url,body?jsonBody(body):{});if(!r.ok){const d=await r.json();throw Error(typeof d.detail==='string'?d.detail:JSON.stringify(d.detail));}const b=await r.blob();const u=URL.createObjectURL(b);const a=document.createElement('a');a.href=u;a.download=(r.headers.get('Content-Disposition')||'').match(/filename="([^"]+)"/)?.[1]||fallback;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),3000);return true;}catch(e){toast(e.message);return false;}finally{busy('');}}
function showView(name){
  name=JunctionHome.resolveView(name);const profile=name==='profile';if(profile)name='home';
  hideNestedCardTooltip();hideMapTooltip();closeFragmentSwap();
  document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id===name));
  document.querySelectorAll('.nav').forEach(x=>x.classList.toggle('active',x.dataset.view===name));
  document.body.classList.toggle('home-active',name==='home');
  history.replaceState(null,'','#'+name);window.JunctionHomeController?.viewChanged(name);
  window.JunctionWorksheetController?.setScope(name);if(name==='workbenches')window.JunctionWorkbenchController?.load();if(name==='design')window.JunctionDesign?.open();if(name==='library')loadInventory();if(name==='uploads')loadUploads();if(name==='bin')loadBin();
  if(profile)window.JunctionHomeController.onReady(()=>$('account-open').click());
}
function settings(){return{...plannerRuleDefaults(),...state.plannerOverrides,backbone_pmol:Number($('backbone-pmol').value),insert_ratio:Number($('insert-ratio').value),reaction_volume_ul:Number($('reaction-ul').value),master_mix_volume_ul:Number($('master-ul').value),backbone_stock_ng_ul:$('backbone-stock').value?Number($('backbone-stock').value):null,assume_target_stock:!$('assume-stock').checked,planner_stock_mode:$('assume-stock').checked?'saved':'custom',fragment_stock_overrides:Object.fromEntries(Object.entries(state.plannerStocks).filter(([id])=>state.parts.some(p=>p.id===Number(id))||selectedNested().some(g=>g.fragment_ids.includes(Number(id))))),resuspension_mode:'constrained'};}
function referenceParams(){const q=new URLSearchParams();for(const[k,v]of Object.entries(settings()))if(v!==null)q.set(k,v);const value=$('backbone').value;q.set('no_backbone',!value);if(value.startsWith('p:'))q.set('backbone_id',value.slice(2));return q;}
function selectSubtab(name){hideNestedCardTooltip();closeFragmentSwap();state.subtab=name;updateAssemblyNext();document.querySelectorAll('[data-subtab]').forEach(b=>{const active=b.dataset.subtab===name;b.classList.toggle('active',active);b.setAttribute('aria-selected',String(active));});$('assembly-subpanel').classList.toggle('hidden',name!=='assembly');$('reaction-subpanel').classList.toggle('hidden',name!=='reaction');$('export-subpanel').classList.toggle('hidden',name!=='export');if(name==='export')refreshExportAssemblies();if(name==='reaction'){loadResuspension();renderBuildList();loadBuildList().catch(error=>toast(error.message));}}
let pendingAssemblyExport=null,assemblyExportBusy=false;
function updateAssemblyNext(){
  const next={assembly:'reaction',reaction:'export'}[state.subtab],button=$('assembly-next');
  button.classList.toggle('hidden',!next);button.disabled=false;
  button.setAttribute('aria-label','Next: '+(next==='reaction'?'Reaction planner':'Export assemblies'));
}
function assemblyExportWarnings(kind){
  const groups=new Map();
  function add(name,messages){
    for(const message of messages||[]){if(!message)continue;if(!groups.has(name))groups.set(name,new Set());groups.get(name).add(String(message));}
  }
  function inspect(name,plan){
    if(!plan)return;
    add(name,[...(plan.errors||[]),...(plan.warnings||[]),...(plan.reaction?.warnings||[]),...(plan.reaction?.rows||[]).flatMap(row=>row.warnings||[])]);
    for(const nested of plan.nested_reactions||[])inspect(name+' / '+nested.name,nested);
  }
  const current=state.parts.length||$('backbone').value;
  if(current){
    if(state.assemblyResult)inspect($('assembly-name').value||'Current assembly',state.assemblyResult);
    else add('Current assembly',['Assembly checks unavailable.']);
  }
  if(kind==='build-list'){
    for(const item of state.buildList){inspect(item.request.name,item.plan);if(item.error)add(item.request.name,[item.error]);}
    if(!state.buildList.length)add('Build list',['No assemblies to export. Add an assembly to the build list.']);
    else if(current&&!state.buildList.some(item=>buildDesign(item.request)===buildDesign(payload())))add('Build list',['The current assembly is not in the build list.']);
  }
  return [...groups].map(([name,messages])=>({name,messages:[...messages]}));
}
function confirmAssemblyExportWarnings(groups){
  $('assembly-warning-list').innerHTML=groups.map(group=>`<section><h3>${esc(group.name)}</h3><ul>${group.messages.map(message=>`<li>${esc(message)}</li>`).join('')}</ul></section>`).join('');
  return new Promise(resolve=>{pendingAssemblyExport=resolve;$('assembly-warning-dialog').showModal();});
}
function finishAssemblyExportWarnings(confirmed=false){
  const resolve=pendingAssemblyExport;pendingAssemblyExport=null;
  if($('assembly-warning-dialog').open)$('assembly-warning-dialog').close();
  resolve?.(confirmed);
}
function navigateAssemblyTab(target){
  if(['assembly','reaction','export'].includes(target)&&state.subtab!==target)selectSubtab(target);
}
async function loadResuspension(){
  const token=++resuspCounter;
  if(!state.parts.length&&!$('backbone').value){$('resuspension-body').innerHTML='';return;}
  try{
    const result=await api('/api/assemblies/preview',jsonBody(payload()));
    const rows=[...result.resuspension.rows,...result.nested_reactions.flatMap(stage=>stage.resuspension.rows)];
    const r={...result.resuspension,rows:rows.filter((p,i,a)=>a.findIndex(x=>x.id===p.id)===i)};if(token!==resuspCounter)return;
    state.resuspension=r;renderPlannerStocks(r);
    $('resuspension-reference').textContent=`${fmt(r.settings.backbone_pmol,4)} pmol · ${fmt(r.settings.insert_ratio)}:1 · ${$('assume-stock').checked?'Saved stocks':'Custom stocks'}`;
  }catch(e){if(token!==resuspCounter)return;$('resuspension-reference').textContent=e.message;}
}
let plannerStockTimer;
function updatePlannerStockMode(){
  $('custom-resuspension').disabled=$('assume-stock').checked;
}
function renderPlannerStocks(result,force=false){
  const body=$('resuspension-body');if(!force&&body.contains(document.activeElement)&&document.activeElement.matches('input[data-quantity]'))return;
  body.innerHTML=result.rows.filter(x=>!x.manual_stock).map(x=>{
    const locked=x.yield_locked!==false;const local=!!state.plannerStocks[x.id];const basis=local?'Instance':x.stock_basis?.startsWith('Library')?'Library plan':x.stock_basis?.startsWith('Saved')?'Saved':'Custom plan';
    const field=(key,label,value)=>`<input type="number" min="0.000001" step="any" data-quantity="${key}" data-raw-value="${value??''}" value="${inventoryValue(value)}" ${key==='yield_ng'&&locked?'readonly':''} aria-label="${label} of ${esc(x.name)}">`;
    return `<tr data-planner-stock="${x.id}" data-name="${esc(x.name)}" data-yield-locked="${locked}" data-target="${x.target_ng??''}"><td><b>${esc(x.name)}</b><small data-planner-stock-status title="${esc(x.stock_basis||'Unmeasured plan')}">${basis}</small><small data-planner-stock-warning class="reaction-warning" title="${esc(x.warnings.join(' '))}">${esc(inventoryWarningNote(x.warnings))}</small></td><td>${esc(plateLabel(x.plate_id))} / ${esc(x.well)}</td><td><div class="yield-field">${field('yield_ng','Yield ng',x.yield_ng)}<button class="yield-lock" data-yield-lock type="button" aria-pressed="${locked}" aria-label="${locked?'Unlock':'Lock'} yield for ${esc(x.name)}">${inventoryIcon(locked?'locked':'unlocked')}</button></div></td><td>${field('resuspension_ul','Resuspend µL',x.resuspension_ul)}</td><td>${field('stock_ng_ul','Stock ng/µL',x.target_ng_ul)}</td><td data-planner-use>${inventoryQuantity(x.input_volume_ul)}</td><td><button class="icon-button row-reset" data-planner-reset aria-label="Reset ${esc(x.name)} for this assembly" title="Reset to ${$('assume-stock').checked?'saved stock':'custom rules'}">${inventoryIcon('reset')}</button></td></tr>`;
  }).join('');
  body.querySelectorAll('[data-planner-stock]').forEach(row=>{
    const id=Number(row.dataset.plannerStock);const field=key=>row.querySelector(`[data-quantity="${key}"]`);
    const values=()=>({...Object.fromEntries(['yield_ng','resuspension_ul','stock_ng_ul'].map(key=>[key,Number(field(key).dataset.rawValue)||null])),yield_locked:row.dataset.yieldLocked==='true'});
    const commit=()=>{
      const v=values();if(![v.yield_ng,v.stock_ng_ul,v.resuspension_ul].every(x=>Number.isFinite(x)&&x>0))return;
      state.plannerStocks[id]=v;row.querySelector('[data-planner-stock-status]').textContent='Instance';
      const use=Number(row.dataset.target)>0?Number(row.dataset.target)/v.stock_ng_ul:null;row.querySelector('[data-planner-use]').textContent=inventoryQuantity(use);
      const limits=$('assume-stock').checked?state.rules:settings();row.querySelector('[data-planner-stock-warning]').textContent=use!==null&&(use<limits.min_input_volume_ul-1e-9||use>limits.max_input_volume_ul+1e-9)?'Volume outside limits':'';
      clearTimeout(plannerStockTimer);plannerStockTimer=setTimeout(()=>{scheduleBuildSettingsSave();checkAssembly();},350);
    };
    row.querySelector('[data-yield-lock]').onclick=()=>{setYieldLock(row,row.dataset.yieldLocked!=='true');commit();};
    row.querySelectorAll('[data-quantity]').forEach(input=>{
      input.oninput=()=>{
        input.dataset.rawValue=input.value;const v=values();const key=input.dataset.quantity;const invalid=!(Number.isFinite(v[key])&&v[key]>0);input.setAttribute('aria-invalid',String(invalid));if(invalid){clearTimeout(plannerStockTimer);$('reaction-status').className='badge error';$('reaction-status').textContent='CHECK REQUIRED';return;}
        const derive=key==='yield_ng'?'stock_ng_ul':!v.yield_locked?'yield_ng':key==='stock_ng_ul'?'resuspension_ul':'stock_ng_ul';
        const value=derive==='yield_ng'?v.stock_ng_ul*v.resuspension_ul:derive==='stock_ng_ul'?v.yield_ng/v.resuspension_ul:v.yield_ng/v.stock_ng_ul;
        if(Number.isFinite(value)&&value>0){setInventoryValue(field(derive),value);field(derive).setAttribute('aria-invalid','false');}commit();
      };
      input.onblur=()=>{if(input.getAttribute('aria-invalid')!=='true')input.value=inventoryValue(input.dataset.rawValue===''?null:Number(input.dataset.rawValue));};
    });
    row.querySelector('[data-planner-reset]').onclick=()=>{delete state.plannerStocks[id];checkAssembly();loadResuspension();scheduleBuildSettingsSave();};
  });
}

function reverseCompFlag(part,inline=false){
  if(!part?.reverse_complement&&!part?.digest?.reverse_complement)return '';
  return `<span class="fragment-rc${inline?' rc-inline':''}" role="img" aria-label="Reverse complement" title="Reverse complement · whole fragment assembled in reverse orientation">${inventoryIcon('reverse')}<span>RC</span></span>`;
}
function applyFragmentOrientations(result){
  state.parts=state.parts.map(part=>{
    const check=result.fragment_checks?.find(item=>!item.is_backbone&&item.id===part.id);
    return check?FragmentOrientation.orient(part,check.reverse_complement):part;
  });
}
function selectedNested(){return state.nestedAssemblies.filter(g=>g.fragment_ids.length&&state.parts.some(p=>p.id===g.parent_fragment_id));}
function nestedEnzyme(group,cassette){return group?.mode==='together'?$('enzyme').value:cassette.enzyme;}
function nestedContext(){
  const parent=state.parts.find(p=>p.id===state.nestedParent);
  const cassettes=parent?.digest.nested_cassettes||[];
  const cassette=cassettes.find(c=>c.id===state.nestedCassette)||cassettes[0];
  if(cassette)state.nestedCassette=cassette.id;
  const group=state.nestedAssemblies.find(g=>g.parent_fragment_id===parent?.id&&g.cassette_id===cassette?.id);
  const parentGroup=state.nestedAssemblies.find(g=>g.parent_fragment_id===parent?.id);
  const mode=group?.mode||parentGroup?.mode||state.nestedDraftMode||'separate';
  return{parent,cassettes,cassette,group,mode,stock:parentGroup?.prepared_stock_ng_ul??state.nestedDraftStocks[parent?.id]??null};
}
function nestedChild(id,enzyme){return state.nestedFragments.get(enzyme+':'+id);}
function displayNestedChild(id,enzyme,group){
  const part=nestedChild(id,enzyme);if(!part)return part;
  const record=state.assemblyResult?.nested_assemblies?.find(r=>r.parent_fragment_id===group?.parent_fragment_id&&r.cassette_id===group?.cassette_id);
  const check=record?.fragment_checks?.find(c=>c.id===id);
  return check?FragmentOrientation.orient(part,check.reverse_complement):part;
}
async function loadNestedChildren(){
  await Promise.all(selectedNested().map(async group=>{
    const parent=state.parts.find(p=>p.id===group.parent_fragment_id),cassette=parent?.digest.nested_cassettes?.find(c=>c.id===group.cassette_id);
    if(!cassette)return;
    const enzyme=nestedEnzyme(group,cassette);
    await Promise.all(group.fragment_ids.map(async id=>{if(!nestedChild(id,enzyme)){const part=await api('/api/fragments/'+id+'?enzyme='+encodeURIComponent(enzyme));state.nestedFragments.set(enzyme+':'+id,part);}}));
  }));
}
async function openNested(parentId,cassetteId=null){
  hideNestedCardTooltip();closeFragmentSwap();state.nestedParent=parentId;state.nestedCassette=cassetteId||selectedNested().find(g=>g.parent_fragment_id===parentId)?.cassette_id||null;state.nestedDraftMode=null;
  try{await loadNestedChildren();renderNestedEditor();$('nested-assembly-editor').scrollIntoView({block:'nearest',behavior:'smooth'});$('nested-search')?.focus({preventScroll:true});}catch(error){toast(error.message);}
}
function closeNestedEditor(restoreFocus=true){
  const parentId=state.nestedParent;state.nestedParent=null;$('nested-assembly-editor').classList.add('hidden');syncNestedCardExpansion();
  if(restoreFocus)$('selected-parts').querySelector(`[data-nested-parent="${parentId}"]`)?.focus({preventScroll:true});hideNestedCardTooltip();
}
function nestedChanged(){renderParts();invalidate();}
function nestedLinker(a,b,cassette){
  const mismatch=a&&b&&a!==b;const chip=value=>overhangHtml(value,value===cassette.left_overhang||value===cassette.right_overhang?'nested-boundary':mismatch?'nested-mismatch':'','code');
  return `<span class="nested-linker" title="${esc(mismatch?'Overhang mismatch':'Fusion overhang')}">${chip(a||b)}${mismatch?chip(b):''}</span>`;
}
function renderNestedEditor(){
  nestedSearchCounter++;
  const box=$('nested-assembly-editor');const ctx=nestedContext();
  const active=document.activeElement,preserve=box.contains(active)&&['nested-search','nested-stock'].includes(active.id)?{id:active.id,value:active.value}:null;
  if(!ctx.parent||!ctx.cassette){box.classList.add('hidden');syncNestedCardExpansion();return;}
  const{parent,cassettes,cassette,group,mode}=ctx;const enzyme=nestedEnzyme({mode},cassette);
  const parts=(group?.fragment_ids||[]).map(id=>displayNestedChild(id,enzyme,group)||{id,name:'Loading…',digest:{}});
  const existing=state.assemblyResult?.nested_assemblies?.find(g=>g.parent_fragment_id===parent.id&&g.cassette_id===cassette.id);
  let previous=cassette.left_overhang;
  box.classList.remove('hidden');
  box.innerHTML=`<div class="panel-heading"><h3>Nested · ${esc(parent.name)}</h3><button class="text-button" id="nested-close" aria-label="Close nested assembly">${inventoryIcon('close')}</button></div><div class="nested-controls"><label>Cassette<select id="nested-cassette" aria-label="Nested cassette" class="${cassetteFlag(cassette)?'palindromic-overhang':''}" title="${cassetteFlag(cassette)?Overhangs.warning:''}">${cassettes.map(c=>`<option value="${esc(c.id)}" ${c.id===cassette.id?'selected':''}>${esc(cassetteFlag(c)+c.label)}</option>`).join('')}</select></label><label>Reaction<select id="nested-mode" aria-label="Nested reaction mode"><option value="together" ${mode==='together'?'selected':''}>Together</option><option value="separate" ${mode==='separate'?'selected':''}>Separate first</option></select></label>${mode==='separate'?`<label>Prepared stock · ng/µL<input id="nested-stock" aria-label="Prepared parent stock" type="number" min="0.000001" step="any" placeholder="Enter measured stock" value="${ctx.stock??''}"></label>`:''}${mode==='together'&&cassette.enzyme!==$('enzyme').value&&$('enzyme').value!=='BsmBI + BsaI'?'<button class="secondary compact" id="nested-use-dual">Use dual cutting</button>':''}</div><div class="nested-chain">${!parts.length?nestedLinker(null,cassette.left_overhang,cassette):''}${parts.map((p,index)=>{const linker=nestedLinker(previous,p.digest.left_overhang,cassette);previous=p.digest.right_overhang;const check=existing?.fragment_checks.find(c=>c.id===p.id);const errors=check?.errors||p.digest.errors||[];return `${linker}<span class="nested-chip"><span class="nested-check ${errors.length?'fail':check?'pass':''}" title="${esc(errors.join(' ')||'Compatible digest')}">${errors.length?'!':check?'✓':'…'}</span>${reverseCompFlag(p,true)}<span><b>${esc(p.name)}</b><small>${esc(p.well||'')} · ${fmt(p.physical_length,0)} bp</small></span><button class="nested-remove" data-nested-remove="${index}" aria-label="Remove nested ${esc(p.name)}">${inventoryIcon('close')}</button></span>`;}).join('')}${parts.length?nestedLinker(previous,cassette.right_overhang,cassette):`<span class="muted">…</span>${nestedLinker(null,cassette.right_overhang,cassette)}`}</div><div class="search-wrap nested-search-wrap"><input id="nested-search" maxlength="5000" placeholder="Name, overhang or DNA" aria-label="Next nested fragment" role="combobox" aria-autocomplete="list" aria-controls="nested-search-results" aria-expanded="false" autocomplete="off"><label class="nested-compatible"><input id="nested-compatible" type="checkbox" checked> Compatible ends</label><div id="nested-search-results" class="search-results hidden" role="listbox"></div></div><div id="nested-errors" class="nested-errors"></div>`;
  syncNestedCardExpansion();
  $('nested-close').onclick=closeNestedEditor;
  $('nested-cassette').onchange=()=>{state.nestedCassette=$('nested-cassette').value;state.nestedDraftMode=null;renderNestedEditor();};
  $('nested-mode').onchange=async()=>{state.nestedDraftMode=$('nested-mode').value;for(const g of state.nestedAssemblies.filter(g=>g.parent_fragment_id===parent.id))g.mode=state.nestedDraftMode;try{await loadNestedChildren();nestedChanged();}catch(error){toast(error.message);}};
  if($('nested-stock'))$('nested-stock').oninput=()=>{const value=$('nested-stock').value;if(value&&!$('nested-stock').checkValidity())return;state.nestedDraftStocks[parent.id]=value?Number(value):null;for(const g of state.nestedAssemblies.filter(g=>g.parent_fragment_id===parent.id))g.prepared_stock_ng_ul=value?Number(value):null;invalidate();};
  if($('nested-use-dual'))$('nested-use-dual').onclick=()=>{$('enzyme').value='BsmBI + BsaI';$('enzyme').onchange();};
  box.querySelectorAll('[data-nested-remove]').forEach(button=>button.onclick=()=>{group.fragment_ids.splice(Number(button.dataset.nestedRemove),1);state.nestedAssemblies=state.nestedAssemblies.filter(g=>g.fragment_ids.length);nestedChanged();});
  $('nested-search').oninput=()=>{clearTimeout(nestedSearchTimer);nestedSearchTimer=setTimeout(searchNestedFragments,160);};
  $('nested-search').onfocus=searchNestedFragments;$('nested-compatible').onchange=searchNestedFragments;
  $('nested-search').onkeydown=event=>{const options=[...$('nested-search-results').querySelectorAll('button')];if(event.key==='Escape'){$('nested-search-results').classList.add('hidden');$('nested-search').setAttribute('aria-expanded','false');}if(['Enter','ArrowDown'].includes(event.key)&&options.length){event.preventDefault();if(event.key==='Enter')options[0].click();else options[0].focus();}};
  $('nested-search-results').onkeydown=event=>{const options=[...$('nested-search-results').querySelectorAll('button')],index=options.indexOf(document.activeElement);if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();options[(index+(event.key==='ArrowDown'?1:-1)+options.length)%options.length]?.focus();}if(event.key==='Escape'){$('nested-search-results').classList.add('hidden');$('nested-search').focus();}};
  renderNestedStatus();
  if(preserve&&$(preserve.id)){$(preserve.id).value=preserve.value;$(preserve.id).focus({preventScroll:true});}
}
let nestedSearchTimer,nestedSearchCounter=0;
async function searchNestedFragments(){
  const ctx=nestedContext();if(!ctx.cassette||!$('nested-search'))return;
  const request=++nestedSearchCounter,{cassette,group,mode,parent}=ctx;const enzyme=nestedEnzyme({mode},cassette);
  const next=group?.fragment_ids.length?displayNestedChild(group.fragment_ids.at(-1),enzyme,group)?.digest.right_overhang:cassette.left_overhang;
  const url='/api/fragments?'+new URLSearchParams({enzyme,q:$('nested-search').value,limit:'30',left:$('nested-compatible').checked?next||'':''});
  try{
    let parts=await api(url);if(request!==nestedSearchCounter||state.nestedParent!==parent.id||state.nestedCassette!==cassette.id||!$('nested-search-results'))return;
    parts=parts.filter(p=>p.id!==parent.id&&!group?.fragment_ids.includes(p.id));
    $('nested-search-results').innerHTML=parts.length?parts.map(p=>`<button class="search-option" role="option" data-nested-add="${p.id}"><span><b>${esc(p.name)}</b>${reverseCompFlag(p,true)}${FragmentSearch.badge(p)}<small>${esc(FragmentSearch.location(p,plateLabel))} · ${fmt(p.physical_length,0)} bp</small></span><code>5′ ${overhangHtml(p.digest.left_overhang)} · 3′ ${overhangHtml(p.digest.right_overhang)}</code><span>＋</span></button>`).join(''):'<div class="search-note">No matching fragments</div>';
    $('nested-search-results').classList.remove('hidden');$('nested-search').setAttribute('aria-expanded','true');
    $('nested-search-results').querySelectorAll('[data-nested-add]').forEach(button=>button.onclick=()=>{const part=parts.find(p=>p.id===Number(button.dataset.nestedAdd));state.nestedFragments.set(enzyme+':'+part.id,part);let g=group;if(!g){g={parent_fragment_id:parent.id,cassette_id:cassette.id,fragment_ids:[],mode,prepared_stock_ng_ul:ctx.stock};state.nestedAssemblies.push(g);}g.fragment_ids.push(part.id);nestedChanged();$('nested-search').focus();});
  }catch(error){toast(error.message);}
}
function renderNestedStatus(){
  const ctx=nestedContext();if(!$('nested-errors')||!ctx.parent)return;
  const result=state.assemblyResult?.nested_assemblies?.find(g=>g.parent_fragment_id===ctx.parent.id&&g.cassette_id===ctx.cassette?.id);
  $('nested-errors').innerHTML=result?`<span class="badge ${result.valid?'':'error'}">${result.valid?'Pass':'Fail'}</span>${messages(result.errors)}${ctx.mode==='separate'&&!ctx.stock?'<small class="muted">Prepared stock required in Reaction planner</small>':''}`:'';
  if(result)document.querySelectorAll('#nested-assembly-editor .nested-chip').forEach((chip,index)=>{const check=result.fragment_checks[index],glyph=chip.querySelector('.nested-check');if(!check)return;glyph.textContent=check.valid?'✓':'!';glyph.className='nested-check '+(check.valid?'pass':'fail');glyph.title=check.errors.join(' ')||'Compatible digest';});
}
function renderNestedReactions(){
  const stages=state.assemblyResult?.nested_reactions||[];const prepared=selectedNested().filter(g=>g.mode==='separate').filter((g,i,a)=>a.findIndex(x=>x.parent_fragment_id===g.parent_fragment_id)===i);
  $('nested-plans-panel').classList.toggle('hidden',!stages.length);
  if(!$('prepared-stocks').contains(document.activeElement))$('prepared-stocks').innerHTML=prepared.map(g=>`<label>${esc(state.parts.find(p=>p.id===g.parent_fragment_id)?.name)} · prepared ng/µL<input data-prepared-stock="${g.parent_fragment_id}" aria-label="Prepared stock for ${esc(state.parts.find(p=>p.id===g.parent_fragment_id)?.name)}" type="number" min="0.000001" step="any" value="${g.prepared_stock_ng_ul??''}" placeholder="Enter measured stock"></label>`).join('');
  $('prepared-stocks').classList.toggle('hidden',!prepared.length);
  $('prepared-stocks').querySelectorAll('[data-prepared-stock]').forEach(input=>input.oninput=()=>{if(input.value&&!input.checkValidity())return;for(const group of selectedNested().filter(g=>g.parent_fragment_id===Number(input.dataset.preparedStock)))group.prepared_stock_ng_ul=input.value?Number(input.value):null;invalidate();});
  $('nested-plans-body').innerHTML=stages.map(stage=>`<div class="nested-stage"><h3>${esc(stage.name)} <span class="badge neutral">${esc(stage.enzyme)}</span> <span class="badge ${reactionIsReady(stage.reaction)&&!stage.errors.length?'':'error'}">${reactionIsReady(stage.reaction)&&!stage.errors.length?'Ready':'Check volumes'}</span></h3><div class="table-scroll"><table><thead><tr><th>Fragment</th><th>Plate / well</th><th>Stock ng/µL</th><th>Required ng</th><th>Use µL</th></tr></thead><tbody>${stage.reaction.rows.map(p=>`<tr><td>${esc(p.name)}<small class="reaction-warning">${esc(p.warnings.join(' '))}</small></td><td>${esc([plateLabel(p.plate_id),p.well].filter(Boolean).join(' / '))}</td><td>${inventoryQuantity(p.concentration_ng_ul)}</td><td>${inventoryQuantity(p.target_ng)}</td><td>${inventoryQuantity(p.volume_ul)}</td></tr>`).join('')}<tr><td>Other reagents</td><td colspan="3"></td><td>${inventoryQuantity(stage.reaction.master_mix_ul)}</td></tr><tr><td>Water</td><td colspan="3"></td><td>${inventoryQuantity(stage.reaction.water_ul)}</td></tr><tr><td>Total</td><td colspan="3"></td><td>${inventoryQuantity(stage.reaction.reaction_volume_ul)}</td></tr></tbody></table></div>${messages(stage.errors,stage.reaction.warnings)}</div>`).join('');
}

function recommendedAssemblyName(){
  const clean=value=>String(value||'').trim().replace(/\s+/g,'_');
  const groups=selectedNested();
  const names=state.parts.map(part=>{
    const children=groups.filter(group=>group.parent_fragment_id===part.id).flatMap(group=>group.fragment_ids.map(id=>{
      const child=[...state.nestedFragments.values()].find(item=>item.id===id)||state.fragments.find(item=>item.id===id);
      return clean(child?.name||'Fragment'+id);
    }));
    const name=clean(part.name);
    return name+(children.length?'['+children.join('+')+']':'');
  }).filter(Boolean);
  if(!names.length)return '';
  const backbone=state.plasmids.find(item=>'p:'+item.id===$('backbone').value);
  if(backbone)names.unshift(clean(backbone.name));
  const name=names.join('_');
  return name.length<=100?name:name.slice(0,97)+'...';
}
function refreshRecommendedAssemblyName(){
  const button=$('assembly-name-recommendation');if(!button)return;
  const name=recommendedAssemblyName();
  button.textContent='↳ '+name;button.title='Use recommended name: '+name;
  button.setAttribute('aria-label',button.title);button.classList.toggle('hidden',!name);
  const changed=name!==state.assemblyNameRecommendation;
  state.assemblyNameRecommendation=name;
  if(!state.assemblyNameManual&&changed){
    $('assembly-name').value=name||'New assembly';assemblyNameChanged(false);
  }
}
function restoreAssemblyName(request){
  state.assemblyNameManual=request.name_mode?request.name_mode==='manual':!!request.name&&request.name!=='New assembly';
  state.assemblyNameRecommendation=recommendedAssemblyName();
  $('assembly-name').value=request.name||'New assembly';
}
function assemblyNameChanged(manual=true){
  if(manual)state.assemblyNameManual=true;
  scheduleBuildSettingsSave();window.JunctionSandbox?.schedule();renderBuildList();
  if(state.result&&!state.result.storedReference){state.result.name=$('assembly-name').value;delete state.result.viewerPlasmidId;$('viewer-name').value=state.result.name;renderMap();}
}
function applyRecommendedAssemblyName(){
  const name=recommendedAssemblyName();if(!name)return;
  state.assemblyNameManual=false;state.assemblyNameRecommendation=name;
  const input=$('assembly-name');input.value=name;assemblyNameChanged(false);input.focus();
}
function payload(){const value=$('backbone').value;return{name:$('assembly-name').value||'New assembly',name_mode:state.assemblyNameManual?'manual':'auto',enzyme:$('enzyme').value,fragment_ids:state.parts.map(p=>p.id),starter_fragment_id:null,backbone_id:value.startsWith('p:')?Number(value.slice(2)):null,slot_id:value?$('slot').value||null:null,circular:value?true:null,nested_assemblies:selectedNested(),settings:settings()};}
let libraryMetricsTimer=null,libraryMetricsRevision=0;
function scheduleLibraryMetrics(){clearTimeout(libraryMetricsTimer);libraryMetricsTimer=setTimeout(refreshLibraryMetrics,120);}
async function refreshLibraryMetrics(){
  const revision=++libraryMetricsRevision;
  try{const metrics=await api('/api/library/metrics?enzyme='+encodeURIComponent($('enzyme').value));if(revision!==libraryMetricsRevision)return;state.libraryMetrics=metrics;
    $('backbone-count').textContent=metrics.backbones;$('junction-count').textContent=metrics.junctions.length;$('design-count').textContent=metrics.designs;
    if($('junction-list-dialog').open)renderJunctionList();
  }catch(error){toast(error.message);}
}
function renderJunctionList(){
  const junctions=state.libraryMetrics?.junctions||[],enzyme=state.libraryMetrics?.qc_enzyme||$('enzyme').value;
  $('junction-list-summary').textContent=`${junctions.length} unique fusion sequences · Reverse-complement pairs grouped`;
  $('junction-list').innerHTML=junctions.map(item=>{
    const problems=item.problems||[],backbone=item.backbones.length>0;
    // Backbone identity stays purple; palindromes use the shared yellow override.
    const classes='junction-sequence end'+(backbone?' backbone-end':problems.length?' bad':'');
    const problemText=problems.map(problem=>problem.source+': '+problem.message).join('\n');
    const sources=(kind,names)=>names.length?`<div class="junction-source-group ${kind}"><b>${kind==='backbones'?'Backbones':'Fragments'}</b><p>${names.map(name=>`<span>${esc(name)}</span>`).join(' · ')}</p></div>`:'';
    return `<details class="junction-item"><summary><span class="junction-pair">${overhangHtml(item.overhang,classes)}${overhangHtml(item.reverse_complement,classes+' junction-complement')}</span><span class="junction-source-badges">${item.fragments.length?`<span class="junction-source-label fragment">Fragment · ${item.fragments.length}</span>`:''}${backbone?`<span class="junction-source-label backbone">Backbone · ${item.backbones.length}</span>`:''}</span>${problems.length?`<span class="badge error junction-problem" tabindex="0" title="${esc(enzyme+' source digest errors\n'+problemText)}" aria-label="${esc(enzyme+' source digest errors: '+problemText)}">! Problem</span>`:''}<small>${esc(item.enzymes.join(' · '))}</small></summary><div>${sources('fragments',item.fragments)}${sources('backbones',item.backbones)}${problems.length?`<div class="junction-problem-details"><b>${esc(enzyme)} source digest errors</b>${problems.map(problem=>`<p><strong>${esc(problem.source)}</strong> · ${esc(problem.message)}</p>`).join('')}</div>`:''}</div></details>`;
  }).join('')||'<span class="muted">No junctions</span>';
}

async function refresh(){
  const requestedEnzyme=$('enzyme').value;
  const [summary,fragments,plasmids,recipes,rulesResult]=await Promise.all([api('/api/summary'),api('/api/fragments?limit=1000&enzyme='+encodeURIComponent(requestedEnzyme)),api('/api/plasmids?enzyme='+encodeURIComponent(requestedEnzyme)),api('/api/recipes'),api('/api/inventory/rules')]);
  if(requestedEnzyme!==$('enzyme').value)return false;
  applyInventoryRules(rulesResult.rules);
  state.plateLabels=summary.plate_labels||{};state.fragments=fragments;state.plasmids=plasmids;state.recipes=recipes;$('library-count').textContent=summary.fragments;scheduleLibraryMetrics();
  const current=$('backbone').value;
  const examples=plasmids.filter(p=>p.circular&&p.recipe?.example_backbone&&!p.recipe?.legacy_example);
  const templates=plasmids.filter(p=>p.circular&&p.recipe?.backbone_template&&!p.recipe?.example_backbone);
  const saved=plasmids.filter(p=>p.circular&&!p.recipe?.backbone_template&&!p.recipe?.example_backbone&&!p.recipe?.legacy_example);
  const option=p=>{
    const counts=p.backbone_options?.site_counts||{};
    const detected=['BsmBI','BsaI'].filter(enzyme=>counts[enzyme]>0);
    const flag=detected.length?detected.map(enzyme=>'['+enzyme+']').join(' '):'[No GG sites]';
    const title=['BsmBI','BsaI'].map(enzyme=>`${enzyme}: ${counts[enzyme]||0} recognition sites`).join(' · ');
    return `<option value="p:${p.id}" title="${esc(title)}">${esc(p.name)} · ${fmt(p.length,0)} bp · ${esc(flag)}</option>`;
  };
  $('backbone').innerHTML='<option value="">No backbone</option>'+(examples.length?'<optgroup label="Examples">'+examples.map(option).join('')+'</optgroup>':'')+(templates.length?'<optgroup label="Saved backbones">'+templates.map(option).join('')+'</optgroup>':'')+(saved.length?'<optgroup label="Plasmids">'+saved.map(option).join('')+'</optgroup>':'');
  $('backbone').value=[...examples,...templates,...saved].some(p=>'p:'+p.id===current)?current:'';
  const currentPlate=$('plate-filter').value;
  $('plate-filter').innerHTML='<option value="">All plates</option>'+summary.plate_ids.map(p=>`<option value="${esc(p)}" title="${esc(p)}">${esc(plateLabel(p))}</option>`).join('');$('plate-filter').value=summary.plate_ids.includes(currentPlate)?currentPlate:'';
  return true;
}
function matchingPlasmidRecipes(query){
  const tokens=query.toLowerCase().match(/[a-z0-9]+/g)||[];
  if(!tokens.includes('plasmid'))return [];
  return state.recipes.map((recipe,index)=>({recipe,index})).filter(({recipe})=>{
    const text=('plasmid '+recipe.name).toLowerCase().replace(/[^a-z0-9]+/g,' ');
    return tokens.every(token=>text.includes(token));
  });
}
function closeAssemblySearch(){
  clearTimeout(searchTimer);searchCounter++;
  $('search-results').classList.add('hidden');
  $('fragment-search').setAttribute('aria-expanded','false');
}
async function loadRecipe(index){
  const recipe=state.recipes[index];if(!recipe?.available)return;
  closeAssemblySearch();$('fragment-search').value='';
  try{
    await persistPendingBuild();state.activeBuildId=null;state.assemblyNameManual=true;state.plannerStocks={};state.nestedAssemblies=[];state.nestedParent=null;state.nestedDraftStocks={};
    if($('enzyme').value!==recipe.enzyme){$('enzyme').value=recipe.enzyme;await refresh();}
    $('assembly-name').value=recipe.name.replace(' · ','_');$('backbone').value='';
    const ids=recipe.no_backbone_fragment_ids||[recipe.starter_fragment_id,...recipe.fragment_ids].filter(Boolean);
    state.parts=ids.map(id=>state.fragments.find(f=>f.id===id));
    restoreAssemblyName({name:recipe.name.replace(' · ','_'),name_mode:'auto'});
    backboneChanged(false);await checkAssembly();
  }catch(error){toast(error.message);}
}
function backboneChanged(recheck=true){
  const value=$('backbone').value;
  const plasmid=state.plasmids.find(p=>value==='p:'+p.id);
  $('slot-wrap').classList.toggle('hidden',!plasmid);
  $('molar-input-label').textContent=plasmid?'Backbone input':'DNA input';
  $('molar-ratio-label').textContent=plasmid?'Insert : backbone':'Fragment ratio';
  switchBackboneStock(plasmid);renderBackboneStocks();
  if(plasmid){
    $('slot').innerHTML='<option value="">Choose cassette</option>'+plasmid.slots.map(slot=>`<option value="${esc(slot.id)}" title="${esc(slot.left_boundary_enzyme&&slot.right_boundary_enzyme?'5′ boundary: '+slot.left_boundary_enzyme+' · 3′ boundary: '+slot.right_boundary_enzyme:slot.label||slot.id)}">${esc(cassetteFlag(slot)+(slot.label||slot.id))}</option>`).join('');
    if(plasmid.slots.length===1)$('slot').value=plasmid.slots[0].id;
    $('backbone-detail').textContent=plasmid.slots.length?`${fmt(plasmid.length,0)} bp · ${plasmid.slots.length} cassette${plasmid.slots.length===1?'':'s'}`:`No ${$('enzyme').value} cassette`;
  }else{
    $('slot').innerHTML='';$('backbone-detail').textContent='';
  }
  updateCassetteFlag();updateBackboneVolume();renderParts();if(recheck)invalidate();loadResuspension();
}
function nextEnd(){return state.parts.length?state.parts.at(-1).digest.right_overhang:backboneEnds().left||null;}
function backboneEnds() {
  const value = $('backbone').value;
  const slot = state.plasmids.find(p => value === 'p:' + p.id)?.slots.find(s => String(s.id) === $('slot').value);
  return {left:slot?.left_overhang, right:slot?.right_overhang};
}

function chainTopology() {
  if (!state.parts.length) return null;
  if (state.parts.some(f => !f.digest.valid)) return 'invalid';
  if (state.parts.some((f,i) => i > 0 && state.parts[i-1].digest.right_overhang !== f.digest.left_overhang)) return 'invalid';
  const first = state.parts[0].digest.left_overhang;
  const last = state.parts.at(-1).digest.right_overhang;
  if (!$('backbone').value) return first === last ? 'circular' : 'linear';
  const ends = backboneEnds();
  if (!ends.left || !ends.right || first !== ends.left || last !== ends.right) return 'invalid';
  return 'circular';
}

function updateChainTopology(result = null) {
  const topology = result ? result.topology || (result.circular ? 'circular' : 'linear') : chainTopology();
  const badge = $('chain-topology');
  badge.className = 'badge' + (!topology ? ' hidden' : topology === 'invalid' || result?.errors?.length ? ' error' : topology === 'linear' ? ' neutral' : '');
  badge.textContent = topology === 'circular' ? 'Circular' : topology === 'linear' ? 'Linear' : 'Check links';
  badge.title = topology === 'circular' ? 'The final linker joins the first fragment' : topology === 'linear' ? 'The terminal linkers remain open' : 'Resolve incompatible fragment ends';
}

function isBackboneLinker(sequence) {
  if (!/^[ACGT]{4}$/.test(sequence || '')) return false;
  const ends = backboneEnds();
  return sequence === ends.left || sequence === ends.right;
}

function overhangHtml(value,classes='',tag='span'){
  const pal=Overhangs.isPalindromic(value),text=value||'—';
  return `<${tag} class="${classes}${pal?' palindromic-overhang':''}"${pal?` title="${Overhangs.warning}" aria-label="${esc(text)} · ${Overhangs.warning}"`:''}>${esc(text)}</${tag}>`;
}
function overhangMessage(value){
  const text=typeof value==='string'?value:JSON.stringify(value);
  if(!/overhang|fusion|junction/i.test(text))return esc(text);
  return text.split(/(\b[ACGT]{4}\b)/gi).map(token=>Overhangs.isPalindromic(token)?overhangHtml(token):esc(token)).join('');
}
function cassetteFlag(cassette){return Overhangs.labels(cassette?.left_overhang,cassette?.right_overhang).length?'🟨 ':'';}
function updateCassetteFlag(){const ends=backboneEnds(),labels=Overhangs.labels(ends.left,ends.right);$('slot').classList.toggle('palindromic-overhang',!!labels.length);$('slot').title=labels.length?Overhangs.warning+' · '+labels.join(' / '):'';}
function fusionEnds(left,right){return `<span class="fusion-labels" title="Fusion labels on the submitted strand, read from its 5′ end to its 3′ end"><span class="fusion-boundary"><small>5′</small>${overhangHtml(left,'end'+(isBackboneLinker(left)?' backbone-end':''))}</span><span class="fusion-boundary"><small>3′</small>${overhangHtml(right,'end'+(isBackboneLinker(right)?' backbone-end':''))}</span></span>`;}

function validationGlyph(kind){return kind==='pass'?'<svg class="ui-icon" viewBox="0 0 20 20" aria-hidden="true"><path d="m4 10 4 4 8-9"/></svg>':kind==='fail'?'<svg class="ui-icon" viewBox="0 0 20 20" aria-hidden="true"><path d="M10 4v7"/><circle cx="10" cy="15" r="1"/></svg>':'<span aria-hidden="true">…</span>';}
let fragmentCheckAnchor=null;
function hideFragmentCheckTooltip(){fragmentCheckAnchor=null;$('fragment-check-tooltip').classList.add('hidden');}
function showFragmentCheckTooltip(button){
  const info=state.fragmentChecks[Number(button.dataset.fragmentCheck)];if(!info)return;
  fragmentCheckAnchor=button;const tooltip=$('fragment-check-tooltip');
  tooltip.innerHTML=`<b>${esc(info.name)}${info.reverse_complement?' · RC':''} · ${info.kind==='pass'?'Pass':info.kind==='fail'?'Fail':'Checking…'}</b><div class="check-tooltip-ends">5′ ${overhangHtml(info.left_overhang)} · 3′ ${overhangHtml(info.right_overhang)}</div>${info.errors.length?`<ul class="check-errors">${info.errors.map(message=>`<li>${overhangMessage(message)}</li>`).join('')}</ul>`:info.kind==='pass'?'<div>Digest and neighbouring overhangs are compatible.</div>':'<div>Validation in progress.</div>'}${info.warnings.length?`<div class="check-tooltip-warning">Warnings</div><ul>${info.warnings.map(message=>`<li>${overhangMessage(message)}</li>`).join('')}</ul>`:''}`;
  tooltip.classList.remove('hidden');const rect=button.getBoundingClientRect();const box=tooltip.getBoundingClientRect();
  tooltip.style.left=Math.max(12,Math.min(rect.left,window.innerWidth-box.width-12))+'px';
  tooltip.style.top=Math.max(12,Math.min(rect.top-box.height-8>=12?rect.top-box.height-8:rect.bottom+8,window.innerHeight-box.height-12))+'px';
}
function updateFragmentChecks(result=null,failure=''){
  updateNestedCardChecks(result);
  state.fragmentChecks=state.parts.map(part=>{
    const check=result?.fragment_checks?.find(item=>!item.is_backbone&&item.id===part.id);
    const errors=failure?[failure]:check?.errors||part.digest.errors||[];
    return{...(check||{}),name:part.name,left_overhang:check?.left_overhang||part.digest.left_overhang,right_overhang:check?.right_overhang||part.digest.right_overhang,errors,warnings:check?.warnings||part.digest.warnings||[],reverse_complement:check?.reverse_complement??part.reverse_complement??false,kind:errors.length?'fail':check?'pass':'pending'};
  });
  $('selected-parts').querySelectorAll('[data-fragment-check]').forEach(button=>{
    const info=state.fragmentChecks[Number(button.dataset.fragmentCheck)];if(!info)return;
    button.className='fragment-check '+info.kind;button.innerHTML=validationGlyph(info.kind);button.setAttribute('aria-label',`${info.name}: ${info.kind==='pass'?'Pass':info.kind==='fail'?'Fail':'Checking'}`);
    button.onmouseenter=()=>showFragmentCheckTooltip(button);button.onmouseleave=()=>hideFragmentCheckTooltip();button.onfocus=()=>showFragmentCheckTooltip(button);button.onblur=()=>hideFragmentCheckTooltip();button.onclick=event=>{event.stopPropagation();showFragmentCheckTooltip(button);};button.onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();hideFragmentCheckTooltip();}};
  });
  const backbone=result?.fragment_checks?.find(item=>item.is_backbone);const badge=$('backbone-check');
  badge.className=backbone?'backbone-validation '+(backbone.valid?'pass':'fail'):'';badge.innerHTML=backbone?validationGlyph(backbone.valid?'pass':'fail'):'';badge.title=backbone?(backbone.errors.length?backbone.errors.join(' '):'Backbone digest and overhangs are compatible.') :'';
  if(fragmentCheckAnchor?.isConnected)showFragmentCheckTooltip(fragmentCheckAnchor);
}

function fragmentLinker(upstream, downstream) {
  const mismatch = upstream && downstream && upstream !== downstream;
  const label = upstream || downstream || '—';
  const backbone = isBackboneLinker(upstream) || isBackboneLinker(downstream);
  const description = `${backbone ? 'Backbone linker' : 'Linker'}: ${label}${mismatch ? ' / ' + downstream + ' (mismatch)' : ''}`;
  return `<div class="fragment-linker${backbone ? ' backbone-linker' : ''}${mismatch ? ' incompatible' : ''}" title="${esc(description)}" aria-label="${esc(description)}">${overhangHtml(label,'linker-sequence'+(isBackboneLinker(label)?' backbone-overhang':''))}${mismatch ? `${overhangHtml(downstream,'linker-other'+(isBackboneLinker(downstream)?' backbone-overhang':''))}` : ''}</div>`;
}

let buildSaveTimer=null,pendingBuildSave=null,savingBuildId=null,buildWriteChain=Promise.resolve(),buildPreviewTimer;
function buildDesign(request){return JSON.stringify([request.name,request.enzyme,request.fragment_ids,request.starter_fragment_id||null,request.backbone_id||null,String(request.slot_id||''),request.nested_assemblies||[]]);}
function activeBuild(){return state.buildList.find(item=>item.id===state.activeBuildId);}
function buildIsDirty(){const item=activeBuild();return item&&buildDesign(item.request)!==buildDesign(payload());}
function updateBuildActions(){
  const disabled=state.buildBusy||(!state.parts.length&&!$('backbone').value);
  if($('add-build-inline'))$('add-build-inline').disabled=disabled;
  $('export-build-genbank').disabled=state.buildBusy||!state.buildList.length;
}
const planInputTimers=new Map();
function flushPlanInputs(){for(const pending of [...planInputTimers.values()]){clearTimeout(pending.timer);pending.save();}}
function queuePlanInput(input,key,commit){
  const previous=planInputTimers.get(key);if(previous)clearTimeout(previous.timer);planInputTimers.delete(key);
  input.setAttribute('aria-invalid',String(!input.checkValidity()));if(!input.checkValidity())return;
  const save=()=>{planInputTimers.delete(key);commit();};planInputTimers.set(key,{save,timer:setTimeout(save,300)});
}
const planRowDrafts=new Map(),buildPlanErrors=new Set(),planEditOperations=new Set(),backboneStockCache=new Map();
let selectedStockKey=null,plannerStockKey=null;
const buildPlanFields={backbone_pmol:['DNA input pmol',0],insert_ratio:['Insert : backbone',0],backbone_stock_ng_ul:['Backbone stock ng/µL',0],master_mix_volume_ul:['Other reagents µL',0],reaction_volume_ul:['Total µL',0]};
function backboneIdentity(request){return request.backbone_id?{kind:'plasmid',id:request.backbone_id}:request.starter_fragment_id?{kind:'fragment',id:request.starter_fragment_id}:null;}
function backboneStockGroups(){
  const groups=new Map();
  for(const item of state.buildList){const ref=backboneIdentity(item.request);if(!ref)continue;const key=ref.kind+':'+ref.id;
    if(!groups.has(key)){const source=(ref.kind==='plasmid'?state.plasmids:state.fragments).find(p=>p.id===ref.id),part=item.plan?.parts.find(p=>p.role==='backbone');groups.set(key,{...ref,key,name:source?.name||part?.name||'Backbone '+ref.id,items:[]});}
    groups.get(key).items.push(item);
  }
  return [...groups.values()];
}
function rememberBackboneStock(){if(selectedStockKey)backboneStockCache.set(selectedStockKey,$('backbone-stock').value?Number($('backbone-stock').value):null);}
function switchBackboneStock(plasmid){
  const key=plasmid?'plasmid:'+plasmid.id:null;if(key===selectedStockKey)return;rememberBackboneStock();selectedStockKey=key;
  const group=backboneStockGroups().find(g=>g.key===key),stocks=[...new Set((group?.items||[]).map(item=>item.request.settings.backbone_stock_ng_ul??null))];
  $('backbone-stock').value=(backboneStockCache.has(key)?backboneStockCache.get(key):stocks.length===1?stocks[0]:null)??'';
}
function backboneStockChoices(){
  const groups=backboneStockGroups(),current=state.plasmids.find(p=>$('backbone').value==='p:'+p.id);
  if(current&&!groups.some(g=>g.key==='plasmid:'+current.id))groups.unshift({kind:'plasmid',id:current.id,key:'plasmid:'+current.id,name:current.name,items:[]});
  return groups;
}
function plannerBackboneStock(group){
  if(!group)return{value:null,mixed:false};
  const stocks=[...new Set(group.items.map(item=>({...item.request.settings,...planRowDrafts.get(item.id)}).backbone_stock_ng_ul??null))];
  return{value:group.items.length?(stocks.length===1?stocks[0]:null):selectedStockKey===group.key?($('backbone-stock').value||null):(backboneStockCache.get(group.key)??null),mixed:stocks.length>1};
}
function renderBackboneStocks(force=false){
  const groups=backboneStockChoices(),select=$('backbone-stock-select'),input=$('planner-backbone-stock');
  if(!groups.some(g=>g.key===plannerStockKey))plannerStockKey=groups.find(g=>g.key===selectedStockKey)?.key||groups[0]?.key||null;
  const options=groups.map(g=>`<option value="${g.key}">${esc(g.name)}</option>`).join('');
  if(select.innerHTML!==options)select.innerHTML=options;
  select.value=plannerStockKey||'';select.disabled=!groups.length;input.disabled=!groups.length;
  $('backbone-stock-field').classList.toggle('hidden',!groups.length);
  const group=groups.find(g=>g.key===plannerStockKey),stock=plannerBackboneStock(group),count=group?.items.length||0;
  $('backbone-stock-usage').textContent=count?`${count} build${count===1?'':'s'}${stock.mixed?' · Mixed stocks':''}`:'';
  input.setAttribute('aria-label',group?'Stock for '+group.name:'Backbone stock');
  input.title=count?'Apply stock to all '+count+' builds using this backbone':'Stock for the current assembly';
  if(force||(document.activeElement!==input&&!planInputTimers.has('backbone:'+plannerStockKey))){
    input.value=stock.value??'';input.placeholder=stock.mixed?'Mixed stocks':'Optional';input.removeAttribute('aria-invalid');
  }
  updateBackboneVolume();
}
function selectPlannerBackboneStock(){
  const key=$('backbone-stock-select').value;
  flushPlanInputs();plannerStockKey=key;renderBackboneStocks(true);
}
function editPlannerBackboneStock(){
  const input=$('planner-backbone-stock'),key=plannerStockKey;
  if(!key)return;
  const[kind,id]=key.split(':'),value=input.value,valid=input.checkValidity();
  updateBackboneVolume();
  // Capture the identity and value before a dropdown change can reuse the input.
  queuePlanInput(input,'backbone:'+key,()=>applyBackboneStock(kind,Number(id),{value,checkValidity:()=>valid,reportValidity:()=>input.reportValidity()}));
}
function renderBuildPlans(){
  const body=$('build-plans-body');
  if((body.contains(document.activeElement)&&document.activeElement.matches('[data-build-setting]'))||[...planInputTimers.keys()].some(key=>key.startsWith('row:'))||body.querySelector('input[aria-invalid="true"]')){updateBuildPlanOutputs();return;}
  body.innerHTML=state.buildList.map(item=>{
    const settings={...item.request.settings,...planRowDrafts.get(item.id)};
    const input=key=>{const[label,min]=buildPlanFields[key],disabled=key==='backbone_stock_ng_ul'&&!backboneIdentity(item.request);return `<input type="number" data-build-setting="${key}" data-build-id="${item.id}" min="${min}" step="any" ${key==='backbone_stock_ng_ul'?'':'required'} ${disabled?'disabled':''} value="${settings[key]??''}" aria-label="${label} for ${esc(item.request.name)}">`;};
    return `<tr data-build-plan="${item.id}"><td><button class="text-button" data-plan-build="${item.id}">${esc(item.request.name)}</button></td><td>${esc(item.request.enzyme)}</td><td>${input('backbone_pmol')}</td><td>${input('insert_ratio')}</td><td>${input('backbone_stock_ng_ul')}</td><td data-plan-output="dna"></td><td>${input('master_mix_volume_ul')}</td><td data-plan-output="water"></td><td>${input('reaction_volume_ul')}</td><td data-plan-output="status"></td></tr>`;
  }).join('');
  body.querySelectorAll('[data-plan-build]').forEach(button=>button.onclick=()=>loadQueuedBuild(Number(button.dataset.planBuild)));
  body.querySelectorAll('[data-build-setting]').forEach(input=>{input.oninput=input.onchange=()=>{input.closest('tr').querySelector('[data-plan-output="status"]').textContent=input.checkValidity()?'Saving…':'Check value';queuePlanInput(input,'row:'+input.dataset.buildId+':'+input.dataset.buildSetting,()=>saveBuildPlanField(input));};});
  updateBuildPlanOutputs();
}
function updateBuildPlanOutputs(){
  for(const item of state.buildList){const row=$('build-plans-body').querySelector(`[data-build-plan="${item.id}"]`);if(!row)continue;const reaction=item.plan?.reaction,parts=reaction?.rows||[],dna=parts.length&&parts.every(p=>p.volume_ul!==null)?parts.reduce((sum,p)=>sum+p.volume_ul,0):null;
    const values={...item.request.settings,...planRowDrafts.get(item.id)};row.querySelectorAll('[data-build-setting]').forEach(input=>{if(input!==document.activeElement&&input.getAttribute('aria-invalid')!=='true'&&!planInputTimers.has('row:'+input.dataset.buildId+':'+input.dataset.buildSetting))input.value=values[input.dataset.buildSetting]??'';});
    row.querySelector('[data-plan-output="dna"]').textContent=inventoryQuantity(dna);row.querySelector('[data-plan-output="water"]').textContent=inventoryQuantity(reaction?.water_ul);
    row.querySelector('[data-plan-output="status"]').textContent=buildPlanErrors.has(item.id)?'Not saved':planRowDrafts.has(item.id)||[...planInputTimers.keys()].some(key=>key.startsWith('row:'+item.id+':'))?'Saving…':item.id===state.activeBuildId&&buildIsDirty()?'Unsaved changes':!item.plan||item.plan.errors?.length?'Fail':item.status==='Ready'?'Pass':'Check volumes';
  }
}
function syncActivePlanPatch(id,changes){
  if(state.activeBuildId!==id)return;
  for(const[inputId,key]of Object.entries(plannerInputKeys))if(key in changes){$(inputId).value=changes[key];state.plannerOverrides[key]=changes[key];}
  if('backbone_stock_ng_ul' in changes){$('backbone-stock').value=changes.backbone_stock_ng_ul??'';rememberBackboneStock();}
  updateBackboneVolume();
}
function trackPlanEdit(operation){planEditOperations.add(operation);operation.finally(()=>planEditOperations.delete(operation));return operation;}
function saveBuildPlanField(input){
  if(!input.checkValidity()){input.reportValidity();return;}
  const id=Number(input.dataset.buildId),key=input.dataset.buildSetting,value=input.value===''?null:Number(input.value),changes={[key]:value};
  planRowDrafts.set(id,{...planRowDrafts.get(id),...changes});buildPlanErrors.delete(id);syncActivePlanPatch(id,changes);updateBuildPlanOutputs();
  return trackPlanEdit((async()=>{
    try{await persistPendingBuild();const operation=buildWriteChain.catch(()=>{}).then(async()=>{
      const item=await api('/api/build-list/'+id+'/settings',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(changes)});
      const drafts=planRowDrafts.get(id);if(drafts?.[key]===value){delete drafts[key];if(!Object.keys(drafts).length)planRowDrafts.delete(id);}buildPlanErrors.delete(id);replaceBuild(item);
      if(state.activeBuildId===id){loadResuspension();checkAssembly();}
    });buildWriteChain=operation;await operation;}
    catch(error){buildPlanErrors.add(id);updateBuildPlanOutputs();toast('Build not saved: '+error.message);}
  })());
}
function applyBackboneStock(kind,id,input){
  if(!id||!input.checkValidity()){input.reportValidity();return;}
  const value=input.value===''?null:Number(input.value),key=kind+':'+id;backboneStockCache.set(key,value);
  if(selectedStockKey===key){$('backbone-stock').value=value??'';updateBackboneVolume();if(activeBuild())scheduleBuildSettingsSave();}
  const ids=backboneStockGroups().find(g=>g.key===key)?.items.map(i=>i.id)||[];
  for(const buildId of ids){planRowDrafts.set(buildId,{...planRowDrafts.get(buildId),backbone_stock_ng_ul:value});buildPlanErrors.delete(buildId);}updateBuildPlanOutputs();
  return trackPlanEdit((async()=>{
    try{await persistPendingBuild();const operation=buildWriteChain.catch(()=>{}).then(async()=>{
      const result=await api('/api/build-list/backbone-stocks/apply',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,id,stock_ng_ul:value})});
      for(const item of result.items){const index=state.buildList.findIndex(entry=>entry.id===item.id);if(index>=0)state.buildList[index]=item;const drafts=planRowDrafts.get(item.id);if(drafts?.backbone_stock_ng_ul===value){delete drafts.backbone_stock_ng_ul;if(!Object.keys(drafts).length)planRowDrafts.delete(item.id);}buildPlanErrors.delete(item.id);syncActivePlanPatch(item.id,{backbone_stock_ng_ul:value});}
      renderBuildList();loadResuspension();if(state.parts.length||$('backbone').value)checkAssembly();
    });buildWriteChain=operation;await operation;}
    catch(error){for(const buildId of ids)buildPlanErrors.add(buildId);updateBuildPlanOutputs();toast('Backbone stock not saved: '+error.message);}
  })());
}
function renderBuildList(){
  window.JunctionWorksheetController?.syncTitles();
  updateBuildListOutcome();updateBuildActions();
  hideBuildPreview();
  $('build-list-count').textContent=state.buildList.length?`(${state.buildList.length})`:'';
  $('undo-build-remove').classList.toggle('hidden',!state.lastRemovedBuildId);
  document.querySelectorAll('[data-worksheet-export="build-list"]').forEach(button=>button.disabled=!state.buildList.length);
  $('build-list-items').innerHTML=state.buildList.map(item=>{
    const selected=item.id===state.activeBuildId;
    const message=state.buildSaveError===item.id?'Not saved':pendingBuildSave?.id===item.id||savingBuildId===item.id?'Saving…':selected&&buildIsDirty()?'Not saved':!item.plan||item.plan.errors?.length?'Fail':item.status==='Ready'?'Pass':'Pass · '+item.status;
    const reaction=item.plan?.reaction;
    const detail=item.error||item.plan?.errors?.join(' ')||reaction?.warnings?.join(' ')||'';
    return `<div class="build-list-item${selected?' active':''}"><button class="build-list-open" data-plan-build="${item.id}" aria-describedby="build-preview" aria-label="Open ${esc(item.request.name)}"><b>${esc(item.request.name)}</b><span>${esc(item.request.enzyme)} · ${item.request.fragment_ids.length} fragment${item.request.fragment_ids.length===1?'':'s'}${item.request.nested_assemblies?.length?' + '+item.request.nested_assemblies.reduce((sum,g)=>sum+g.fragment_ids.length,0)+' nested':''}${item.plan?' · '+fmt(item.plan.length,0)+' bp':''}</span><small class="${message==='Pass'?'build-ready':message==='Fail'?'build-fail':'build-check'}">${esc(message)}</small></button><button class="build-list-remove" data-remove-build="${item.id}" aria-label="Remove ${esc(item.request.name)} from build list" title="Remove">${inventoryIcon('close')}</button></div>`;
  }).join('')||'<span class="build-list-empty">No assemblies</span>';
  $('build-plans-panel').classList.toggle('hidden',!state.buildList.length);
  renderBuildPlans();renderBackboneStocks();renderExportAssemblies();
  $('build-list-items').querySelectorAll('[data-plan-build]').forEach(button=>{button.onclick=()=>loadQueuedBuild(Number(button.dataset.planBuild));button.onmouseenter=()=>showBuildPreview(button);button.onmouseleave=scheduleHideBuildPreview;button.onfocus=()=>showBuildPreview(button);button.onblur=scheduleHideBuildPreview;button.onkeydown=event=>{if(event.key==='Escape')hideBuildPreview();};});
  $('build-list-items').querySelectorAll('[data-remove-build]').forEach(button=>button.onclick=()=>removeQueuedBuild(Number(button.dataset.removeBuild)));
}
async function refreshExportAssemblies(){
  $('export-assemblies-summary').textContent='Updating…';$('export-assemblies-download').disabled=true;
  try{flushPlanInputs();await persistPendingBuild();await Promise.all([...planEditOperations]);await loadBuildList();}
  catch(error){$('export-assemblies-summary').textContent='Could not load plans';toast(error.message);}
}
function exportPlateLabel(label,plates){
  const plate=plates.find(p=>p.short===label),color=plate?.text_color;
  return color&&/^[0-9A-F]{6}$/i.test(color)?`<span class="export-plate-name" style="--plate-color:#${color}">${esc(label)}</span>`:esc(label);
}
function exportInputTuples(value,plates){
  const aliases=[...plates].sort((a,b)=>b.short.length-a.short.length);
  return String(value??'').split('\n').map(line=>{
    const plate=aliases.find(p=>line.startsWith('('+p.short+'-'));
    return plate?'('+exportPlateLabel(plate.short,plates)+esc(line.slice(plate.short.length+1)):esc(line);
  }).join('\n');
}
function renderExportAssemblies(){
  const snapshot=state.exportSnapshot,rows=snapshot?.rows||[],metadata=snapshot?.metadata||[],plates=snapshot?.plates||[];
  const inputColumn=snapshot?.headers?.indexOf('Inputs (Plate-Well-µL)');
  $('export-assemblies-empty').classList.toggle('hidden',!!rows.length);
  const ready=state.buildList.filter(item=>item.status==='Ready').length;
  $('export-assemblies-summary').textContent=`${state.buildList.length} assembl${state.buildList.length===1?'y':'ies'} · ${ready} ready · ${state.buildList.length-ready} to check`;
  const head=labels=>labels.length?'<tr>'+labels.map(label=>`<th>${esc(label)}</th>`).join('')+'</tr>':'';
  $('export-assemblies-head').innerHTML=head(snapshot?.headers||[]);
  $('export-assemblies-body').innerHTML=rows.map(row=>'<tr>'+row.map((value,i)=>`<td${i===inputColumn?' class="export-input-tuples"':''}>${i===row.length-1?value==='Pass'?'<span class="build-ready">Pass</span>':`<details class="export-checks"><summary>Check</summary>${esc(value)}</details>`:i===inputColumn?exportInputTuples(value,plates):typeof value==='number'?inventoryQuantity(value):esc(value??'—')}</td>`).join('')+'</tr>').join('');
  $('export-fragments-head').innerHTML=head((snapshot?.metadata_headers||[]).slice(0,10));
  $('export-fragments-body').innerHTML=metadata.map(row=>`<tr title="${esc(row.slice(10).filter(Boolean).join('\n'))}">`+row.slice(0,10).map((value,i)=>`<td>${i===2?exportPlateLabel(value??'',plates):typeof value==='number'?i===4?fmt(value,0):inventoryQuantity(value):esc(value??'—')}</td>`).join('')+'</tr>').join('');
  $('export-plates').innerHTML=plates.map(plate=>`<div>${exportPlateLabel(plate.short,plates)} <span class="export-plate-name" style="--plate-color:#${plate.text_color}">${esc(plate.name)}</span></div>`).join('');
}
function hideBuildPreview(){clearTimeout(buildPreviewTimer);$('build-preview').classList.add('hidden');}
function scheduleHideBuildPreview(){clearTimeout(buildPreviewTimer);buildPreviewTimer=setTimeout(hideBuildPreview,150);}
function showBuildPreview(button){
  clearTimeout(buildPreviewTimer);
  const item=state.buildList.find(entry=>entry.id===Number(button.dataset.planBuild));if(!item)return;
  const request=item.id===state.activeBuildId?payload():item.request;
  const parts=[...(request.backbone_id?[{id:'p:'+request.backbone_id,is_backbone:true}]:[]),...[request.starter_fragment_id,...request.fragment_ids].filter(Boolean).map(id=>({id}))].map(ref=>{
    const source=ref.is_backbone?state.plasmids.find(p=>'p:'+p.id===ref.id):state.fragments.find(p=>p.id===ref.id);
    const saved=item.plan?.parts.find(p=>ref.is_backbone?p.role==='backbone':p.id===ref.id);
    const checked=item.plan?.fragment_checks?.find(p=>ref.is_backbone?p.is_backbone:p.id===ref.id&&!p.is_backbone);
    const digest=item.id===state.activeBuildId?source?.digest:checked||(request.enzyme===$('enzyme').value?source?.digest:null);
    return{...saved,...source,digest,is_backbone:ref.is_backbone};
  });
  const tooltip=$('build-preview');tooltip.innerHTML=`<b>${esc(request.name)}</b><small>${esc(request.enzyme)} · ${parts.length} inputs</small><ol>${parts.map(part=>`<li><div><strong>${esc(part.name||'Unavailable fragment')}</strong>${part.is_backbone?'<span class="preview-backbone">Backbone</span>':''}<small>${esc([plateLabel(part.plate_id),part.well].filter(Boolean).join(' / '))}${part.physical_length||part.length?' · '+fmt(part.physical_length||part.length,0)+' bp':''}</small></div>${part.digest?`<code>5′ ${overhangHtml(part.digest.left_overhang)}<br>3′ ${overhangHtml(part.digest.right_overhang)}</code>`:''}</li>${(request.nested_assemblies||[]).filter(g=>g.parent_fragment_id===part.id).map(g=>`<li class="preview-nested"><small>${esc(g.mode==='separate'?'Separate first':'Together')} · ${g.fragment_ids.map(id=>esc(item.plan?.nested_assemblies?.flatMap(n=>n.children).find(c=>c.id===id)?.name||'Fragment '+id)).join(' · ')}</small></li>`).join('')}`).join('')}</ol>`;
  tooltip.classList.remove('hidden');const rect=button.getBoundingClientRect(),box=tooltip.getBoundingClientRect();tooltip.style.left=Math.max(12,Math.min(rect.left,window.innerWidth-box.width-12))+'px';tooltip.style.top=Math.max(12,Math.min(rect.bottom+8+box.height<=window.innerHeight-12?rect.bottom+8:rect.top-box.height-8,window.innerHeight-box.height-12))+'px';
}
async function loadBuildList(){const data=await api('/api/build-list');state.buildList=data.items;state.exportSnapshot=data.export;state.lastRemovedBuildId=data.last_removed_id;if(!activeBuild())state.activeBuildId=null;renderBuildList();}
function replaceBuild(item){window.JunctionSandbox?.schedule();const index=state.buildList.findIndex(entry=>entry.id===item.id);if(index<0)state.buildList.push(item);else state.buildList[index]=item;state.buildList.sort((a,b)=>a.id-b.id);renderBuildList();}
async function addCurrentBuild(){
  if(state.buildBusy)return;state.buildBusy=true;
  updateBuildActions();
  try{
    const request=structuredClone(payload());
    // Adding captures an independent entry. Keep the current design available
    // as a draft for the next variant, without autosaving back into this row.
    state.activeBuildId=null;window.JunctionSandbox?.schedule();renderBuildList();
    await persistPendingBuild();
    const item=await api('/api/build-list',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});
    state.buildSaveError=null;replaceBuild(item);
    toast('Added to build list');
  }catch(error){toast(error.message);}finally{state.buildBusy=false;updateBuildActions();}
}
function scheduleBuildSettingsSave(){
  if(!activeBuild())return;
  if(buildIsDirty()){
    state.activeBuildId=null;window.JunctionSandbox?.schedule();renderBuildList();return;
  }
  if(!state.parts.length&&!$('backbone').value){clearTimeout(buildSaveTimer);pendingBuildSave=null;renderBuildList();return;}
  if([...document.querySelectorAll('.reaction-panel input')].some(input=>!input.matches(':disabled')&&!input.checkValidity())||$('resuspension-body').querySelector('input[aria-invalid="true"]')){clearTimeout(buildSaveTimer);pendingBuildSave=null;renderBuildList();return;}
  clearTimeout(buildSaveTimer);pendingBuildSave={id:state.activeBuildId,request:structuredClone(payload())};state.buildSaveError=null;renderBuildList();
  buildSaveTimer=setTimeout(()=>persistPendingBuild().catch(()=>{}),400);
}
async function persistPendingBuild(){
  clearTimeout(buildSaveTimer);
  const pending=pendingBuildSave;pendingBuildSave=null;
  if(pending)buildWriteChain=buildWriteChain.catch(()=>{}).then(async()=>{
    savingBuildId=pending.id;renderBuildList();
    try{const item=await api('/api/build-list/'+pending.id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(pending.request)});state.buildSaveError=null;replaceBuild(item);}
    catch(error){state.buildSaveError=pending.id;renderBuildList();toast('Build not saved: '+error.message);throw error;}
    finally{savingBuildId=null;renderBuildList();}
  });
  return pending?buildWriteChain:buildWriteChain.catch(()=>{});
}
function setPlannerInputs(values){
  state.plannerOverrides={...readPlannerOverrides(),...Object.fromEntries(Object.entries(values).filter(([key])=>key in plannerRuleDefaults()))};
  for(const[id,key]of Object.entries(plannerInputKeys))$(id).value=values[key]??plannerRuleDefaults()[key];
  state.plannerStocks=structuredClone(values.fragment_stock_overrides||{});
  $('assume-stock').checked=values.planner_stock_mode?values.planner_stock_mode==='saved':true;updatePlannerStockMode();
  $('backbone-stock').value=values.backbone_stock_ng_ul??'';rememberBackboneStock();
  updatePlannerRuleLabels();updateBackboneVolume();
}
async function loadQueuedBuild(id){
  try{
    await persistPendingBuild();
    const item=state.buildList.find(entry=>entry.id===id);if(!item)return;
    const request=item.request;
    if(request.starter_fragment_id)throw Error('This queued build uses a backbone fragment. It can be exported from the list, but the builder requires a plasmid backbone.');
    if($('enzyme').value!==request.enzyme){$('enzyme').value=request.enzyme;await refresh();}
    const ids=[request.starter_fragment_id,...request.fragment_ids].filter(Boolean);
    const parts=ids.map(partId=>state.fragments.find(f=>f.id===partId));
    if(parts.some(part=>!part))throw Error('A queued fragment is unavailable. Restore it from Bin first.');
    if(request.backbone_id&&!state.plasmids.some(p=>p.id===request.backbone_id))throw Error('The queued backbone is unavailable. Restore it from Bin first.');
    state.activeBuildId=null;state.assemblyNameManual=true;
    $('assembly-name').value=request.name;$('backbone').value=request.backbone_id?'p:'+request.backbone_id:'';
    state.parts=parts;state.nestedDraftStocks={};state.nestedAssemblies=structuredClone(request.nested_assemblies||[]);state.nestedParent=null;await loadNestedChildren();restoreAssemblyName(request);backboneChanged(false);
    if(request.slot_id!==null)$('slot').value=String(request.slot_id);
    setPlannerInputs(request.settings);
    state.activeBuildId=id;renderParts();invalidate();selectSubtab(state.subtab);await checkAssembly();renderBuildList();
  }catch(error){toast(error.message);}
}
async function newBuild(){
  try{await persistPendingBuild();state.activeBuildId=null;state.parts=[];state.nestedAssemblies=[];state.nestedParent=null;state.nestedDraftStocks={};$('backbone').value='';restoreAssemblyName({name_mode:'auto'});setPlannerInputs({...plannerRuleDefaults(),...readPlannerOverrides()});backboneChanged();renderBuildList();selectSubtab('assembly');}
  catch(error){toast(error.message);}
}
async function removeQueuedBuild(id){
  try{await persistPendingBuild();await api('/api/build-list/'+id,{method:'DELETE'});state.buildList=state.buildList.filter(item=>item.id!==id);state.lastRemovedBuildId=id;if(state.activeBuildId===id)state.activeBuildId=null;renderBuildList();toast('Removed from build list');}catch(error){toast(error.message);}
}
async function undoBuildRemove(){try{await api('/api/build-list/'+state.lastRemovedBuildId+'/restore',jsonBody({}));await loadBuildList();toast('Build restored');}catch(error){toast(error.message);}}

let fragmentSwapCandidates = [],swapSearchCounter=0;
let fragmentSwapAnchor = null;
let fragmentDragEnded = 0;

function closeFragmentSwap(restoreFocus = false) {
  swapSearchCounter++;
  const anchor = fragmentSwapAnchor;
  state.swapIndex = null;
  fragmentSwapAnchor = null;
  $('fragment-swap').classList.add('hidden');
  document.querySelectorAll('[data-swap-index]').forEach(b => b.setAttribute('aria-expanded', 'false'));
  document.querySelectorAll('.fragment-tile.is-swapping').forEach(el => el.classList.remove('is-swapping'));
  if (restoreFocus && anchor?.isConnected) anchor.focus({preventScroll:true});
}

function positionFragmentSwap() {
  if (!fragmentSwapAnchor?.isConnected) return;
  const rect = fragmentSwapAnchor.getBoundingClientRect();
  const popup = $('fragment-swap');
  const width = popup.offsetWidth;
  const height = popup.offsetHeight;
  const below = rect.bottom + 9;
  const above = rect.top - height - 9;
  popup.style.left = Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)) + 'px';
  popup.style.top = Math.max(12, Math.min(below + height <= window.innerHeight - 12 ? below : above, window.innerHeight - height - 12)) + 'px';
}

async function renderSwapOptions() {
  const token=++swapSearchCounter,index=state.swapIndex,enzyme=$('enzyme').value;
  const query = $('swap-search').value.trim().toLowerCase();
  let candidates=fragmentSwapCandidates;
  if(query){
    try{
      const results=await api('/api/fragments?'+new URLSearchParams({q:query,enzyme,limit:'1000'}));
      if(token!==swapSearchCounter||state.swapIndex!==index||$('enzyme').value!==enzyme)return;
      const matches=new Map(results.map(part=>[part.id,part.search_match]));
      candidates=candidates.filter(part=>matches.has(part.id)).map(part=>({...part,search_match:matches.get(part.id)}));
    }catch(error){if(token===swapSearchCounter){$('swap-options').innerHTML='<div class="swap-empty">'+esc(error.message)+'</div>';positionFragmentSwap();}return;}
  }
  $('swap-options').innerHTML = candidates.length ? candidates.map(f => `<button class="swap-option" role="option" data-swap-id="${f.id}"><div><span class="swap-name">${esc(f.name)}${reverseCompFlag(f,true)}${FragmentSearch.badge(f)}</span>${f.swap_backbone_mismatches?.length?`<span class="badge warn" title="${esc(f.swap_backbone_mismatches.join(" · "))}">Backbone mismatch</span>`:""}<span class="swap-location">${esc(FragmentSearch.location(f,plateLabel))} · ${fmt(f.physical_length,0)} bp</span></div><div class="swap-ends">${fusionEnds(f.digest.left_overhang,f.digest.right_overhang)}</div></button>`).join('') : `<div class="swap-empty">${query ? 'No matching alternatives' : 'No alternatives'}</div>`;
  $('swap-options').querySelectorAll('[data-swap-id]').forEach(button => button.onclick = event => {
    event.stopPropagation();
    const index = state.swapIndex;
    const replacement = fragmentSwapCandidates.find(f => f.id === Number(button.dataset.swapId));
    if (index === null || !replacement || !state.parts[index]) return;
    closeFragmentSwap();
    state.parts[index] = replacement;
    renderParts();
    invalidate();
    document.querySelector(`[data-swap-index="${index}"]`)?.focus({preventScroll:true});
    checkAssembly();
  });
  positionFragmentSwap();
}

function compatibleFragmentAlternatives(index) {
  const current = state.parts[index];
  if (!current) return [];
  return FragmentOrientation.alternatives(state.parts,state.fragments,index,{...backboneEnds(),hasBackbone:!!$('backbone').value,closed:chainTopology()==='circular'});
}

function openFragmentSwap(index, anchor) {
  if (performance.now() - fragmentDragEnded < 200) return;
  if (state.swapIndex === index) { closeFragmentSwap(true); return; }
  closeFragmentSwap();
  const current = state.parts[index];
  if (!current) return;
  fragmentSwapCandidates = compatibleFragmentAlternatives(index);
  state.swapIndex = index;
  fragmentSwapAnchor = anchor;
  $('swap-current').textContent = current.name;
  $('swap-current').title = `${current.plate_id} / ${current.well}`;
  $('swap-search').value = '';
  $('fragment-swap').classList.remove('hidden');
  anchor.setAttribute('aria-expanded', 'true');
  anchor.closest('.fragment-tile').classList.add('is-swapping');
  renderSwapOptions();
  $('swap-search').focus({preventScroll:true});
}

function nestedGroupKey(group){return group.parent_fragment_id+':'+group.cassette_id;}
function inlineNestedInfo(parent,group){
  const result=state.assemblyResult?.nested_assemblies?.find(g=>nestedGroupKey(g)===nestedGroupKey(group));
  const cassette=parent.digest.nested_cassettes?.find(c=>c.id===group.cassette_id)||result?.cassette;
  const enzyme=group.mode==='together'?$('enzyme').value:cassette?.enzyme;
  const parts=group.fragment_ids.map(id=>displayNestedChild(id,enzyme,group)||[...state.nestedFragments.values()].find(part=>part.id===id)||{id,name:'Fragment '+id,digest:{}});
  return{result,cassette,parts};
}
function nestedCardIndicator(parent){
  const groups=selectedNested().filter(g=>g.parent_fragment_id===parent.id);
  const cassettes=parent.digest.nested_cassettes||[];
  if(!cassettes.length&&!groups.length)return '';
  const count=groups.reduce((n,g)=>n+g.fragment_ids.length,0);
  const blocks=Array.from({length:Math.min(count||3,4)},(_,i)=>`<rect x="${5+i*10}" y="7" width="7" height="9" rx="1.5"/>`).join('');
  return `<button type="button" class="nested-card-trigger${count?' has-donors':''}" data-nested-parent="${parent.id}" aria-label="Nested assembly in ${esc(parent.name)}, ${count} fragments" aria-controls="nested-assembly-editor" aria-expanded="false" aria-describedby="nested-card-tooltip"><svg class="ui-icon" viewBox="0 0 48 24" aria-hidden="true"><path class="nest-bracket" d="M4 3H1v18h3M44 3h3v18h-3"/><path class="nest-join" d="M5 11.5h36"/>${blocks}</svg><span>${count?`<b>${count}</b> nested`:`${cassettes.length} cassette${cassettes.length===1?'':'s'}`}</span><span class="nested-card-status" data-nested-card-status aria-hidden="true"></span><span class="nested-card-chevron" aria-hidden="true">⌄</span></button>`;
}
function syncNestedCardExpansion(){
  const visible=!$('nested-assembly-editor').classList.contains('hidden');
  $('selected-parts').querySelectorAll('[data-nested-parent]').forEach(button=>{
    const active=visible&&Number(button.dataset.nestedParent)===state.nestedParent;
    button.setAttribute('aria-expanded',String(active));button.closest('.fragment-tile').classList.toggle('is-nesting',active);
  });
}
let nestedCardAnchor=null,nestedCardCheckResult=null;
function hideNestedCardTooltip(){nestedCardAnchor=null;$('nested-card-tooltip').classList.add('hidden');}
function nestedCardDetails(parent){
  const groups=selectedNested().filter(g=>g.parent_fragment_id===parent.id);
  const cassettes=parent.digest.nested_cassettes||[];
  const items=[...cassettes,...groups.filter(g=>!cassettes.some(c=>c.id===g.cassette_id)).map(g=>({id:g.cassette_id}))];
  return `<b class="nested-tooltip-title">${esc(parent.name)}</b>${items.map(c=>{
    const group=groups.find(g=>g.cassette_id===c.id);
    const info=group?inlineNestedInfo(parent,group):null;
    const checked=group?nestedCardCheckResult?.nested_assemblies?.find(g=>nestedGroupKey(g)===nestedGroupKey(group)):null;
    const cassette=info?.cassette||c;
    return `<section><div class="nested-tooltip-heading"><b>${esc(cassette.enzyme||'Cassette unavailable')}</b><span>${group?(group.mode==='separate'?'Separate first':'Together'):'Empty'}</span>${group?`<strong class="nested-card-status ${checked?(checked.valid?'pass':'fail'):'pending'}">${checked?(checked.valid?'✓ Pass':'! Fail'):'Checking…'}</strong>`:''}</div><code>5′ ${overhangHtml(cassette.left_overhang)} · 3′ ${overhangHtml(cassette.right_overhang)}</code>${group?`<ol>${info.parts.map((part,index)=>{const check=checked?.fragment_checks?.[index];const errors=check?.errors||part.digest.errors||[];return `<li><span class="nested-card-status ${errors.length?'fail':check?'pass':'pending'}">${errors.length?'!':check?'✓':'·'}</span><span><b>${esc(part.name)}</b><small>${esc([plateLabel(part.plate_id),part.well].filter(Boolean).join(' / '))}</small>${errors.length?`<small class="nested-tooltip-error">${overhangMessage(errors.join(' '))}</small>`:''}</span></li>`;}).join('')}</ol>${checked?.errors.length?`<div class="nested-tooltip-error">${overhangMessage(checked.errors.join(' '))}</div>`:''}`:'<div class="muted">No nested fragments</div>'}</section>`;
  }).join('')}<small class="nested-tooltip-hint">Click to edit</small>`;
}
function showNestedCardTooltip(button){
  const parent=state.parts.find(p=>p.id===Number(button.dataset.nestedParent));if(!parent)return;
  nestedCardAnchor=button;const tooltip=$('nested-card-tooltip');tooltip.innerHTML=nestedCardDetails(parent);tooltip.classList.remove('hidden');
  const rect=button.closest('.fragment-tile').getBoundingClientRect(),box=tooltip.getBoundingClientRect();
  const beside=rect.right+box.width+12<=window.innerWidth-12?'right':rect.left-box.width-12>=12?'left':null;
  const left=beside==='right'?rect.right+12:beside==='left'?rect.left-box.width-12:rect.left;
  const top=beside?rect.top:rect.bottom+8+box.height<=window.innerHeight-12?rect.bottom+8:rect.top-box.height-8;
  tooltip.style.left=Math.max(12,Math.min(left,window.innerWidth-box.width-12))+'px';
  tooltip.style.top=Math.max(12,Math.min(top,window.innerHeight-box.height-12))+'px';
}
function updateNestedCardChecks(result=null){
  nestedCardCheckResult=result;
  $('selected-parts').querySelectorAll('[data-nested-parent]').forEach(button=>{
    const groups=selectedNested().filter(g=>g.parent_fragment_id===Number(button.dataset.nestedParent));
    const checks=groups.map(g=>result?.nested_assemblies?.find(c=>nestedGroupKey(c)===nestedGroupKey(g)));
    const kind=checks.some(c=>c&&!c.valid)?'fail':checks.length&&checks.every(Boolean)?'pass':'pending';
    const status=button.querySelector('[data-nested-card-status]');
    status.textContent=groups.length?(kind==='pass'?'✓':kind==='fail'?'!':'…'):'';status.className='nested-card-status '+kind;
    const parent=state.parts.find(p=>p.id===Number(button.dataset.nestedParent));
    const count=groups.reduce((n,g)=>n+g.fragment_ids.length,0);
    button.setAttribute('aria-label',`Nested assembly in ${parent.name}, ${count} fragments${groups.length?`, ${kind==='pass'?'Pass':kind==='fail'?'Fail':'Checking'}`:''}`);
  });
  if(nestedCardAnchor?.isConnected)showNestedCardTooltip(nestedCardAnchor);
}
function bindNestedCards(){
  $('selected-parts').querySelectorAll('[data-nested-parent]').forEach(button=>{
    button.onmouseenter=()=>showNestedCardTooltip(button);button.onmouseleave=hideNestedCardTooltip;
    button.onfocus=()=>showNestedCardTooltip(button);button.onblur=hideNestedCardTooltip;
    button.onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();hideNestedCardTooltip();}};
    button.onclick=event=>{event.stopPropagation();if(button.getAttribute('aria-expanded')==='true')closeNestedEditor();else openNested(Number(button.dataset.nestedParent));};
  });
}
window.addEventListener('scroll',hideNestedCardTooltip,{passive:true,capture:true});
window.addEventListener('resize',hideNestedCardTooltip,{passive:true});

function renderFragmentAssemblyActions(){
  const actions=document.createElement('div');
  actions.className='fragment-chain-actions';
  actions.setAttribute('role','group');
  actions.setAttribute('aria-label','Fragment assembly actions');
  const fresh=$('new-build').cloneNode(true);
  fresh.id='new-build-inline';fresh.type='button';fresh.onclick=newBuild;
  const add=document.createElement('button');
  add.id='add-build-inline';add.type='button';add.className='icon-button add-build';
  add.setAttribute('aria-label','Add current assembly as a new entry');add.title='Add current assembly as a new entry';
  add.innerHTML='<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';
  add.onclick=addCurrentBuild;actions.append(fresh,add);
  $('selected-parts').append(actions);
  updateBuildActions();
}

function renderParts() {
  hideNestedCardTooltip();closeFragmentSwap();
  state.nestedAssemblies=state.nestedAssemblies.filter(g=>state.parts.some(p=>p.id===g.parent_fragment_id));
  refreshRecommendedAssemblyName();
  $('part-count').textContent = `${state.parts.length} selected${selectedNested().length?' · '+selectedNested().reduce((sum,g)=>sum+g.fragment_ids.length,0)+' nested':''}`;
  updateBuildActions();
  const ends = backboneEnds();
  let previous = ends.left;
  $('selected-parts').innerHTML = state.parts.length ? state.parts.map((f,index) => {
    const linker = fragmentLinker(previous, f.digest.left_overhang);
    previous = f.digest.right_overhang;
    const variants = compatibleFragmentAlternatives(index).length;
    const variantLabel = `${variants} alternative${variants === 1 ? '' : 's'}`;
    const details = `${f.name} · ${plateLabel(f.plate_id)} / ${f.well} · ${fmt(f.physical_length,0)} bp`;
    return `<div class="fragment-step">${linker}<div class="fragment-parent-group"><div class="fragment-tile" draggable="true" data-order="${index}"><button class="fragment-check pending" data-fragment-check="${index}" type="button" aria-label="Checking ${esc(f.name)}" aria-describedby="fragment-check-tooltip">…</button>${reverseCompFlag(f)}<button class="fragment-open" data-swap-index="${index}" aria-label="Swap ${esc(f.name)}${variants ? ', ' + variantLabel : ''}" aria-haspopup="dialog" aria-expanded="false" aria-controls="fragment-swap" title="${esc(details)}"><span class="part-name">${esc(f.name)}</span><span class="fragment-footer"><span class="fragment-meta">${esc(f.well)} · ${fmt(f.physical_length,0)} bp</span>${variants ? `<span class="fragment-variants" title="${variantLabel}">${variants} variant${variants === 1 ? '' : 's'}</span>` : ''}</span></button>${nestedCardIndicator(f)}<button class="fragment-remove" data-remove="${index}" aria-label="Remove ${esc(f.name)}" title="Remove ${esc(f.name)}">${inventoryIcon('close')}</button></div></div>${index===state.parts.length-1?fragmentLinker(previous,ends.right):''}</div>`;
  }).join('') : '<div class="empty-state">No fragments</div>';
  renderFragmentAssemblyActions();
  bindNestedCards();
  renderNestedEditor();
  $('next-end').textContent = nextEnd() || '';
  $('next-end').classList.toggle('backbone-end', isBackboneLinker(nextEnd()));
  $('next-end').classList.toggle('palindromic-overhang',Overhangs.isPalindromic(nextEnd()));
  $('next-end').title=Overhangs.isPalindromic(nextEnd())?Overhangs.warning:'';
  updateChainTopology();
  updateFragmentChecks(state.assemblyResult);
  $('selected-parts').querySelectorAll('[data-swap-index]').forEach(button => button.onclick = event => {
    event.stopPropagation();
    openFragmentSwap(Number(button.dataset.swapIndex), button);
  });
  $('selected-parts').querySelectorAll('[data-remove]').forEach(button => button.onclick = event => {
    event.stopPropagation();
    const index = Number(button.dataset.remove);
    if(state.nestedParent===state.parts[index].id)state.nestedParent=null;
    state.parts.splice(index, 1);
    renderParts();
    invalidate();
  });
  let dragIndex = null;
  $('selected-parts').querySelectorAll('[data-order]').forEach(tile => {
    tile.ondragstart = event => {
      closeFragmentSwap();
      dragIndex = Number(tile.dataset.order);
      event.dataTransfer.setData('text/plain', String(dragIndex));
      event.dataTransfer.effectAllowed = 'move';
      tile.classList.add('dragging');
    };
    tile.ondragend = () => { tile.classList.remove('dragging'); fragmentDragEnded = performance.now(); };
    tile.ondragover = event => event.preventDefault();
    tile.ondrop = event => {
      event.preventDefault();
      event.stopPropagation();
      if (dragIndex === null) return;
      const [fragment] = state.parts.splice(dragIndex, 1);
      state.parts.splice(Number(tile.dataset.order), 0, fragment);
      renderParts();
      invalidate();
    };
  });
}
function updateBuildListOutcome(){
  const badge=$('assembly-status');const items=state.buildList;
  if(!items.length){badge.className='assembly-outcome neutral hidden';badge.innerHTML='';badge.removeAttribute('title');badge.setAttribute('aria-busy','false');return;}
  const pending=!!pendingBuildSave||savingBuildId!==null;
  const failed=items.filter(item=>!item.plan||item.plan.errors?.length);
  const kind=pending?'pending':failed.length?'fail':'pass';
  const text=pending?'Checking…':failed.length?'Fail':'Pass';
  badge.className='assembly-outcome '+kind;badge.innerHTML=`<small>Build list QC</small>`+(pending?'':validationGlyph(kind))+`<span>${text}</span>`;
  badge.setAttribute('aria-busy',String(pending));
  badge.title=pending?'Checking queued assembly updates':failed.length?`${failed.length} of ${items.length} queued assemblies failed: ${failed.map(item=>item.request.name).join(', ')}`:`${items.length} queued assembl${items.length===1?'y passes':'ies pass'} sequence checks`;
}

function clearAssemblyFeedback(){
  $('assembly-feedback').classList.add('hidden');$('assembly-stats').innerHTML='';$('assembly-messages').innerHTML='';$('junctions').innerHTML='';
  updateBuildListOutcome();
  for(const id of ['download-gb','save-assembly','save-backbone'])$(id).disabled=true;
}
function invalidate(){
  window.JunctionSandbox?.schedule();
  hideMapTooltip();
  scheduleBuildSettingsSave();
  renderBuildList();closeFragmentSwap();hideNestedCardTooltip();hideFragmentCheckTooltip();searchCounter++;checkCounter++;resuspCounter++;
  $('search-results').classList.add('hidden');$('fragment-search').setAttribute('aria-expanded','false');
  state.result=null;state.assemblyResult=null;$('reaction-status').classList.add('hidden');$('results').classList.add('hidden');$('reaction-results').innerHTML='';$('reaction-empty').classList.remove('hidden');
  clearAssemblyFeedback();updateFragmentChecks();clearTimeout(assemblyCheckTimer);
  if(state.parts.length||$('backbone').value)assemblyCheckTimer=setTimeout(checkAssembly,220);
}

async function searchFragments(){
  const request=++searchCounter;
  const query=$('fragment-search').value;
  const recipes=matchingPlasmidRecipes(query);
  const needsCassette=$('backbone').value.startsWith('p:')&&!$('slot').value;
  const preferred=$('compatible-only').checked?nextEnd():'';
  let url='/api/fragments?enzyme='+encodeURIComponent($('enzyme').value)+'&limit=30&q='+encodeURIComponent(query);
  if(preferred)url+='&left='+encodeURIComponent(preferred);
  try{
    let results=needsCassette?[]:await api(url);
    if(request!==searchCounter)return;
    results=results.filter(f=>!state.parts.some(p=>p.id===f.id));
    const plasmidOptions=recipes.map(({recipe:r,index})=>{
      const ids=r.no_backbone_fragment_ids||[r.starter_fragment_id,...r.fragment_ids].filter(Boolean);
      const detail=r.available?`${r.enzyme} · ${ids.length} fragments`:'Missing fragments';
      const title=r.available?'Load plasmid assembly':'Missing from the plate maps: '+r.missing.join(', ');
      return `<button class="search-option plasmid-search-option" role="option" data-recipe="${index}" ${r.available?'':'disabled aria-disabled="true"'} title="${esc(title)}"><div><div class="part-name">${esc(r.name.replace(' · ',' '))}</div><div class="part-location">${esc(detail)}</div></div><span class="badge neutral search-plasmid-label">Plasmid</span></button>`;
    }).join('');
    const fragmentOptions=results.map(f=>`<button class="search-option" role="option" data-add="${f.id}"><div><div class="part-name">${esc(f.name)}${reverseCompFlag(f,true)}${FragmentSearch.badge(f)}</div><div class="part-location">${esc(FragmentSearch.location(f,plateLabel))} · ${fmt(f.physical_length,0)} bp ${f.digest.errors?.length?'· check required':''}</div></div><div class="part-ends">${fusionEnds(f.digest.left_overhang,f.digest.right_overhang)}<span>＋</span></div></button>`).join('');
    $('search-results').innerHTML=plasmidOptions+fragmentOptions+(needsCassette?'<div class="search-note">Choose cassette for fragments</div>':!results.length&&!recipes.length?'<div class="search-note">No matches</div>':'');
    $('search-results').classList.remove('hidden');$('fragment-search').setAttribute('aria-expanded','true');
    $('search-results').querySelectorAll('[data-recipe]').forEach(b=>b.onclick=()=>loadRecipe(Number(b.dataset.recipe)));
    $('search-results').querySelectorAll('[data-add]').forEach(b=>b.onclick=()=>{
      const f=results.find(f=>f.id===Number(b.dataset.add));state.parts.push(f);renderParts();invalidate();
      $('fragment-search').value='';closeAssemblySearch();$('fragment-search').focus();searchFragments();
    });
  }catch(e){if(request===searchCounter)toast(e.message);}
}
async function checkAssembly(){
  if(plasmidViewerSession){plasmidViewerSession.recheck=true;return;}
  clearTimeout(assemblyCheckTimer);const request=++checkCounter;
  if(!state.parts.length&&!$('backbone').value){clearAssemblyFeedback();return;}

  try{
    const result=await api('/api/assemblies/preview',jsonBody(payload()));
    if(request!==checkCounter)return;
    result.name=$('assembly-name').value||result.name;
    state.result=result;state.assemblyResult=result;applyFragmentOrientations(result);renderParts();state.selectedFeature=null;state.mapMode=result.circular?'circular':'linear';renderResult();
  }catch(error){if(request!==checkCounter)return;assemblyCheckFailed(error.message);}
}
function assemblyCheckFailed(message){
  $('assembly-feedback').classList.remove('hidden');$('assembly-stats').innerHTML='';$('junctions').innerHTML='';$('junction-details').classList.add('hidden');$('assembly-messages').innerHTML=messages([message]);updateFragmentChecks(null,message);
}

function messages(errors=[],warnings=[]){return errors.map(x=>`<div class="notice error">${overhangMessage(x)}</div>`).join('')+warnings.map(x=>`<div class="notice warn">${overhangMessage(x)}</div>`).join('');}
function renderAssemblyFeedback(r){
  const junctions=[...(r.junctions||[]),...(r.nested_assemblies||[]).flatMap(group=>group.junctions||[])];
  const valid=r.valid!==false&&!r.errors?.length;$('assembly-feedback').classList.remove('hidden');
  const counts={};for(const site of r.restriction_sites||[])counts[site.enzyme]=(counts[site.enzyme]||0)+1;
  $('assembly-stats').innerHTML=`<div><strong>${fmt(r.length||r.sequence.length,0)}</strong><small>bp</small></div><div><strong>${fmt(r.gc,1)}%</strong><small>GC</small></div><div><strong>${junctions.length}</strong><small>junctions</small></div><div><strong>${counts.BsmBI||0}</strong><small>BsmBI sites retained</small></div>`;
  $('assembly-messages').innerHTML=(r.errors?.length?`<details class="assembly-details" open><summary>Errors (${r.errors.length})</summary>${messages(r.errors,[])}</details>`:'')+(r.warnings?.length?`<details class="assembly-details"><summary>Warnings (${r.warnings.length})</summary>${messages([],r.warnings)}</details>`:'');
  $('junction-details').classList.toggle('hidden',!junctions.length);
  $('junctions').innerHTML=junctions.map(j=>`<div class="junction"><span>${esc(j.from||'Junction')}</span><b>${overhangHtml(j.overhang||j.left_overhang)} ${j.compatible===false?'!':'✓'}</b><span>${esc(j.to||'')}</span>${j.compatible===false?`<small>Expected ${overhangHtml(j.right_overhang)}</small>`:''}</div>`).join('');
  updateFragmentChecks(r);
  $('download-gb').disabled=!valid;$('save-assembly').disabled=!valid;$('save-backbone').disabled=!valid||!r.backbone_template?.eligible;$('save-backbone').title=r.backbone_template?.eligible?'Save backbone · '+r.backbone_template.enzymes.join(' / '):'Requires a circular assembly with a usable Golden Gate cassette';
}
function renderResult(){
  const r=state.result;$('viewer-name').readOnly=!!r.viewerReadOnly||!!r.viewerPlasmidId&&!!window.JunctionAccount&&!window.JunctionAccount.allowed('can_edit');if(document.activeElement!==$('viewer-name'))$('viewer-name').value=r.name||'';$('viewer-name-status').textContent='';$('viewer-name').title=r.viewerReadOnly?'Read-only Design preview':'Click to rename';
  $('viewer-download-gb').classList.toggle('hidden',!!r.storedReference&&!r.viewerPlasmidId);
  $('viewer-download-gb').disabled=!r.sequence||!!r.errors?.length;
  if(!r.storedReference){state.assemblyResult=r;updateChainTopology(r);renderAssemblyFeedback(r);renderReaction(r.reaction);renderNestedStatus();renderNestedReactions();}
  $('viewer-title').textContent=r.viewerTitle||(r.circular?'Plasmid':'Linear assembly');$('view-circular').disabled=r.circular===false;$('results').classList.remove('hidden');renderMap();renderViewerAnnotations();renderSequence();if(state.subtab==='reaction'&&!r.storedReference)loadResuspension();
  const counts={};for(const site of r.restriction_sites||[])counts[site.enzyme]=(counts[site.enzyme]||0)+1;$('site-list').textContent='Recognition sites: '+Object.entries(counts).map(([key,value])=>key+' '+value).join(' · ');
}

function reactionIsReady(r){return !!r?.rows?.length&&r.rows.every(p=>p.feasible===true&&p.volume_ul!==null)&&r.water_ul!==null&&r.water_ul>=0;}
function renderReaction(r){const ready=(state.assemblyResult?.nested_reactions||[]).every(s=>!s.errors.length&&reactionIsReady(s.reaction))&&r.rows?.length&&r.rows.every(x=>x.feasible===true&&x.volume_ul!==null&&(x.role==='backbone'||(x.volume_ul>=(state.result?.effective_settings?.min_input_volume_ul||settings().min_input_volume_ul)-1e-9&&x.volume_ul<=(state.result?.effective_settings?.max_input_volume_ul||settings().max_input_volume_ul)+1e-9)))&&r.water_ul!==null&&r.water_ul>=0;$('reaction-status').className='badge '+(ready?'':'error');$('reaction-status').textContent=ready?'READY':'CHECK REQUIRED';$('reaction-empty').classList.add('hidden');$('reaction-results').innerHTML=(r.rows||[]).map(x=>`<div class="reaction-line"><span>${esc(x.name)}<small>${esc(x.well||(String(x.id).startsWith('prepared:')?'Prepared parent':x.role==='backbone'?'Backbone':''))} · ${x.feasibility==='default_volume'?'Target: ':''}${fmt(x.target_ng)} ng · ${fmt(x.target_fmol)} fmol</small><small>${x.concentration_ng_ul?inventoryQuantity(x.concentration_ng_ul)+' ng/µL · ':''}${x.feasibility==='default_volume'?'Default 1 µL':x.role==='backbone'||String(x.id).startsWith('prepared:')?'Manual':x.concentration_basis?.includes('Instance')?'Instance':x.concentration_basis?.match(/ASSUMED|PROPOSED|planned/i)?'Planned':'Saved'}</small>${x.warnings?.filter(w=>!w.match(/planning assumption/i)).length?`<small class="reaction-warning">${esc(x.warnings.filter(w=>!w.match(/planning assumption/i)).join(' '))}</small>`:''}</span><strong>${inventoryQuantity(x.volume_ul)} µL</strong></div>`).join('')+`<div class="reaction-line"><span>Master mix + reagents</span><strong>${fmt(r.master_mix_ul)} µL</strong></div><div class="reaction-line"><span>Water</span><strong>${fmt(r.water_ul)} µL</strong></div>`+(r.warnings||[]).map(w=>`<div class="reaction-warning">${esc(w)}</div>`).join('');}
const colors=Array.from({length:8},(_,i)=>`var(--feature-${i})`);
function mapFeatures(result=state.result){return(result?.features||[]).filter(f=>f.type!=='source'&&PlasmidFeatures.segments(f,result.sequence.length).length&&(result.storedReference||f.end-f.start>12));}
let mapTooltipFeature=null,mapResizeFrame=null,mapRenderedWidth=0;
function hideMapTooltip(){
  mapTooltipFeature=null;$('map-tooltip').classList.add('hidden');
  $('plasmid-map').querySelectorAll('.is-hovered').forEach(node=>node.classList.remove('is-hovered'));
}
function positionMapTooltip(event,node){
  const tooltip=$('map-tooltip'),rect=node.getBoundingClientRect();
  const x=Number.isFinite(event?.clientX)?event.clientX:rect.left+rect.width/2;
  const y=Number.isFinite(event?.clientY)?event.clientY:rect.top;
  const box=tooltip.getBoundingClientRect();
  tooltip.style.left=Math.max(10,Math.min(x+14,window.innerWidth-box.width-10))+'px';
  tooltip.style.top=Math.max(10,Math.min(y+18+box.height<window.innerHeight-10?y+18:y-box.height-12,window.innerHeight-box.height-10))+'px';
}
function featureSummary(feature,result=state.result){
  const length=result.sequence.length,parts=PlasmidFeatures.segments(feature,length),strand=feature.strand===-1?'Reverse':feature.strand===1?'Forward':'Mixed / unstranded';
  return [feature.type||'Feature',PlasmidFeatures.location(feature,length)||'No local coordinates',parts.length?fmt(PlasmidFeatures.size(feature,length),0)+' bp':'Remote location',strand].join(' · ');
}
function showMapTooltip(event,node,feature,index,features){
  const tooltip=$('map-tooltip');
  if(mapTooltipFeature!==feature){
    $('plasmid-map').querySelectorAll('.is-hovered').forEach(el=>el.classList.remove('is-hovered'));
    if(index>=0)$('plasmid-map').querySelectorAll(`[data-feature="${index}"],[data-map-leader="${index}"]`).forEach(el=>el.classList.add('is-hovered'));
    const parent=feature.parent_fragment_id?features.find(f=>f.fragment_id===feature.parent_fragment_id&&f.source==='fragment'):null;
    tooltip.innerHTML=`<strong>${esc(PlasmidFeatures.name(feature))}</strong><small>${esc(featureSummary(feature))}</small>${parent?`<small>Nested in ${esc(parent.label)}</small>`:''}${PlasmidFeatures.qualifiers(feature,true).slice(0,6).map(([key,value])=>`<small><b>${esc(key)}</b>: ${esc(value)}</small>`).join('')}`;
    mapTooltipFeature=feature;
  }
  tooltip.classList.remove('hidden');positionMapTooltip(event,node);
}
function selectMapFeature(feature){
  state.selectedFeature=feature;
  $('feature-detail').classList.remove('hidden');
  $('feature-detail').textContent=[PlasmidFeatures.name(feature),featureSummary(feature),...PlasmidFeatures.qualifiers(feature).map(([key,value])=>key+': '+value)].join('\n');
  const first=PlasmidFeatures.segments(feature,state.result.sequence.length)[0];
  if(first)$('sequence-start').value=first.start+1;
  renderSequence();
}
function renderViewerAnnotations(){
  const features=state.result?.features||[],mapped=mapFeatures(),length=state.result?.sequence.length||0;
  $('viewer-annotations').classList.toggle('hidden',!features.length);
  $('viewer-annotation-count').textContent=`Annotations (${features.length})`;
  $('viewer-annotation-rows').innerHTML=features.map((f,i)=>`<tr><td><button class="text-button" data-viewer-annotation="${i}" aria-describedby="map-tooltip">${esc(PlasmidFeatures.name(f))}</button></td><td>${esc(f.type||'Feature')}</td><td>${esc(PlasmidFeatures.location(f,length)||'No local coordinates')}</td></tr>`).join('');
  $('viewer-annotation-rows').querySelectorAll('[data-viewer-annotation]').forEach(button=>{
    const feature=features[Number(button.dataset.viewerAnnotation)],index=mapped.indexOf(feature);
    button.onclick=()=>selectMapFeature(feature);
    button.onpointerenter=event=>showMapTooltip(event,button,feature,index,mapped);button.onpointermove=event=>showMapTooltip(event,button,feature,index,mapped);button.onpointerleave=hideMapTooltip;
    button.onfocus=()=>showMapTooltip(null,button,feature,index,mapped);button.onblur=hideMapTooltip;
  });
}
function mapTextTools(map=$('plasmid-map')){
  const context=document.createElement('canvas').getContext('2d');
  const family=getComputedStyle(map).fontFamily;
  const measure=(text,size=11)=>{if(!context)return [...text].length*size*.7;context.font=`600 ${size}px ${family}`;return context.measureText(text).width;};
  const fit=(value,limit,width,size=11)=>{
    const full=String(value||'Feature');let chars=[...full].slice(0,limit),cut=[...full].length>limit;
    let text=chars.join('')+(cut?'…':'');
    while(chars.length&&measure(text,size)>width){chars.pop();cut=true;text=chars.join('')+'…';}
    return{text,width:measure(text,size)};
  };
  return{measure,fit};
}
function mapFeatureGroup(index,feature,content,kind='geometry',length=state.result.sequence.length,tooltipId='map-tooltip'){
  return `<g class="map-feature map-${kind}" data-feature="${index}" role="button" tabindex="${kind==='geometry'?0:-1}" aria-label="${esc(PlasmidFeatures.name(feature))} · ${esc(PlasmidFeatures.location(feature,length))}" aria-describedby="${tooltipId}">${content}</g>`;
}
const mapSiteColors={BsaI:'var(--site-bsai)',BsmBI:'var(--site-bsmbi)',BbsI:'var(--site-bbsi)',HindIII:'var(--site-hindiii)'};
function mapSites(){
  const mode=$('map-site-filter').value;
  return(state.result?.restriction_sites||[]).map((site,index)=>({...site,index,type:'restriction_site',label:site.enzyme}))
    .filter(site=>mode==='all'||(mode==='BsmBI + BsaI'?['BsmBI','BsaI'].includes(site.enzyme):site.enzyme===mode));
}
function mapSiteRange(site,length=state.result.sequence.length){
  return `${site.start+1}–${site.wraps_origin?site.end%length:site.end}${site.wraps_origin?' · across origin':''}`;
}
function mapSiteGroup(site,content,kind='geometry',length=state.result.sequence.length,tooltipId='map-tooltip'){
  return `<g class="map-site map-site-${kind}" data-site="${site.index}" role="button" tabindex="${kind==='geometry'?0:-1}" style="--site-color:${mapSiteColors[site.enzyme]||'var(--muted)'}" aria-label="${esc(site.enzyme)} site · ${esc(mapSiteRange(site,length))}" aria-describedby="${tooltipId}">${content}</g>`;
}
function mapSiteLeader(site,path){return `<path class="map-leader map-site-leader" data-site-leader="${site.index}" style="stroke:${mapSiteColors[site.enzyme]||'var(--muted)'}" d="${path}"/>`;}
function renderMapSiteLegend(sites){
  const counts={};for(const site of sites)counts[site.enzyme]=(counts[site.enzyme]||0)+1;
  $('map-site-legend').innerHTML=Object.entries(counts).map(([enzyme,count])=>`<span class="map-site-key" style="--site-color:${mapSiteColors[enzyme]||'var(--muted)'}"><i aria-hidden="true"></i>${esc(enzyme)} · ${count} site${count===1?'':'s'}</span>`).join('')||`<span class="muted">${$('map-site-filter').value==='none'?'Sites hidden':'No sites detected'}</span>`;
}
function showMapSiteTooltip(event,node,site){
  const key='site-'+site.index,tooltip=$('map-tooltip');
  if(mapTooltipFeature!==key){
    $('plasmid-map').querySelectorAll('.is-hovered').forEach(el=>el.classList.remove('is-hovered'));
    $('plasmid-map').querySelectorAll(`[data-site="${site.index}"],[data-site-leader="${site.index}"]`).forEach(el=>el.classList.add('is-hovered'));
    const count=(state.result.restriction_sites||[]).filter(s=>s.enzyme===site.enzyme).length;
    tooltip.innerHTML=`<strong>${esc(site.enzyme)} · ${esc(mapSiteRange(site))}</strong><small>Recognition: ${esc(site.motif)} · ${site.strand===-1?'Reverse':'Forward'} strand</small><small>${count===1?'Single cutter':count+' sites in plasmid'}</small><small>Click to highlight sequence</small>`;
    mapTooltipFeature=key;
  }
  tooltip.classList.remove('hidden');positionMapTooltip(event,node);
}
function selectMapSite(site){
  state.selectedFeature=site;$('feature-detail').classList.remove('hidden');
  $('feature-detail').textContent=`${site.enzyme} · ${mapSiteRange(site)} · ${site.motif} · ${site.strand===-1?'Reverse':'Forward'} strand`;
  $('sequence-start').value=site.start+1;renderSequence();
}
function linearMapSvg(result,features,width,textTools,sites,tooltipId='map-tooltip'){
  const featureGroup=(i,f,content,kind)=>mapFeatureGroup(i,f,content,kind,result.sequence.length,tooltipId);
  const siteGroup=(site,content,kind)=>mapSiteGroup(site,content,kind,result.sequence.length,tooltipId);
  const startX=30,endX=width-30,length=result.sequence.length,lanes=PlasmidFeatures.lanes(features,length);
  const labels=features.map((feature,index)=>{
    const anchor=startX+(endX-startX)*PlasmidFeatures.anchor(feature,length)/length;
    const fitted=textTools.fit(PlasmidFeatures.name(feature),18,Math.min(190,width-80));
    return{index,feature,anchor,position:anchor,lane:lanes.indices[index],size:fitted.width+10,text:fitted.text};
  });
  const siteLabels=sites.map(site=>{
    const anchor=startX+(endX-startX)*site.start/length,text=site.enzyme+' · '+(site.start+1);
    return{site,anchor,position:anchor,size:textTools.measure(text)+12,text};
  });
  const top=MapLabelLayout.rows([...labels.filter(item=>item.index%2===0),...siteLabels],24,width-24);
  const bottom=MapLabelLayout.rows(labels.filter(item=>item.index%2===1),24,width-24);
  const topY=40+Math.max(1,top.count)*26;
  const axisY=topY+35+lanes.count*21,bottomY=axisY+10;
  const height=bottomY+30+Math.max(1,bottom.count)*26+52;
  let geometry=`<line x1="${startX}" x2="${endX}" y1="${axisY}" y2="${axisY}" stroke="var(--map-track)" stroke-width="4"/>`;
  const leaders=[],texts=[];
  for(const item of labels){
    const y=topY+12+item.lane*21,color=PlasmidFeatures.color(item.feature,colors[item.index%colors.length]);
    const shapes=PlasmidFeatures.segments(item.feature,length).map(part=>{
      const x=startX+(endX-startX)*part.start/length,w=Math.max(3,(endX-startX)*(part.end-part.start)/length),tip=Math.min(6,w/2);
      const path=part.strand===-1?`M${x+tip},${y}H${x+w}V${y+16}H${x+tip}L${x},${y+8}Z`:part.strand===1?`M${x},${y}H${x+w-tip}L${x+w},${y+8}L${x+w-tip},${y+16}H${x}Z`:null;
      return path?`<path d="${path}" fill="${color}"/>`:`<rect x="${x}" y="${y}" width="${w}" height="16" rx="2" fill="${color}"/>`;
    }).join('');
    geometry+=featureGroup(item.index,item.feature,shapes);
  }
  for(const item of siteLabels){
    geometry+=siteGroup(item.site,`<rect class="map-site-hit" x="${item.anchor-6}" y="${axisY-12}" width="12" height="24"/><path class="map-site-tick" d="M${item.anchor},${axisY-10}v20"/><circle class="map-site-dot" cx="${item.anchor}" cy="${axisY}" r="3"/>`);
  }
  for(const [side,layout] of [[-1,top],[1,bottom]])for(const item of layout.labels){
    const y=side===-1?topY-18-item.row*26:bottomY+48+item.row*26;
    const anchorY=item.site?axisY-10:topY+12+item.lane*21+(side===-1?0:16);
    const endY=y+(side===-1?9:-9),path=`M${item.anchor},${anchorY} L${item.anchor},${anchorY+side*7} L${item.position},${endY}`;
    const content=`<rect class="map-label-background" x="${item.position-item.size/2}" y="${y-9}" width="${item.size}" height="18" rx="3"/><text class="map-label${item.site?' map-site-label':''}" data-map-label="${item.site?'site-'+item.site.index:item.index}" x="${item.position}" y="${y}" text-anchor="middle" dominant-baseline="middle">${esc(item.text)}</text>`;
    leaders.push(item.site?mapSiteLeader(item.site,path):`<path class="map-leader" data-map-leader="${item.index}" d="${path}"/>`);
    texts.push(item.site?siteGroup(item.site,content,'annotation'):featureGroup(item.index,item.feature,content,'annotation'));
  }
  return `<svg class="plasmid-svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" aria-label="Linear plasmid map">${geometry}<g class="map-leaders">${leaders.join('')}</g>${texts.join('')}<text x="${startX}" y="${height-18}" font-size="11" fill="var(--muted)">1</text><text x="${endX}" y="${height-18}" text-anchor="end" font-size="11" fill="var(--muted)">${length.toLocaleString()} bp</text></svg>`;
}
function circularMapSvg(result,features,width,textTools,sites,tooltipId='map-tooltip'){
  const featureGroup=(i,f,content,kind)=>mapFeatureGroup(i,f,content,kind,result.sequence.length,tooltipId);
  const siteGroup=(site,content,kind)=>mapSiteGroup(site,content,kind,result.sequence.length,tooltipId);
  const radius=Math.min(165,width*.2),cx=width/2,lanes=PlasmidFeatures.lanes(features,result.sequence.length);
  const gap=Math.min(3,(radius-45)/(lanes.count*3)),band=Math.min(24,(radius-45)/lanes.count-gap);
  const labels=features.map((feature,index)=>{
    const mid=PlasmidFeatures.anchor(feature,result.sequence.length)/result.sequence.length*2*Math.PI-Math.PI/2,radiusAt=radius-lanes.indices[index]*(band+gap);
    return{index,feature,mid,radiusAt,side:Math.cos(mid)<0?-1:1,position:Math.sin(mid)*(radius+30),size:14};
  });
  const siteLabels=sites.map(site=>{
    const mid=site.start/result.sequence.length*2*Math.PI-Math.PI/2;
    return{site,mid,side:Math.cos(mid)<0?-1:1,position:Math.sin(mid)*(radius+30),size:14};
  });
  const allLabels=[...labels,...siteLabels];
  const left=allLabels.filter(item=>item.side===-1),right=allLabels.filter(item=>item.side===1);
  const height=Math.max(390,Math.max(left.length,right.length)*22+48),cy=height/2;
  const labelX=cx-radius-50,available=labelX-24;
  const name=textTools.fit(result.name||'Assembly',30,radius*2-44,16).text;
  let geometry=`<circle cx="${cx}" cy="${cy}" r="${radius}" fill="none" stroke="var(--map-track)" stroke-width="24"/><text class="map-center-name" x="${cx}" y="${cy-5}" text-anchor="middle" font-size="16" fill="var(--ink)"><title>${esc(result.name||'Assembly')}</title>${esc(name)}</text><text x="${cx}" y="${cy+20}" text-anchor="middle" font-size="12" fill="var(--muted)">${result.sequence.length.toLocaleString()} bp · ${result.circular?'circular':'linear'}</text>`;
  for(const item of labels){
    const radiusAt=item.radiusAt,color=PlasmidFeatures.color(item.feature,colors[item.index%colors.length]);
    const shapes=PlasmidFeatures.segments(item.feature,result.sequence.length).map(part=>{
      const start=part.start/result.sequence.length*2*Math.PI-Math.PI/2,end=Math.min(part.end/result.sequence.length*2*Math.PI-Math.PI/2,start+2*Math.PI-.008);
      const x1=cx+radiusAt*Math.cos(start),y1=cy+radiusAt*Math.sin(start),x2=cx+radiusAt*Math.cos(end),y2=cy+radiusAt*Math.sin(end);
      const mark=part.strand?(part.strand===-1?start:end):null,head=mark===null?'':`<path d="M${cx+(radiusAt-band*.38)*Math.cos(mark)},${cy+(radiusAt-band*.38)*Math.sin(mark)} L${cx+(radiusAt+band*.38)*Math.cos(mark)},${cy+(radiusAt+band*.38)*Math.sin(mark)}" stroke="var(--paper)" stroke-width="1.5"/>`;
      return `<path d="M${x1},${y1} A${radiusAt},${radiusAt} 0 ${end-start>Math.PI?1:0} 1 ${x2},${y2}" stroke="${color}" stroke-width="${band}" fill="none"/>${head}`;
    }).join('');
    geometry+=featureGroup(item.index,item.feature,shapes);
  }
  for(const item of siteLabels){
    const x1=cx+(radius-17)*Math.cos(item.mid),y1=cy+(radius-17)*Math.sin(item.mid),x2=cx+(radius+19)*Math.cos(item.mid),y2=cy+(radius+19)*Math.sin(item.mid);
    geometry+=siteGroup(item.site,`<path class="map-site-hit" d="M${x1},${y1} L${x2},${y2}"/><path class="map-site-tick" d="M${x1},${y1} L${x2},${y2}"/><circle class="map-site-dot" cx="${x2}" cy="${y2}" r="3"/>`);
  }
  const leaders=[],texts=[];
  for(const side of [-1,1]){
    const group=allLabels.filter(item=>item.side===side).map(item=>({...item,position:item.position+cy}));
    for(const item of MapLabelLayout.spread(group,24,height-24,8)){
      const x=side===-1?labelX:width-labelX,y=item.position;
      const leaderRadius=item.site?radius+19:item.radiusAt+band/2;
      const anchorX=cx+leaderRadius*Math.cos(item.mid),anchorY=cy+leaderRadius*Math.sin(item.mid);
      const elbowX=cx+side*(radius+27),endX=x-side*7;
      const label=item.site?item.site.enzyme+' · '+(item.site.start+1):PlasmidFeatures.name(item.feature);
      const fitted=textTools.fit(label,item.site?30:23,available-8);
      leaders.push(item.site?mapSiteLeader(item.site,`M${anchorX},${anchorY} L${elbowX},${anchorY} L${endX},${y}`):`<path class="map-leader" data-map-leader="${item.index}" d="M${anchorX},${anchorY} L${elbowX},${anchorY} L${endX},${y}"/>`);
      const content=`<rect class="map-label-background" x="${side===-1?x-fitted.width-4:x-4}" y="${y-9}" width="${fitted.width+8}" height="18" rx="3"/><text class="map-label${item.site?' map-site-label':''}" data-map-label="${item.site?'site-'+item.site.index:item.index}" x="${x}" y="${y}" dominant-baseline="middle" text-anchor="${side===-1?'end':'start'}">${esc(fitted.text)}</text>`;
      texts.push(item.site?siteGroup(item.site,content,'annotation'):featureGroup(item.index,item.feature,content,'annotation'));
    }
  }
  return `<svg class="plasmid-svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" aria-label="Circular plasmid map">${geometry}<g class="map-leaders">${leaders.join('')}</g>${texts.join('')}</svg>`;
}

function renderMap(){
  const result=state.result,map=$('plasmid-map');
  hideMapTooltip();
  if(!result?.sequence?.length){map.replaceChildren();$('map-site-legend').replaceChildren();return;}
  const features=mapFeatures(),sites=mapSites();renderMapSiteLegend(sites);
  if(!(result.features||[]).includes(state.selectedFeature)&&!(state.selectedFeature?.type==='restriction_site'&&sites.some(s=>s.index===state.selectedFeature.index&&s.start===state.selectedFeature.start&&s.enzyme===state.selectedFeature.enzyme))){state.selectedFeature=null;$('feature-detail').classList.add('hidden');}
  mapRenderedWidth=map.clientWidth;
  const width=Math.max(620,mapRenderedWidth||780),textTools=mapTextTools();
  const linear=state.mapMode==='linear'||result.circular===false;
  map.innerHTML=linear?linearMapSvg(result,features,width,textTools,sites):circularMapSvg(result,features,width,textTools,sites);
  $('view-circular').classList.toggle('active',!linear);
  $('view-linear').classList.toggle('active',linear);
  map.querySelectorAll('[data-feature]').forEach(node=>{
    const index=Number(node.dataset.feature),feature=features[index];
    node.onpointerenter=event=>showMapTooltip(event,node,feature,index,features);
    node.onpointermove=event=>showMapTooltip(event,node,feature,index,features);
    node.onpointerleave=()=>{if(document.activeElement!==node)hideMapTooltip();};
    node.onfocus=()=>showMapTooltip(null,node,feature,index,features);
    node.onblur=hideMapTooltip;
    node.onclick=()=>selectMapFeature(feature);
    node.onkeydown=event=>{if(event.key==='Escape'){hideMapTooltip();node.blur();}if(event.key==='Enter'||event.key===' '){event.preventDefault();selectMapFeature(feature);}};
  });
  map.querySelectorAll('[data-site]').forEach(node=>{
    const site=sites.find(s=>s.index===Number(node.dataset.site));
    node.onpointerenter=event=>showMapSiteTooltip(event,node,site);node.onpointermove=event=>showMapSiteTooltip(event,node,site);
    node.onpointerleave=()=>{if(document.activeElement!==node)hideMapTooltip();};node.onfocus=()=>showMapSiteTooltip(null,node,site);node.onblur=hideMapTooltip;
    node.onclick=event=>{selectMapSite(site);showMapSiteTooltip(event,node,site);};node.onkeydown=event=>{if(event.key==='Escape'){hideMapTooltip();node.blur();}if(event.key==='Enter'||event.key===' '){event.preventDefault();selectMapSite(site);showMapSiteTooltip(null,node,site);}};
  });
}
window.addEventListener('scroll',hideMapTooltip,{passive:true,capture:true});
window.addEventListener('resize',hideMapTooltip,{passive:true});
new ResizeObserver(()=>{
  if(!$('plasmid-map').clientWidth||Math.abs($('plasmid-map').clientWidth-mapRenderedWidth)<1)return;
  cancelAnimationFrame(mapResizeFrame);mapResizeFrame=requestAnimationFrame(renderMap);
}).observe($('plasmid-map'));

function renderSequence(){const r=state.result;if(!r)return;const start=Math.max(0,Math.min(r.sequence.length-1,Number($('sequence-start').value)-1||0));$('sequence-start').value=start+1;const end=Math.min(r.sequence.length,start+240),palindromes=new Set();for(const feature of r.features||[]){if((feature.source!=='fusion'&&!/^[ACGT]{4}\s+fusion\b/i.test(feature.label||''))||feature.end-feature.start!==4)continue;const label=(r.sequence+(r.circular?r.sequence.slice(0,3):'')).slice(feature.start,feature.end);if(Overhangs.isPalindromic(label))for(let i=feature.start;i<feature.end;i++)palindromes.add(i%r.sequence.length);}let html='';for(let pos=start;pos<end;pos+=60){html+=String(pos+1).padStart(7)+'  ';for(let j=pos;j<Math.min(end,pos+60);j++){const selected=state.selectedFeature&&PlasmidFeatures.contains(state.selectedFeature,j,r.sequence.length);const pal=palindromes.has(j);html+=(pal?`<mark class="palindromic-overhang${selected?' sequence-selected':''}" title="${Overhangs.warning}">`:selected?'<mark>':'')+r.sequence[j]+(pal||selected?'</mark>':'');if((j-pos+1)%10===0)html+=' ';}html+='\n';}$('sequence-view').innerHTML=html;}
function plasmidDraft(plasmid){return state.plasmidDrafts.get(plasmid.id)||{name:plasmid.name,circular:plasmid.circular,backbone_template:!!plasmid.recipe?.backbone_template};}
function plasmidDirty(plasmid,draft=plasmidDraft(plasmid)){return draft.name.trim()!==plasmid.name||draft.circular!==plasmid.circular||draft.backbone_template!==!!plasmid.recipe?.backbone_template;}
function changePlasmidDraft(plasmid,changes){
  state.plasmidDrafts.set(plasmid.id,{...plasmidDraft(plasmid),...changes});
  if(!plasmidDirty(plasmid))state.plasmidDrafts.delete(plasmid.id);
  document.querySelectorAll(`[data-plasmid="${plasmid.id}"]`).forEach(card=>syncPlasmidCard(card,plasmid));
}
function syncPlasmidCard(card,plasmid){
  const draft=plasmidDraft(plasmid),saving=state.plasmidSaving.has(plasmid.id),dirty=plasmidDirty(plasmid,draft);
  const name=card.querySelector('[data-plasmid-name]');if(document.activeElement!==name)name.value=draft.name;
  name.disabled=saving;
  const topology=card.querySelector('[data-topology]');
  topology.innerHTML=inventoryIcon(draft.circular?'circular':'linear');topology.setAttribute('aria-pressed',String(draft.circular));
  topology.setAttribute('aria-label',`Topology for ${plasmid.name}: ${draft.circular?'Circular':'Linear'}`);
  topology.title=`${draft.circular?'Circular':'Linear'} · switch to ${draft.circular?'linear':'circular'}`;topology.disabled=saving;
  const backbone=card.querySelector('[data-backbone]');
  backbone.setAttribute('aria-pressed',String(draft.backbone_template));backbone.disabled=saving||!plasmid.backbone_options?.eligible;
  const count=Math.max(0,...Object.values(plasmid.backbone_options?.cassette_counts||{}));
  backbone.title=plasmid.backbone_options?.eligible?((draft.backbone_template?'Backbone template · disable':'Use as backbone template')+(count>1?' · '+count+' cassettes; every opened cassette needs an insert':'')):'No complete BsaI, BsmBI or dual-cut cassette set';
  const save=card.querySelector('[data-save-plasmid]');save.disabled=saving||!dirty;save.title=saving?'Saving…':dirty?'Save changes':'Saved';
  card.querySelector('[data-plasmid-status]').textContent=saving?'Saving…':dirty?'Unsaved':'';
  card.classList.toggle('has-changes',dirty);
}
async function savePlasmidCard(id){
  const plasmid=state.plasmids.find(p=>p.id===id);if(!plasmid||state.plasmidSaving.has(id))return;
  const draft={...plasmidDraft(plasmid),name:plasmidDraft(plasmid).name.trim()};
  const input=[...document.querySelectorAll(`[data-plasmid="${id}"] [data-plasmid-name]`)].find(el=>el.closest('.view.active'));
  if(!draft.name){input?.setCustomValidity('Enter a plasmid name');input?.reportValidity();return;}
  state.plasmidSaving.add(id);document.querySelectorAll(`[data-plasmid="${id}"]`).forEach(card=>syncPlasmidCard(card,plasmid));
  const usedAsBackbone=$('backbone').value==='p:'+id;
  try{
    const saved=await api('/api/plasmids/'+id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(draft)});
    state.plasmidDrafts.delete(id);await refresh();if(usedAsBackbone)backboneChanged();
    if(state.result?.storedReference&&state.result.viewerPlasmidId===id){state.result={...state.result,...saved,storedReference:true,viewerPlasmidId:id};renderResult();}
    state.plasmidSaving.delete(id);renderPlasmidLibraries();toast('Plasmid saved');
  }catch(error){toast(error.message);state.plasmidSaving.delete(id);document.querySelectorAll(`[data-plasmid="${id}"]`).forEach(card=>{syncPlasmidCard(card,plasmid);card.querySelector('[data-plasmid-status]').textContent='Not saved';});}
}
let plasmidViewerSession=null,plasmidViewRequest=0;
function restorePlasmidViewer(){
  const session=plasmidViewerSession;if(!session)return;
  plasmidViewerSession=null;plasmidViewRequest++;clearTimeout(viewerRenameTimer);hideMapTooltip();
  session.panelParent.insertBefore(session.panel,session.panelNext);
  session.tooltipParent.insertBefore(session.tooltip,session.tooltipNext);
  session.panel.classList.remove('hidden');
  state.result=session.result;state.mapMode=session.mapMode;state.selectedFeature=session.selectedFeature;
  $('sequence-start').value=session.sequenceStart;$('map-site-filter').value=session.siteFilter;
  if(state.result)renderResult();
  $('results').classList.toggle('hidden',session.resultsHidden);
  $('feature-detail').textContent=session.detail;$('feature-detail').classList.toggle('hidden',session.detailHidden);
  $('viewer-name-status').textContent=session.nameStatus;
  const focus=session.focus?.isConnected?session.focus:document.querySelector(`.view.active [data-view-plasmid="${session.id}"]`);
  focus?.focus({preventScroll:true});
  if((session.recheck||!session.result)&&(state.parts.length||$('backbone').value))assemblyCheckTimer=setTimeout(checkAssembly,220);
}
async function viewPlasmid(id){return viewSequenceRecord(()=>api('/api/plasmids/'+id),'/api/plasmids/'+id+'/genbank',id);}
window.JunctionSequenceViewer={open:record=>viewSequenceRecord(async()=>record),openPlasmid:viewPlasmid,preview:createSequenceMapPreview};
async function viewSequenceRecord(load,downloadUrl='',id=null){
  const dialog=$('plasmid-view-dialog');if(dialog.open)return;
  const panel=document.querySelector('.viewer-panel'),tooltip=$('map-tooltip');
  plasmidViewerSession={id,result:state.result,mapMode:state.mapMode,selectedFeature:state.selectedFeature,
    sequenceStart:$('sequence-start').value,siteFilter:$('map-site-filter').value,resultsHidden:$('results').classList.contains('hidden'),
    detail:$('feature-detail').textContent,detailHidden:$('feature-detail').classList.contains('hidden'),nameStatus:$('viewer-name-status').textContent,
    panel,panelParent:panel.parentNode,panelNext:panel.nextSibling,tooltip,tooltipParent:tooltip.parentNode,tooltipNext:tooltip.nextSibling,focus:document.activeElement};
  clearTimeout(assemblyCheckTimer);checkCounter++;hideMapTooltip();
  $('plasmid-view-host').append(panel);dialog.append(tooltip);panel.classList.add('hidden');
  $('plasmid-view-loading').textContent='Loading…';$('plasmid-view-loading').classList.remove('hidden');
  $('plasmid-view-download').href=downloadUrl||'#';$('plasmid-view-download').hidden=!downloadUrl;$('plasmid-view-download').classList.toggle('hidden',!downloadUrl);
  $('plasmid-view-context').textContent='';
  dialog.showModal();const request=++plasmidViewRequest;
  try{
    const plasmid=await load();if(request!==plasmidViewRequest||!dialog.open)return;
    state.result={...plasmid,viewerPlasmidId:id,viewerReadOnly:!id,storedReference:true,gc:100*[...plasmid.sequence].filter(c=>c==='G'||c==='C').length/plasmid.sequence.length,junctions:[],errors:[],warnings:['Stored reference'],reaction:{rows:[],warnings:[]}};
    state.mapMode=plasmid.circular?'circular':'linear';state.selectedFeature=null;$('sequence-start').value=1;$('map-site-filter').value='all';
    $('plasmid-view-context').textContent=plasmid.viewSummary||'';
    $('feature-detail').classList.add('hidden');panel.classList.remove('hidden');$('plasmid-view-loading').classList.add('hidden');renderResult();
  }catch(error){if(request===plasmidViewRequest&&dialog.open)$('plasmid-view-loading').textContent=error.message;}
}
let sequenceMapPreviewIndex=0;
function createSequenceMapPreview(host,input){
  // A separate record and DOM scope keep Design previews out of the builder draft.
  const record=JSON.parse(JSON.stringify(input)),length=record.sequence.length,tooltipId='sequence-preview-tooltip-'+(++sequenceMapPreviewIndex);
  let mode=record.circular?'circular':'linear',filter='all',disposed=false,frame=null,renderedWidth=-1;
  host.innerHTML=`<div class="sequence-preview-toolbar"><h3>${esc(record.viewerTitle||'Assembly')}</h3><div class="segmented"><button type="button" data-preview-mode="circular" ${record.circular?'':'disabled'}>Circular</button><button type="button" data-preview-mode="linear">Linear</button></div><label>Sites<select data-preview-sites aria-label="Example assembly restriction sites"><option value="all">All enzymes</option><option value="BsmBI + BsaI">BsmBI + BsaI</option><option>BsaI</option><option>BsmBI</option><option value="none">Hide sites</option></select></label><button type="button" class="icon-button" data-preview-open aria-label="View example assembly" title="View sequence" aria-haspopup="dialog">${inventoryIcon('view')}</button></div><div class="sequence-preview-map" aria-label="Example assembly map"></div><div class="sequence-preview-detail hidden" role="status"></div><div id="${tooltipId}" class="map-tooltip hidden" role="tooltip"></div>`;
  const map=host.querySelector('.sequence-preview-map'),detail=host.querySelector('.sequence-preview-detail'),tooltip=host.querySelector('.map-tooltip');
  const features=mapFeatures({...record,storedReference:true});
  function hide(){tooltip.classList.add('hidden');map.querySelectorAll('.is-hovered').forEach(node=>node.classList.remove('is-hovered'));}
  function description(feature,site=false){return site?`${feature.enzyme} · ${mapSiteRange(feature,length)} · ${feature.motif||''}`:featureSummary(feature,record);}
  function hover(event,node,feature,index,site=false){
    hide();
    const selector=site?`[data-site="${index}"],[data-site-leader="${index}"]`:`[data-feature="${index}"],[data-map-leader="${index}"]`;
    map.querySelectorAll(selector).forEach(item=>item.classList.add('is-hovered'));
    tooltip.innerHTML=`<strong>${esc(site?feature.enzyme:PlasmidFeatures.name(feature))}</strong><small>${esc(description(feature,site))}</small>${site?'':PlasmidFeatures.qualifiers(feature,true).slice(0,6).map(([key,value])=>`<small><b>${esc(key)}</b>: ${esc(value)}</small>`).join('')}`;
    tooltip.classList.remove('hidden');
    const rect=node.getBoundingClientRect(),box=tooltip.getBoundingClientRect(),x=event?.clientX??rect.left+rect.width/2,y=event?.clientY??rect.top;
    tooltip.style.left=Math.max(10,Math.min(x+14,window.innerWidth-box.width-10))+'px';
    tooltip.style.top=Math.max(10,Math.min(y+18+box.height<window.innerHeight-10?y+18:y-box.height-12,window.innerHeight-box.height-10))+'px';
  }
  function select(feature,site=false){
    detail.classList.remove('hidden');detail.textContent=(site?feature.enzyme:PlasmidFeatures.name(feature))+' · '+description(feature,site);
  }
  function render(){
    if(disposed)return;hide();renderedWidth=map.clientWidth;
    const sites=(record.restriction_sites||[]).map((site,index)=>({...site,index})).filter(site=>filter==='all'||(filter==='BsmBI + BsaI'?['BsmBI','BsaI'].includes(site.enzyme):site.enzyme===filter));
    const width=Math.max(620,renderedWidth||780),tools=mapTextTools(map);
    map.innerHTML=(mode==='circular'?circularMapSvg:linearMapSvg)(record,features,width,tools,sites,tooltipId);
    host.querySelectorAll('[data-preview-mode]').forEach(button=>{const active=button.dataset.previewMode===mode;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));});
    function bind(selector,lookup,site){map.querySelectorAll(selector).forEach(node=>{
      const index=Number(site?node.dataset.site:node.dataset.feature),feature=lookup(index);if(!feature)return;
      node.onpointerenter=node.onpointermove=event=>hover(event,node,feature,index,site);
      node.onpointerleave=hide;node.onfocus=()=>hover(null,node,feature,index,site);node.onblur=hide;
      node.onclick=()=>select(feature,site);
      node.onkeydown=event=>{if(event.key==='Escape'){hide();node.blur();}if(event.key==='Enter'||event.key===' '){event.preventDefault();select(feature,site);}};
    });}
    bind('[data-feature]',index=>features[index],false);bind('[data-site]',index=>sites.find(site=>site.index===index),true);
  }
  host.querySelectorAll('[data-preview-mode]').forEach(button=>button.onclick=()=>{mode=button.dataset.previewMode;render();});
  host.querySelector('[data-preview-sites]').onchange=event=>{filter=event.target.value;render();};
  host.querySelector('[data-preview-open]').onclick=()=>{hide();viewSequenceRecord(async()=>record);};
  const observer=new ResizeObserver(()=>{if(disposed||!map.clientWidth||Math.abs(map.clientWidth-renderedWidth)<1)return;cancelAnimationFrame(frame);frame=requestAnimationFrame(render);});
  observer.observe(map);window.addEventListener('scroll',hide,{passive:true,capture:true});window.addEventListener('resize',hide,{passive:true});
  render();
  return{destroy(){if(disposed)return;disposed=true;observer.disconnect();cancelAnimationFrame(frame);window.removeEventListener('scroll',hide,true);window.removeEventListener('resize',hide);hide();host.replaceChildren();}};
}
function renderPlasmidLibraries(){
  finishPlasmidSelectionDrag();
  for(const targetId of ['plasmid-library','uploaded-plasmids']){
    const root=$(targetId);root.setAttribute('aria-label','Plasmids');
    root.innerHTML=`<div class="plasmid-selection-bar"><span data-plasmid-count role="status">0 selected</span><div class="plasmid-selection-actions"><button class="icon-button" data-plasmid-all aria-label="Select all plasmids" title="Select all">${inventoryIcon('selectAll')}</button><button class="icon-button" data-plasmid-clear aria-label="Clear plasmid selection" title="Clear selection">${inventoryIcon('clear')}</button><button class="icon-button archive-button" data-archive-plasmids aria-label="Archive selected plasmids" title="Archive selected" disabled>${inventoryIcon('trash')}</button></div></div>`+state.plasmids.map(p=>{
      const draft=plasmidDraft(p);
      const enzymes=Object.entries(p.backbone_options?.site_counts||{}).filter(([,count])=>count).map(([enzyme])=>enzyme).join(' · ');
      const cassetteCount=Math.max(0,...Object.values(p.backbone_options?.cassette_counts||{}));
      return `<article class="plasmid-item" data-plasmid="${p.id}" tabindex="0" role="group" aria-label="Plasmid ${esc(p.name)}, not selected"><span class="plasmid-selected-mark" aria-hidden="true">${inventoryIcon('check')}</span><label class="plasmid-name-field"><input data-plasmid-name aria-label="Name of ${esc(p.name)}" value="${esc(draft.name)}" maxlength="100" required autocomplete="off" title="Edit plasmid name"><span aria-hidden="true">${inventoryIcon('edit')}</span></label><div class="plasmid-card-meta"><span>${fmt(p.length,0)} bp</span><small>${esc(enzymes)}${cassetteCount>1?' · '+cassetteCount+' cassettes':''}</small></div><div class="plasmid-card-bottom"><div class="plasmid-actions"><button class="icon-button state-icon" data-topology aria-pressed="${draft.circular}" title="Topology"></button><button class="icon-button state-icon backbone-toggle" data-backbone aria-label="Backbone template for ${esc(p.name)}" aria-pressed="${draft.backbone_template}">${inventoryIcon('backbone')}</button><button class="icon-button" data-save-plasmid="${p.id}" aria-label="Save ${esc(p.name)}" title="Save">${inventoryIcon('save')}</button><button class="icon-button" data-view-plasmid="${p.id}" aria-haspopup="dialog" aria-controls="plasmid-view-dialog" aria-label="View ${esc(p.name)}" title="View saved plasmid">${inventoryIcon('view')}</button><a class="icon-button" href="/api/plasmids/${p.id}/genbank" aria-label="Download ${esc(p.name)} GenBank" title="Download saved GenBank">${inventoryIcon('download')}</a></div><small data-plasmid-status role="status"></small></div></article>`;
    }).join('');
    root.querySelector('[data-plasmid-all]').onclick=()=>{for(const p of state.plasmids)state.plasmidSelection.add(p.id);updatePlasmidSelection();};
    root.querySelector('[data-plasmid-clear]').onclick=()=>{state.plasmidSelection.clear();updatePlasmidSelection();};
    root.querySelector('[data-archive-plasmids]').onclick=()=>archiveSelection([],Array.from(state.plasmidSelection));
    root.querySelectorAll('[data-plasmid]').forEach(card=>{
      const id=Number(card.dataset.plasmid),plasmid=state.plasmids.find(p=>p.id===id),input=card.querySelector('[data-plasmid-name]');
      syncPlasmidCard(card,plasmid);
      input.oninput=()=>{input.setCustomValidity('');changePlasmidDraft(plasmid,{name:input.value});};
      input.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();savePlasmidCard(id);}if(event.key==='Escape'){event.preventDefault();input.value=plasmid.name;input.setCustomValidity('');changePlasmidDraft(plasmid,{name:plasmid.name});input.blur();}};
      card.querySelector('[data-topology]').onclick=()=>{const draft=plasmidDraft(plasmid);changePlasmidDraft(plasmid,{circular:!draft.circular,...(draft.circular?{backbone_template:false}:{})});};
      card.querySelector('[data-backbone]').onclick=()=>{const draft=plasmidDraft(plasmid);changePlasmidDraft(plasmid,{backbone_template:!draft.backbone_template,...(!draft.backbone_template?{circular:true}:{})});};
      card.querySelector('[data-save-plasmid]').onclick=()=>savePlasmidCard(id);
      card.querySelector('[data-view-plasmid]').onclick=()=>viewPlasmid(id);
    });
    bindPlasmidSelection(root);
  }
  updatePlasmidSelection();
}
function togglePlasmidSelection(id){state.plasmidSelection.has(id)?state.plasmidSelection.delete(id):state.plasmidSelection.add(id);updatePlasmidSelection();}
let plasmidSelectionDrag=null,plasmidSelectionClickUntil=0;
function finishPlasmidSelectionDrag(){
  if(plasmidSelectionDrag){const {root,pointerId}=plasmidSelectionDrag;if(root.hasPointerCapture(pointerId))root.releasePointerCapture(pointerId);root.classList.remove('is-selecting');}
  plasmidSelectionDrag=null;$('plasmid-selection-box').classList.add('hidden');
}
function drawPlasmidSelection(event){
  const drag=plasmidSelectionDrag;if(!drag||(event.pointerId!==undefined&&event.pointerId!==drag.pointerId))return;drag.x=event.clientX;drag.y=event.clientY;
  if(!drag.active&&Math.hypot(drag.x-drag.startX,drag.y-drag.startY)<6)return;
  if(!drag.active){drag.active=true;drag.root.setPointerCapture(drag.pointerId);drag.root.classList.add('is-selecting');}
  event.preventDefault?.();
  const rect={left:Math.min(drag.x,drag.startX),right:Math.max(drag.x,drag.startX),top:Math.min(drag.y,drag.startY),bottom:Math.max(drag.y,drag.startY)};
  const box=$('plasmid-selection-box');box.classList.remove('hidden');Object.assign(box.style,{left:rect.left+'px',top:rect.top+'px',width:rect.right-rect.left+'px',height:rect.bottom-rect.top+'px'});
  state.plasmidSelection=new Set(drag.base);
  drag.root.querySelectorAll('[data-plasmid]').forEach(card=>{const r=card.getBoundingClientRect();if(r.left<rect.right&&r.right>rect.left&&r.top<rect.bottom&&r.bottom>rect.top)state.plasmidSelection.add(Number(card.dataset.plasmid));});
  updatePlasmidSelection();
}
function bindPlasmidSelection(root){
  const interactive=target=>target.closest('button,input,a,select,textarea,label');
  root.onpointerdown=event=>{
    if(event.button!==0||event.pointerType==='touch'||interactive(event.target))return;
    const card=event.target.closest('[data-plasmid]');card?.focus({preventScroll:true});event.preventDefault();
    plasmidSelectionDrag={root,pointerId:event.pointerId,startX:event.clientX,startY:event.clientY,x:event.clientX,y:event.clientY,active:false,base:new Set(event.shiftKey||event.ctrlKey||event.metaKey?state.plasmidSelection:[]),original:new Set(state.plasmidSelection)};
  };
  root.onpointermove=drawPlasmidSelection;
  root.onpointerup=event=>{if(plasmidSelectionDrag?.pointerId!==event.pointerId)return;if(plasmidSelectionDrag.active)plasmidSelectionClickUntil=performance.now()+150;finishPlasmidSelectionDrag();};
  root.onpointercancel=()=>{if(plasmidSelectionDrag){state.plasmidSelection=plasmidSelectionDrag.original;updatePlasmidSelection();finishPlasmidSelectionDrag();}};
  root.onclick=event=>{if(performance.now()<plasmidSelectionClickUntil||interactive(event.target))return;const card=event.target.closest('[data-plasmid]');if(card)togglePlasmidSelection(Number(card.dataset.plasmid));else{state.plasmidSelection.clear();updatePlasmidSelection();}};
  root.onkeydown=event=>{
    if(interactive(event.target))return;
    const card=event.target.closest('[data-plasmid]');
    if(card&&[' ','Enter'].includes(event.key)){event.preventDefault();togglePlasmidSelection(Number(card.dataset.plasmid));}
    if(event.key==='Escape'){event.preventDefault();if(plasmidSelectionDrag){state.plasmidSelection=plasmidSelectionDrag.original;finishPlasmidSelectionDrag();}else state.plasmidSelection.clear();updatePlasmidSelection();}
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='a'){event.preventDefault();for(const p of state.plasmids)state.plasmidSelection.add(p.id);updatePlasmidSelection();}
  };
}
window.addEventListener('pointerup',()=>{if(plasmidSelectionDrag&&!plasmidSelectionDrag.active)finishPlasmidSelectionDrag();});
window.addEventListener('blur',finishPlasmidSelectionDrag);
window.addEventListener('scroll',()=>{if(plasmidSelectionDrag?.active)drawPlasmidSelection({clientX:plasmidSelectionDrag.x,clientY:plasmidSelectionDrag.y});},true);
function updateUploadPlasmidIcons(){
  const mode=$('upload-topology').value;
  document.querySelectorAll('[data-upload-topology]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.uploadTopology===mode)));
  $('upload-topology-label').textContent=mode==='file'?'From file':mode==='circular'?'Circular':'Linear';
  $('upload-backbone-toggle').setAttribute('aria-pressed',String($('upload-backbone').checked));
}

function inventoryIcon(name){
  const paths={reverse:'<path d="M4 7h16m-5-4 5 4-5 4M20 17H4m5-4-5 4 5 4"/>',close:'<path d="m6 6 12 12M18 6 6 18"/>',back:'<path d="m10 5-7 7 7 7M3 12h18"/>',previous:'<path d="m15 5-7 7 7 7"/>',next:'<path d="m9 5 7 7-7 7"/>',check:'<path d="m5 12 4 4L19 6"/>',up:'<path d="M12 20V4m-6 6 6-6 6 6"/>',down:'<path d="M12 4v16m-6-6 6 6 6-6"/>',sort:'<path d="M8 20V4m-4 4 4-4 4 4M16 4v16m-4-4 4 4 4-4"/>',circular:'<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5.5"/><path d="M12 3v3.5M12 17.5V21M3 12h3.5M17.5 12H21"/><path class="icon-cassette" d="M16.1 4a9 9 0 0 1 4 4"/>',linear:'<path d="M2 8h17M5 16h17M6 8v8M10 8v8M14 8v8M18 8v8"/><path class="icon-cassette" d="M2 8h4M18 16h4"/>',backbone:'<path d="M10 3a9 9 0 1 0 11 11M10 6.5A5.5 5.5 0 1 0 17.5 14"/><path d="M3 12h3.5M12 17.5V21"/><rect x="13" y="2" width="9" height="9" rx="2" stroke-dasharray="2 2"/><path d="M17.5 4.5v4M15.5 6.5h4"/>',save:'<path d="M4 3h13l3 3v15H4zM8 3v6h8V3M8 21v-8h8v8"/>',view:'<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',download:'<path d="M12 3v12M7 10l5 5 5-5M4 16v5h16v-5"/>',selectAll:'<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5M8 12l3 3 5-6"/>',clear:'<rect x="4" y="4" width="16" height="16" rx="2"/><path d="m8 8 8 8M16 8l-8 8"/>',edit:'<path d="m4 16 12-12 4 4L8 20H4zM13 7l4 4"/>',file:'<path d="M5 3h9l5 5v13H5zM14 3v5h5M8 13h8M8 17h5"/>',trash:'<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',reset:'<path d="M3 10a9 9 0 1 1 2 8M3 4v6h6"/>',locked:'<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4M12 14v3"/>',unlocked:'<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M16 10V6a4 4 0 0 0-8 0M12 14v3"/>'};
  return `<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${paths[name]||''}</svg>`;
}
function archiveIconButton(button,count,kind){button.disabled=!count;button.innerHTML=inventoryIcon('trash')+(count?`<span class="icon-count">${count}</span>`:'');button.setAttribute('aria-label',`Archive selected ${kind}${count?' ('+count+')':''}`);button.title=`Archive selected ${kind}`;}
function updateFragmentSelection(){
  const rows=[...$('inventory-body').querySelectorAll('[data-inventory-id]')];const count=rows.filter(r=>state.fragmentSelection.has(Number(r.dataset.inventoryId))).length;$('select-fragments').disabled=!rows.length;
  $('select-fragments').checked=!!rows.length&&count===rows.length;$('select-fragments').indeterminate=count>0&&count<rows.length;
  archiveIconButton($('archive-fragments'),state.fragmentSelection.size,'fragments');$('reset-inventory').disabled=!state.fragmentSelection.size;$('apply-inventory-rules').disabled=!state.fragmentSelection.size;
}
function updatePlasmidSelection(){
  const valid=new Set(state.plasmids.map(p=>p.id));for(const id of state.plasmidSelection)if(!valid.has(id))state.plasmidSelection.delete(id);
  const count=state.plasmidSelection.size;
  for(const targetId of ['plasmid-library','uploaded-plasmids']){
    const root=$(targetId);if(!root.querySelector('[data-plasmid-all]'))continue;
    root.querySelector('[data-plasmid-count]').textContent=count+' selected';root.querySelector('[data-plasmid-clear]').disabled=!count;
    root.querySelectorAll('[data-plasmid]').forEach(card=>{const id=Number(card.dataset.plasmid),selected=state.plasmidSelection.has(id),part=state.plasmids.find(p=>p.id===id);card.classList.toggle('is-selected',selected);card.setAttribute('aria-label',`Plasmid ${part.name}, ${selected?'selected':'not selected'}`);});
    archiveIconButton(root.querySelector('[data-archive-plasmids]'),count,'plasmids');
  }
}

async function archiveSelection(fragmentIds,plasmidIds){
  try{await Promise.all(fragmentIds.map(persistInventoryRow));const r=await api('/api/bin/archive',jsonBody({fragment_ids:fragmentIds,plasmid_ids:plasmidIds}));for(const id of fragmentIds)state.inventoryDrafts.delete(id);state.fragmentSelection.clear();state.plasmidSelection.clear();for(const id of plasmidIds)state.plasmidDrafts.delete(id);state.parts=state.parts.filter(p=>!fragmentIds.includes(p.id));await refresh();backboneChanged();await loadInventory();if($('uploads').classList.contains('active'))await loadUploads();toast(`Moved ${r.count} item(s) to Bin`);}catch(e){toast(e.message);}
}
function sortInventoryRows(){
  const sort=state.inventorySort;if(!sort)return;
  const numeric=new Set(['length','yield_ng','resuspension_ul','stock_ng_ul','aliquot']);
  const value=row=>{const input=row.querySelector(`[data-quantity="${sort.key}"]`);const v=input?input.dataset.rawValue:row.dataset[sort.key];return v===undefined||v===''?null:numeric.has(sort.key)?Number(v):v;};
  const rows=[...$('inventory-body').querySelectorAll('tr')];rows.sort((a,b)=>{const x=value(a),y=value(b);if(x===null)return y===null?0:1;if(y===null)return-1;const delta=numeric.has(sort.key)?x-y:String(x).localeCompare(String(y),undefined,{numeric:true,sensitivity:'base'});return sort.direction*delta;});
  $('inventory-body').append(...rows);
  document.querySelectorAll('[data-inventory-sort]').forEach(button=>{const active=button.dataset.inventorySort===sort.key;button.closest('th').setAttribute('aria-sort',active?(sort.direction===1?'ascending':'descending'):'none');button.querySelector('span').innerHTML=inventoryIcon(active?(sort.direction===1?'up':'down'):'sort');});
}
async function loadBin(){
  try{const data=await api('/api/bin');$('bin-body').innerHTML=data.rows.length?data.rows.map(row=>`<tr><td><input type="checkbox" data-bin-kind="${row.kind}" data-bin-id="${esc(row.id)}" aria-label="Restore ${esc(row.kind)} ${esc(row.name)}"></td><td>${esc(row.kind)}</td><td>${row.kind==='plate'?`<button class="plate-bin-open" data-bin-plate="${esc(row.plate_id)}" aria-haspopup="dialog" title="${esc(row.plate_id)}">${esc(plateLabel(row.plate_id))}</button>`:esc(row.name)}</td><td title="${esc(row.plate_id)}">${esc(plateLabel(row.plate_id))}</td><td>${esc(row.well)}</td><td>${esc(row.archived_at)}</td></tr>`).join(''):'<tr><td colspan="6">Bin is empty</td></tr>';$('select-bin').checked=false;$('restore-bin').disabled=true;$('bin-body').querySelectorAll('input').forEach(input=>input.onchange=updateBinSelection);$('bin-body').querySelectorAll('[data-bin-plate]').forEach(button=>button.onclick=()=>openPlateMap(button.dataset.binPlate));}catch(e){toast(e.message);}
}
function updateBinSelection(){const boxes=[...$('bin-body').querySelectorAll('[data-bin-id]')];const count=boxes.filter(b=>b.checked).length;$('select-bin').checked=!!boxes.length&&count===boxes.length;$('select-bin').indeterminate=count>0&&count<boxes.length;$('restore-bin').disabled=!count;}
let inventoryLoadCounter=0;
const inventoryValue=x=>x===null||x===undefined?'':Number(x).toFixed(2);
const inventoryQuantity=x=>x===null||x===undefined?'—':Number(x).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
// Display rounding must never become an input to linked calculations or autosaves.
function setInventoryValue(field,value){field.dataset.rawValue=value??'';if(document.activeElement!==field)field.value=inventoryValue(value);}
function inventoryEnzymeFlags(sites){
  const counts={};for(const site of sites||[])counts[site.enzyme]=(counts[site.enzyme]||0)+1;
  const label=Object.entries(counts).map(([enzyme,count])=>enzyme+(count>1?' ×'+count:'')).join(' · ');
  return label?`<small class="inventory-note enzyme-detection" title="${esc((sites||[]).map(site=>site.enzyme+' · '+(site.start+1)+'–'+site.end).join('\n'))}">${esc(label)}</small>`:'';
}
function inventoryWarningNote(warnings){
  return [...new Set(warnings.map(message=>{
    if(/aliquot outside|input.volume limits|input.volume.*exceeds|No feasible plan|No feasible resuspension/i.test(message))return 'Volume outside limits';
    if(/resuspension exceeds/i.test(message))return 'Resuspension above cap';
    if(/insufficient.*(yield|mass)/i.test(message))return 'Insufficient yield';
    if(/length missing/i.test(message))return 'Length missing';
    if(/mass unknown/i.test(message))return 'Yield missing';
    if(/plate identifier or well missing/i.test(message))return 'Plate/well missing';
    if(/missing length or available mass/i.test(message))return 'Length/yield missing';
    if(/backbone physical length/i.test(message))return 'Backbone outside 1.5–10 kb';
    return 'Check stock';
  }))].join(' · ');
}
function applyInventoryRules(rules){
  if(JSON.stringify(rules)===JSON.stringify(state.rules))return;
  state.rules=rules;
  const planner={...plannerRuleDefaults(),...state.plannerOverrides};
  for(const[id,key]of Object.entries(plannerInputKeys))$(id).value=planner[key];
  for(const[key,value]of Object.entries(rules))$('rule-'+key).value=value;
  updatePlannerRuleLabels();updateUploadRuleLabels();
}
async function reloadInventory(){await refresh();invalidate();await loadInventory();}
function inventoryRow(id){return $('inventory-body').querySelector(`[data-inventory-id="${id}"]`);}
function inventorySaveEntry(id){if(!state.inventoryAutosaves.has(id))state.inventoryAutosaves.set(id,{revision:0,timer:null,inflight:null,resetting:false});return state.inventoryAutosaves.get(id);}
function inventoryStatus(id,message,error=false){const row=inventoryRow(id);if(row){row.querySelector('[data-record-status]').textContent=message;row.querySelector('[data-record-status]').classList.toggle('save-error',error);}}
function setYieldLock(row,locked){
  row.dataset.yieldLocked=String(locked);const field=row.querySelector('[data-quantity="yield_ng"]');field.readOnly=locked;
  const button=row.querySelector('[data-yield-lock]');button.innerHTML=inventoryIcon(locked?'locked':'unlocked');button.setAttribute('aria-pressed',String(locked));button.setAttribute('aria-label',`${locked?'Unlock':'Lock'} yield for ${row.dataset.name}`);button.title=locked?'Yield locked · stock and volume update each other':'Yield unlocked · stock and volume recalculate yield';
}
function queueInventoryRow(id,values,{quantitiesChanged=false,invalid=false}={}){
  const entry=inventorySaveEntry(id);if(entry.resetting)return;
  const previous=state.inventoryDrafts.get(id);const draft={...values,quantitiesChanged:quantitiesChanged||!!previous?.quantitiesChanged,invalid,revision:++entry.revision};
  state.inventoryDrafts.set(id,draft);clearTimeout(entry.timer);inventoryStatus(id,invalid?'Enter a positive value':'Unsaved',invalid);
  if(!invalid)entry.timer=setTimeout(()=>persistInventoryRow(id).catch(()=>{}),450);
}
async function persistInventoryRow(id){
  const entry=inventorySaveEntry(id);clearTimeout(entry.timer);
  if(entry.inflight)return entry.inflight;
  if(entry.resetting||!state.inventoryDrafts.has(id))return;
  entry.inflight=(async()=>{
    while(state.inventoryDrafts.has(id)&&!entry.resetting){
      const draft={...state.inventoryDrafts.get(id)};
      if(draft.invalid)throw Error('Finish the invalid inventory value before continuing.');
      const body=draft.quantitiesChanged?{yield_ng:draft.yield_ng,stock_ng_ul:draft.stock_ng_ul,resuspension_ul:draft.resuspension_ul,derive:draft.derive,yield_locked:draft.yield_locked}:{yield_locked:draft.yield_locked};
      inventoryStatus(id,'Saving…');
      try{
        const saved=await api('/api/fragments/'+id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        for(const part of [...state.fragments,...state.parts])if(part.id===id)Object.assign(part,saved);
        if(!entry.resetting&&state.inventoryDrafts.get(id)?.revision===draft.revision){
          state.inventoryDrafts.delete(id);const row=inventoryRow(id);
          if(row){
            for(const key of ['yield_ng','resuspension_ul','stock_ng_ul']){const field=row.querySelector(`[data-quantity="${key}"]`);setInventoryValue(field,saved.inventory[key]);}
            setYieldLock(row,saved.yield_locked);const warning=row.querySelector('[data-record-warnings]');warning.textContent=inventoryWarningNote(saved.inventory.warnings);warning.title=saved.inventory.warnings.join(' ');row.dataset.target=saved.inventory.target_ng??'';row.dataset.aliquot=saved.inventory.input_volume_ul??'';row.querySelector('[data-aliquot-value]').textContent=inventoryQuantity(saved.inventory.input_volume_ul);
          }
          inventoryStatus(id,saved.inventory.saved?'Saved':'Planned');
        }
        invalidate();
      }catch(error){inventoryStatus(id,'Not saved',true);toast(error.message);throw error;}
    }
  })();
  try{return await entry.inflight;}finally{entry.inflight=null;}
}
async function resetInventoryRows(ids){
  if(!ids.length)return;
  const entries=ids.map(id=>inventorySaveEntry(id));
  for(let i=0;i<ids.length;i++){const entry=entries[i];entry.resetting=true;clearTimeout(entry.timer);inventoryRow(ids[i])?.querySelectorAll('input,button').forEach(el=>el.disabled=true);}
  try{
    await Promise.all(entries.map(entry=>entry.inflight?.catch(()=>{})));
    await api('/api/inventory/reset',jsonBody({fragment_ids:ids}));
    for(const id of ids)state.inventoryDrafts.delete(id);
    await reloadInventory();toast(ids.length===1?'Row reset to defaults':'Selected rows reset to defaults');
  }catch(error){toast(error.message);}
  finally{for(let i=0;i<ids.length;i++){entries[i].resetting=false;inventoryRow(ids[i])?.querySelectorAll('input,button').forEach(el=>el.disabled=false);}}
}
let inventoryRuleSelection=[];
const inventoryRuleLabels={backbone_pmol:'DNA input · pmol',insert_ratio:'Fragment ratio',preferred_resuspension_ul:'Preferred resuspend · µL',max_resuspension_ul:'Maximum resuspend · µL',min_input_volume_ul:'Minimum aliquot · µL',max_input_volume_ul:'Maximum aliquot · µL'};
function fillSelectedRuleFields(rules){
  $('inventory-rule-fields').innerHTML=Object.entries(inventoryRuleLabels).map(([key,label])=>{
    return `<label>${label}<input id="selected-rule-${key}" type="number" min="0" step="any" value="${rules[key]}" required></label>`;
  }).join('');
}
function openSelectedRules(){
  inventoryRuleSelection=Array.from(state.fragmentSelection);if(!inventoryRuleSelection.length)return;
  const rules=Object.fromEntries(Object.keys(inventoryRuleLabels).map(key=>[key,Number($('rule-'+key).value)]));
  fillSelectedRuleFields(rules);$('inventory-rule-selection').textContent=inventoryRuleSelection.length+' selected';$('inventory-rule-error').classList.add('hidden');$('inventory-rule-editor').showModal();
}
async function applySelectedRules(event){
  event.preventDefault();const ids=[...inventoryRuleSelection],button=$('inventory-rule-apply');button.disabled=true;$('inventory-rule-close').disabled=true;$('inventory-rule-default').disabled=true;
  const entries=ids.map(id=>inventorySaveEntry(id));
  try{
    await Promise.all(ids.map(persistInventoryRow));
    for(const entry of entries){entry.resetting=true;clearTimeout(entry.timer);}
    const rules=Object.fromEntries(Object.keys(inventoryRuleLabels).map(key=>[key,Number($('selected-rule-'+key).value)]));
    const result=await api('/api/inventory/apply-rules',jsonBody({fragment_ids:ids,rules}));
    for(const id of ids)state.inventoryDrafts.delete(id);
    $('inventory-rule-editor').close();await reloadInventory();toast('Rules applied to '+result.count+' fragment'+(result.count===1?'':'s'));
  }catch(error){$('inventory-rule-error').textContent=error.message;$('inventory-rule-error').classList.remove('hidden');}
  finally{button.disabled=false;$('inventory-rule-close').disabled=false;$('inventory-rule-default').disabled=false;for(const entry of entries)entry.resetting=false;}
}
async function loadInventory(){
  const token=++inventoryLoadCounter;
  try{
    const q=$('library-search').value;
    const[records,inventory]=await Promise.all([api('/api/fragments?limit=1000&enzyme='+encodeURIComponent($('library-enzyme').value)+'&q='+encodeURIComponent(q)+'&plate='+encodeURIComponent($('plate-filter').value)),api('/api/inventory/records')]);
    if(token!==inventoryLoadCounter)return;
    const byId=new Map(inventory.rows.map(x=>[x.id,x]));const visibleIds=new Set(records.map(f=>f.id));for(const id of state.fragmentSelection)if(!visibleIds.has(id))state.fragmentSelection.delete(id);
    $('inventory-body').innerHTML=records.map(f=>{
      const stored=byId.get(f.id);const draft=state.inventoryDrafts.get(f.id);const values=draft||stored;const locked=values.yield_locked!==false;
      const input=(key,label)=>`<input type="number" min="0.000001" step="any" data-quantity="${key}" data-raw-value="${values[key]??''}" ${key==='yield_ng'&&locked?'readonly':''} value="${inventoryValue(values[key])}" aria-label="${label} of ${esc(f.name)}">`;
      const yieldField=`<div class="yield-field">${input('yield_ng','Yield ng')}<button class="yield-lock" data-yield-lock type="button" aria-pressed="${locked}" aria-label="${locked?'Unlock':'Lock'} yield for ${esc(f.name)}" title="${locked?'Yield locked · stock and volume update each other':'Yield unlocked · stock and volume recalculate yield'}">${inventoryIcon(locked?'locked':'unlocked')}</button></div>`;
      const aliquot=stored.target_ng&&values.stock_ng_ul?stored.target_ng/values.stock_ng_ul:null;
      return `<tr data-yield-locked="${locked}" data-name="${esc(f.name)}" data-plate="${esc(f.plate_id)}" data-well="${esc(f.well)}" data-length="${f.physical_length}" data-ends="${esc((f.digest.left_overhang||'')+(f.digest.right_overhang||''))}" data-target="${stored.target_ng??''}" data-aliquot="${aliquot??''}" data-inventory-id="${f.id}" data-derive="${draft?.derive||'stock_ng_ul'}"><td><input type="checkbox" data-fragment-select aria-label="Select fragment ${esc(f.name)}" ${state.fragmentSelection.has(f.id)?'checked':''}></td><td><button class="fragment-name-open" type="button" data-fragment-open="${f.id}" aria-label="View fragment ${esc(f.name)}" aria-haspopup="dialog" title="${f.plate_id&&f.well?'View plate location':'View fragment information'}">${esc(f.name)}</button>${FragmentSearch.stockBadge(f)}${f.location?`<small class="stock-location">${esc(f.location)}</small>`:""}${inventoryEnzymeFlags(f.sites)}</td><td title="${esc(f.plate_id)}">${esc(plateLabel(f.plate_id))}</td><td>${esc(f.well)}</td><td>${fmt(f.physical_length,0)}</td><td>${fusionEnds(f.digest.left_overhang,f.digest.right_overhang)}</td><td>${yieldField}</td><td>${input('resuspension_ul','Resuspend µL')}</td><td>${input('stock_ng_ul','Stock ng/µL')}</td><td><span data-aliquot-value>${inventoryQuantity(aliquot)}</span><small data-record-warnings class="reaction-warning inventory-note" title="${esc(stored.warnings.join(' '))}">${esc(inventoryWarningNote(stored.warnings))}</small></td><td><button class="icon-button row-reset" data-record-reset aria-label="Reset ${esc(f.name)} to defaults" title="Reset ${esc(f.name)} to defaults">${inventoryIcon('reset')}</button><small data-record-status title="${esc(stored.concentration_basis||'')}">${draft?draft.invalid?'Not saved':'Unsaved':stored.concentration_basis==='Custom rule plan (unmeasured)'?'Rules applied':stored.saved?'Saved':'Planned'}</small></td></tr>`;
    }).join('');
    $('inventory-body').querySelectorAll('[data-inventory-id]').forEach(row=>{
      const id=Number(row.dataset.inventoryId);row.querySelector('[data-fragment-open]').onclick=()=>openInventoryFragment(records.find(f=>f.id===id));row.querySelector('[data-fragment-select]').onchange=event=>{event.target.checked?state.fragmentSelection.add(id):state.fragmentSelection.delete(id);updateFragmentSelection();};
      const field=key=>row.querySelector(`[data-quantity="${key}"]`);
      const values=()=>({...Object.fromEntries(['yield_ng','resuspension_ul','stock_ng_ul'].map(key=>[key,field(key).dataset.rawValue!==''?Number(field(key).dataset.rawValue):null])),yield_locked:row.dataset.yieldLocked==='true',derive:row.dataset.derive});
      row.querySelector('[data-yield-lock]').onclick=()=>{setYieldLock(row,row.dataset.yieldLocked!=='true');queueInventoryRow(id,values(),{invalid:!!state.inventoryDrafts.get(id)?.invalid});};
      row.querySelectorAll('[data-quantity]').forEach(input=>{
        input.oninput=()=>{
          input.dataset.rawValue=input.value;const key=input.dataset.quantity;const v=values();const invalid=!(Number.isFinite(v[key])&&v[key]>0);input.setAttribute('aria-invalid',String(invalid));
          const derive=key==='yield_ng'?'stock_ng_ul':!v.yield_locked?'yield_ng':key==='stock_ng_ul'?'resuspension_ul':'stock_ng_ul';
          if(!invalid){const value=derive==='yield_ng'?v.stock_ng_ul&&v.resuspension_ul?v.stock_ng_ul*v.resuspension_ul:null:derive==='stock_ng_ul'?v.yield_ng&&v.resuspension_ul?v.yield_ng/v.resuspension_ul:null:v.yield_ng&&v.stock_ng_ul?v.yield_ng/v.stock_ng_ul:null;setInventoryValue(field(derive),value);}
          const aliquot=Number(row.dataset.target)>0&&Number(field('stock_ng_ul').dataset.rawValue)>0?Number(row.dataset.target)/Number(field('stock_ng_ul').dataset.rawValue):null;row.dataset.aliquot=aliquot??'';row.querySelector('[data-aliquot-value]').textContent=inventoryQuantity(aliquot);row.dataset.derive=derive;
          queueInventoryRow(id,values(),{quantitiesChanged:true,invalid});
        };
        input.onblur=()=>{if(input.getAttribute('aria-invalid')!=='true')input.value=inventoryValue(input.dataset.rawValue===''?null:Number(input.dataset.rawValue));if(state.inventoryDrafts.has(id)&&!state.inventoryDrafts.get(id).invalid)persistInventoryRow(id).catch(()=>{});};
      });
      row.querySelector('[data-record-reset]').onclick=()=>resetInventoryRows([id]);
    });
    sortInventoryRows();updateFragmentSelection();renderPlasmidLibraries();
  }catch(e){toast(e.message);}
}
async function loadUploads(){try{const [plates,history]=await Promise.all([api('/api/plates'),api('/api/uploads')]);state.plateMaps=plates;renderPlateMaps();renderPlasmidLibraries();$('upload-history').innerHTML=history.length?history.map(h=>`<div class="history-row"><span><b>${esc(h.filename)}</b><small class="muted"> · ${esc(h.kind)} · ${h.row_count} rows</small></span><span class="muted">${esc(h.created_at)}</span></div>`).join(''):'<p>No plate imports yet.</p>';}catch(e){toast(e.message);}}
function renderPlateMaps(){
  const valid=new Set(state.plateMaps.map(p=>p.plate_id));for(const id of state.plateSelection)if(!valid.has(id))state.plateSelection.delete(id);
  $('example-files').innerHTML=state.plateMaps.length?state.plateMaps.map(p=>`<div class="plate-map-row ${state.plateSelection.has(p.plate_id)?'selected':''}"><input type="checkbox" data-plate-select="${esc(p.plate_id)}" aria-label="Select plate ${esc(p.plate_id)}" ${state.plateSelection.has(p.plate_id)?'checked':''}><button class="plate-map-open" data-plate-open="${esc(p.plate_id)}" aria-haspopup="dialog" aria-controls="plate-viewer"><b title="${esc(p.plate_id)}">${esc(plateLabel(p.plate_id))}</b><small class="muted">${esc(p.filenames.join(' · '))}</small></button><span class="plate-map-count small muted">${p.active_wells} / ${p.occupied_wells} active</span><span class="badge neutral" title="${esc(p.layout_basis)}">${p.format}</span><a class="icon-button" href="/api/plates/export?plate_id=${encodeURIComponent(p.plate_id)}" aria-label="Download plate ${esc(p.plate_id)}" title="Download current plate map">${inventoryIcon('download')}</a></div>`).join(''):'<span class="small muted">No plate maps</span>';
  $('example-files').querySelectorAll('[data-plate-select]').forEach(input=>input.onchange=()=>{input.checked?state.plateSelection.add(input.dataset.plateSelect):state.plateSelection.delete(input.dataset.plateSelect);input.closest('.plate-map-row').classList.toggle('selected',input.checked);updatePlateSelection();});
  $('example-files').querySelectorAll('[data-plate-open]').forEach(button=>button.onclick=()=>openPlateMap(button.dataset.plateOpen));updatePlateSelection();
}
function updatePlateSelection(){const n=state.plateSelection.size;$('plate-selection-count').textContent=n+' selected';$('select-plates').disabled=!state.plateMaps.length;$('select-plates').checked=!!state.plateMaps.length&&n===state.plateMaps.length;$('select-plates').indeterminate=n>0&&n<state.plateMaps.length;archiveIconButton($('archive-plates'),n,'plate maps');}
async function archivePlateMaps(){
  const ids=[...state.plateSelection],parts=state.fragments.filter(p=>ids.includes(p.plate_id));
  try{await Promise.all(parts.map(p=>persistInventoryRow(p.id)));const result=await api('/api/bin/archive',jsonBody({plate_ids:ids}));
    for(const p of parts){state.inventoryDrafts.delete(p.id);state.fragmentSelection.delete(p.id);}
    state.parts=state.parts.filter(p=>!ids.includes(p.plate_id));state.plateSelection.clear();await refresh();backboneChanged();await loadUploads();toast(`${result.count} plate map${result.count===1?'':'s'} archived`);
  }catch(error){toast(error.message);}
}
let fragmentInfoToken=0,fragmentSequenceToken=0,fragmentInfoRecord=null,fragmentSequenceRecord=null;
async function openInventoryFragment(part){
  if(!part)return;
  if(part.plate_id&&/^[A-P](?:[1-9]|1[0-9]|2[0-4])$/.test(part.well||'')){
    try{await persistInventoryRow(part.id);}catch(error){toast(error.message);}
    await openPlateMap(part.plate_id,part.well);return;
  }
  const token=++fragmentInfoToken,dialog=$('fragment-info-dialog'),host=$('fragment-info-body');
  fragmentInfoRecord=null;$('fragment-info-title').textContent=part.name;host.textContent='Loading…';if(!dialog.open)dialog.showModal();
  let warning='';try{await persistInventoryRow(part.id);}catch(error){warning='Showing saved values. '+error.message;}
  try{
    const record=await api('/api/fragments/'+part.id+'/details');if(token!==fragmentInfoToken||!dialog.open)return;
    fragmentInfoRecord=record;const inv=record.inventory;
    host.innerHTML=`${warning?messages([],[warning]):''}${FragmentSearch.stockBadge(record)}${record.custom_metadata?.linked_fragment_name?`<div class="small muted">Sequence linked to ${esc(record.custom_metadata.linked_fragment_name)}</div>`:''}<dl class="well-detail-grid"><dt>Location</dt><dd>${esc(record.location||'—')}</dd><dt>Plate</dt><dd>${esc(record.plate_id||'—')}</dd><dt>Well</dt><dd>${esc(record.well||'—')}</dd><dt>Length</dt><dd>${fmt(record.length,0)} bp</dd><dt>Construct</dt><dd>${fmt(record.physical_length,0)} bp</dd>${record.fusion_ends.map(end=>`<dt>${end.label}</dt><dd class="well-overhang">${plateEndHtml(end,record)}</dd>`).join('')}<dt>Yield</dt><dd>${inventoryQuantity(inv.yield_ng)} ng</dd><dt>Resuspend</dt><dd>${inventoryQuantity(inv.resuspension_ul)} µL</dd><dt>Stock</dt><dd>${inventoryQuantity(inv.stock_ng_ul)} ng/µL</dd><dt>Use</dt><dd>${inventoryQuantity(inv.input_volume_ul)} µL</dd></dl><button id="fragment-info-sequence" class="secondary compact" type="button" aria-haspopup="dialog">${inventoryIcon('view')} Sequence</button>${plateSitesHtml(record)}${record.notes?`<details><summary>Notes</summary><p>${esc(record.notes)}</p></details>`:''}`;
    $('fragment-info-sequence').onclick=()=>openFragmentSequence(record.id,record);
  }catch(error){if(token===fragmentInfoToken&&dialog.open)host.textContent=error.message;}
}
async function openFragmentSequence(id,record=null){
  const token=++fragmentSequenceToken,dialog=$('fragment-sequence-dialog');fragmentSequenceRecord=null;
  $('fragment-sequence-title').textContent='Sequence';$('fragment-sequence-text').value='';$('fragment-sequence-status').textContent='Loading…';$('fragment-sequence-kind').hidden=true;$('fragment-sequence-copy').disabled=true;
  if(!dialog.open)dialog.showModal();
  try{
    const part=record||await api('/api/fragments/'+id+'/details');if(token!==fragmentSequenceToken||!dialog.open)return;
    fragmentSequenceRecord=part;$('fragment-sequence-title').textContent=part.name;$('fragment-sequence-kind').value='sequence';$('fragment-sequence-kind').hidden=!part.construct_sequence||part.construct_sequence===part.sequence;
    renderFragmentSequence();
  }catch(error){if(token===fragmentSequenceToken&&dialog.open)$('fragment-sequence-status').textContent=error.message;}
}
function renderFragmentSequence(){
  const part=fragmentSequenceRecord;if(!part)return;
  const kind=$('fragment-sequence-kind').value,sequence=part[kind]||'';$('fragment-sequence-text').value=sequence;
  $('fragment-sequence-text').setAttribute('aria-label',kind==='construct_sequence'?'Construct sequence':'Fragment sequence');
  $('fragment-sequence-status').textContent=fmt(sequence.length,0)+' nt · 5′ → 3′';$('fragment-sequence-copy').disabled=!sequence;
}
async function copyFragmentSequence(){
  const sequence=$('fragment-sequence-text').value,token=fragmentSequenceToken;if(!sequence)return;
  const copied=()=>{if(token===fragmentSequenceToken&&$('fragment-sequence-text').value===sequence)$('fragment-sequence-status').textContent='Copied · '+fmt(sequence.length,0)+' nt';};
  $('fragment-sequence-text').focus();$('fragment-sequence-text').select();
  $('fragment-sequence-status').textContent='Sequence selected. Press Ctrl+C or ⌘C to copy.';
  // A direct user-gesture copy also works in embedded browsers where the
  // asynchronous clipboard API can wait indefinitely for focus or permission.
  try{if(typeof document==='object'&&document.execCommand?.('copy')){copied();return;}}catch{}
  try{await navigator.clipboard.writeText(sequence);copied();}catch{}
}
let plateViewToken=0;
async function openPlateMap(id,well=null){
  state.plateView=null;state.plateWell=well;state.plateWellSelection.clear();$('plate-select-wells').checked=false;$('plate-archive-status').hidden=true;updatePlateArchiveControls();$('plate-view-format').value='auto';$('plate-export-format').disabled=true;$('plate-export-format').value='';
  $('plate-view-title').textContent=id;$('plate-view-summary').textContent='Loading…';$('plate-grid').innerHTML='';$('plate-well-details').innerHTML='';
  if(!$('plate-viewer').open)$('plate-viewer').showModal();await loadPlateView(id);
}
async function loadPlateView(id=state.plateView?.plate_id){
  if(!id)return;const token=++plateViewToken;$('plate-grid').setAttribute('aria-busy','true');hidePlateTooltip();
  try{const result=await api('/api/plates/detail?'+new URLSearchParams({plate_id:id}));if(token!==plateViewToken||!$('plate-viewer').open)return;
    state.plateView=result;$('plate-export-format').disabled=false;$('plate-view-format').querySelector('[value="auto"]').textContent=`Auto (${result.format})`;
    $('plate-view-format').querySelector('[value="96"]').disabled=result.format===384;
    if(result.format===384&&$('plate-view-format').value==='96')$('plate-view-format').value='auto';renderPlateView();
  }catch(error){if(token===plateViewToken){$('plate-view-summary').textContent='';$('plate-well-details').innerHTML=messages([error.message]);}}
  finally{if(token===plateViewToken){$('plate-grid').setAttribute('aria-busy','false');}}
}
function renderPlateView(){
  const p=state.plateView;if(!p)return;hidePlateTooltip();
  const activeIds=new Set(p.archived_at?[]:p.fragments.filter(f=>!f.archived_at).map(f=>f.id));
  for(const id of state.plateWellSelection)if(!activeIds.has(id))state.plateWellSelection.delete(id);
  const format=$('plate-view-format').value==='auto'?p.format:Number($('plate-view-format').value),rows=format===384?16:8,cols=format===384?24:12;
  const parts=new Map(p.fragments.map(f=>[f.well,f]));
  if(!state.plateWell||state.plateWell.charCodeAt(0)-65>=rows||Number(state.plateWell.slice(1))>cols)state.plateWell=p.fragments[0]?.well||'A1';
  $('plate-view-title').textContent=plateLabel(p.plate_id);$('plate-view-title').title=p.plate_id;$('plate-view-summary').textContent=`${format} wells · ${p.occupied_wells} occupied${p.archived_at?' · Archived':''}`;$('plate-view-summary').title=p.layout_basis;
  const grid=$('plate-grid');grid.style.setProperty('--plate-cols',cols);grid.classList.toggle('labels-hidden',!$('plate-show-labels').checked);grid.classList.toggle('dense',format===384);grid.setAttribute('aria-label',`${format}-well plate ${p.plate_id}`);
  let html='<span class="plate-axis" aria-hidden="true"></span>'+Array.from({length:cols},(_,i)=>`<span class="plate-axis" aria-hidden="true">${i+1}</span>`).join('');
  for(let row=0;row<rows;row++){const letter=String.fromCharCode(65+row);html+=`<span class="plate-axis" aria-hidden="true">${letter}</span>`;for(let col=1;col<=cols;col++){
    const well=letter+col,part=parts.get(well),archived=!!(p.archived_at||part?.archived_at),selected=state.plateWell===well,checked=!!part&&state.plateWellSelection.has(part.id),pal=Overhangs.labels(...plateOverhangValues(part));
    html+=`<button type="button" class="plate-well ${part?'occupied':''} ${part&&archived?'archived':''} ${selected?'selected':''} ${checked?'archive-selected':''}" data-plate-well="${well}" data-plate-row="${row}" data-plate-col="${col}" tabindex="${selected?0:-1}" aria-pressed="${$('plate-select-wells').checked?checked:selected}" aria-describedby="plate-well-tooltip" aria-label="${well}${part?' '+esc(part.name)+(archived?', archived':''):', empty'}${pal.length?', palindromic overhang '+pal.join(' / '):''}${checked?', selected for archive':''}">${checked?'<span class="well-selection-mark" aria-hidden="true">✓</span>':''}${pal.length?'<span class="palindromic-indicator" aria-hidden="true">!</span>':''}<span class="well-coordinate">${well}</span>${part?`<span class="well-label">${esc(part.name)}</span>`:''}</button>`;
  }}grid.innerHTML=html;
  grid.querySelectorAll('[data-plate-well]').forEach(button=>{
    button.onclick=()=>{const part=state.plateView?.fragments.find(f=>f.well===button.dataset.plateWell);if($('plate-select-wells').checked&&!state.plateArchiveBusy&&part&&!part.archived_at&&!state.plateView.archived_at){state.plateWellSelection.has(part.id)?state.plateWellSelection.delete(part.id):state.plateWellSelection.add(part.id);state.plateWell=part.well;renderPlateView();$('plate-grid').querySelector(`[data-plate-well="${part.well}"]`)?.focus();}else selectPlateWell(button.dataset.plateWell);};button.onmouseenter=()=>showPlateTooltip(button);button.onmouseleave=hidePlateTooltip;button.onfocus=()=>showPlateTooltip(button);button.onblur=hidePlateTooltip;
    button.onkeydown=e=>{const delta={ArrowLeft:[0,-1],ArrowRight:[0,1],ArrowUp:[-1,0],ArrowDown:[1,0]}[e.key];if(!delta)return;e.preventDefault();const row=Math.min(rows-1,Math.max(0,Number(button.dataset.plateRow)+delta[0])),col=Math.min(cols,Math.max(1,Number(button.dataset.plateCol)+delta[1]));const next=String.fromCharCode(65+row)+col;selectPlateWell(next);grid.querySelector(`[data-plate-well="${next}"]`).focus();};
  });renderPlateWellDetails();updatePlateArchiveControls();
}
function selectPlateWell(well){
  state.plateWell=well;hidePlateTooltip();$('plate-grid').querySelectorAll('[data-plate-well]').forEach(button=>{const selected=button.dataset.plateWell===well;button.classList.toggle('selected',selected);const part=state.plateView?.fragments.find(f=>f.well===button.dataset.plateWell);button.setAttribute('aria-pressed',String($('plate-select-wells').checked?!!part&&state.plateWellSelection.has(part.id):selected));button.tabIndex=selected?0:-1;});renderPlateWellDetails();updatePlateArchiveControls();
}
function platePosition(start,end){return start===null||start===undefined?'Outside fragment':`${start+1}–${end}`;}
function plateOverhangValues(part){return [...(part?.fusion_ends||[]).map(end=>end.overhang),...(part?.sites||[]).map(site=>site.overhang)];}
function plateEndHtml(end,part){
  return `${overhangHtml(end.overhang)}<small>nt ${platePosition(end.start,end.end)}</small>${part.construct_offset?`<small>Construct ${platePosition(end.construct_start,end.construct_end)}</small>`:''}`;
}
function plateSitesHtml(part){
  if(!part.sites.length)return '<div class="small muted">No restriction sites detected</div>';
  return `<section class="well-sites" aria-label="Detected restriction sites"><h4>Sites</h4><div class="small muted">Fragment positions · 1-based · 5′→3′</div>${part.sites.map(site=>`<div class="well-site"><div class="well-site-heading"><b>${esc(site.enzyme)}</b><small>${site.strand===1?'Forward':'Reverse'}${site.location?' · '+esc(site.location):''}</small></div><small>Site ${platePosition(site.start,site.end)} · <code>${esc(site.motif)}</code></small><div class="well-site-overhang">${site.overhang?`${overhangHtml(site.overhang)}<small>Overhang ${platePosition(site.overhang_start,site.overhang_end)}</small>`:'<small class="muted">Overhang outside fragment</small>'}</div>${part.construct_offset?`<small class="muted">Construct site ${platePosition(site.construct_start,site.construct_end)}${site.overhang?' · overhang '+platePosition(site.construct_overhang_start,site.construct_overhang_end):''}</small>`:''}</div>`).join('')}</section>`;
}
function renderPlateWellDetails(){
  const plate=state.plateView,well=state.plateWell,part=plate?.fragments.find(f=>f.well===well),target=$('plate-well-details');
  if(!part){target.innerHTML=`<h3>${esc(well)}</h3><span class="small muted">Empty well</span>`;return;}
  const inv=part.inventory,archived=plate.archived_at||part.archived_at;
  target.innerHTML=`<div class="panel-heading"><h3>${esc(well)}</h3><div class="well-detail-actions"><span class="badge ${archived?'neutral':''}">${archived?'Archived':'Active'}</span>${!archived?`<button class="icon-button archive-button" type="button" data-plate-archive-well="${part.id}" aria-label="Archive well ${esc(well)}" title="Archive well">${inventoryIcon('trash')}</button>`:''}</div></div><b class="well-detail-name">${esc(part.name)}</b><div class="small muted">${esc(plateLabel(plate.plate_id))}</div>${part.detected_enzymes.length?`<div class="well-enzyme-flags">${part.detected_enzymes.map(enzyme=>`<span class="badge neutral">${esc(enzyme)}</span>`).join('')}</div>`:''}<dl class="well-detail-grid"><dt>Length</dt><dd>${fmt(part.length,0)} bp</dd><dt>Construct</dt><dd>${fmt(part.physical_length,0)} bp</dd>${part.fusion_ends.map(end=>`<dt>${end.label}</dt><dd class="well-overhang">${plateEndHtml(end,part)}</dd>`).join('')}</dl>${part.adapter_enzyme?`<div class="small muted">Adapters · ${esc(part.adapter_enzyme)}</div>`:''}${plateSitesHtml(part)}<button class="secondary compact" type="button" data-well-sequence="${part.id}" aria-haspopup="dialog">${inventoryIcon('view')} Sequence</button><details class="well-stock-details"><summary>Stock</summary><dl class="well-detail-grid"><dt>Yield</dt><dd>${inventoryQuantity(inv.yield_ng)} ng</dd><dt>Resuspend</dt><dd>${inventoryQuantity(inv.resuspension_ul)} µL</dd><dt>Stock</dt><dd>${inventoryQuantity(inv.stock_ng_ul)} ng/µL</dd><dt>Use</dt><dd>${inventoryQuantity(inv.input_volume_ul)} µL</dd><dt>Stock basis</dt><dd>${inv.saved?'Saved':'Planned'}</dd></dl>${inv.warnings?.length?messages([],inv.warnings):''}</details>${part.notes?`<details class="well-notes"><summary>Notes</summary><p>${esc(part.notes)}</p></details>`:''}`;
  target.querySelector('[data-well-sequence]').onclick=()=>openFragmentSequence(part.id);
  const archive=target.querySelector('[data-plate-archive-well]');if(archive){archive.disabled=state.plateArchiveBusy||!canArchivePlate();archive.onclick=()=>archiveFromPlate([part.id]);}
}
function canArchivePlate(){return window.JunctionAccount?.allowed('can_archive')!==false;}
function updatePlateArchiveControls(){
  const p=state.plateView,active=p&&!p.archived_at?p.fragments.filter(f=>!f.archived_at):[],count=state.plateWellSelection.size,busy=state.plateArchiveBusy;
  $('plate-well-selection-count').textContent=count+' selected';
  archiveIconButton($('plate-archive-wells'),count,'wells');$('plate-archive-wells').disabled=busy||!count||!canArchivePlate();
  $('plate-archive-map').innerHTML=inventoryIcon('trash');$('plate-archive-map').disabled=busy||!p||!!p.archived_at||!canArchivePlate();
  $('plate-wells-all').innerHTML=inventoryIcon('selectAll');$('plate-wells-all').disabled=busy||!active.length;
  $('plate-wells-clear').innerHTML=inventoryIcon('clear');$('plate-wells-clear').disabled=busy||!count;
  $('plate-select-wells').disabled=busy||!active.length;
  $('plate-well-details').querySelectorAll('[data-plate-archive-well]').forEach(button=>button.disabled=busy||!canArchivePlate());
}
async function archiveFromPlate(fragmentIds=[],wholePlate=false){
  const plate=state.plateView;if(!plate||plate.archived_at||state.plateArchiveBusy||!canArchivePlate())return;
  const parts=plate.fragments.filter(f=>!f.archived_at&&(wholePlate||fragmentIds.includes(f.id))),ids=parts.map(f=>f.id),plateId=plate.plate_id;
  if(!wholePlate&&!ids.length)return;
  const report=(message,error=false)=>{$('plate-archive-status').textContent=message;$('plate-archive-status').hidden=false;$('plate-archive-status').classList.toggle('reaction-warning',error);};
  state.plateArchiveBusy=true;hidePlateTooltip();updatePlateArchiveControls();report('Archiving…');
  try{
    await Promise.all(ids.map(persistInventoryRow));
    if(state.plateView?.plate_id!==plateId||!$('plate-viewer').open)return;
    const result=await api('/api/bin/archive',jsonBody(wholePlate?{plate_ids:[plateId]}:{fragment_ids:ids}));
    for(const id of ids){state.inventoryDrafts.delete(id);state.fragmentSelection.delete(id);state.plateWellSelection.delete(id);}
    state.parts=state.parts.filter(p=>!ids.includes(p.id));if(wholePlate)state.plateSelection.delete(plateId);
    const message=wholePlate?'Plate archived':`${result.count} well${result.count===1?'':'s'} archived`;
    if(state.plateView?.plate_id===plateId&&$('plate-viewer').open){
      const stamp=new Date().toISOString();if(!wholePlate)for(const part of state.plateView.fragments)if(ids.includes(part.id))part.archived_at=stamp;
      if(wholePlate)state.plateView.archived_at=stamp;renderPlateView();report(message);
      await loadPlateView(plateId);
    }
    await refresh();backboneChanged();await Promise.all([loadInventory(),loadUploads()]);if($('bin').classList.contains('active'))await loadBin();toast(message);
  }catch(error){if(state.plateView?.plate_id===plateId&&$('plate-viewer').open)report(error.message,true);else toast(error.message);}
  finally{state.plateArchiveBusy=false;updatePlateArchiveControls();}
}
function hidePlateTooltip(){$('plate-well-tooltip').classList.add('hidden');}
function showPlateTooltip(button){
  const p=state.plateView,f=p?.fragments.find(part=>part.well===button.dataset.plateWell),tip=$('plate-well-tooltip');if(!p)return;
  tip.innerHTML=`<b>${esc(button.dataset.plateWell)}${f?' · '+esc(f.name):''}</b>${f?`<div>${fmt(f.length,0)} bp · ${inventoryQuantity(f.inventory.stock_ng_ul)} ng/µL</div><div>${inventoryQuantity(f.inventory.resuspension_ul)} µL resuspend${p.archived_at||f.archived_at?' · Archived':''}</div><div>${esc(f.detected_enzymes.join(' · ')||'No restriction sites')}</div>${f.fusion_ends.map(end=>`<div>${end.label} ${overhangHtml(end.overhang)} · nt ${platePosition(end.start,end.end)}</div>`).join('')}${Overhangs.labels(...plateOverhangValues(f)).map(value=>`<div>Palindromic · ${overhangHtml(value)}</div>`).join('')}`:'<div>Empty well</div>'}`;
  tip.classList.remove('hidden');const rect=button.getBoundingClientRect(),box=tip.getBoundingClientRect();tip.style.left=Math.max(12,Math.min(innerWidth-box.width-12,rect.left))+'px';tip.style.top=(rect.bottom+box.height+12<innerHeight?rect.bottom+7:Math.max(12,rect.top-box.height-7))+'px';
}

function readUploadRules(){
  try{const saved=window.JunctionSandbox?.preferences?.uploadRuleOverrides||{};return Object.fromEntries(Object.entries(saved).filter(([key,value])=>['backbone_pmol','insert_ratio','preferred_resuspension_ul','max_resuspension_ul','min_input_volume_ul','max_input_volume_ul'].includes(key)&&Number.isFinite(value)));}catch{return {};}
}
function uploadRules(){return{...state.rules,...state.uploadRuleOverrides};}
function updateUploadRuleLabels(){
  const rules=uploadRules();
  $('upload-rule-molar').textContent=`DNA ${fmt(rules.backbone_pmol,4)} pmol`;
  $('upload-rule-ratio').textContent=`Ratio ${fmt(rules.insert_ratio)}:1`;
  $('upload-rule-target').textContent=`Target ${fmt(rules.preferred_resuspension_ul)} µL`;
  $('upload-rule-inputs').textContent=`Inputs ${fmt(rules.min_input_volume_ul)}–${fmt(rules.max_input_volume_ul)} µL`;
  $('upload-rule-resuspension').textContent=`Resuspension ≤${fmt(rules.max_resuspension_ul)} µL`;
}
function uploadRuleParams(){return new URLSearchParams({...uploadRules(),no_backbone:'true',resuspension_mode:'constrained',apply_import_rules:'true'});}
const plateUploads=JunctionUploadQueue.create({extensions:['csv','tsv','xlsx'],changed:renderPlateUploads});
const plasmidUploads=JunctionUploadQueue.create({extensions:['gb','gbk','genbank','fa','fasta','fna'],changed:renderPlasmidUploads});
function renderUploadFiles(queue,kind){
  const count=queue.jobs.length,done=queue.jobs.filter(job=>job.status==='Imported').length;
  $(kind+'-upload-count').textContent=count?`${count} files · ${done} imported`:'';
  $(kind+'-upload-clear').disabled=!count||queue.running;
  $(kind+'-upload-files').innerHTML=queue.jobs.map(job=>`<div class="upload-file-row"><span class="upload-file-name">${esc(job.file.name)}<small>${fmt(job.file.size/1024,1)} KB</small>${job.error?`<small class="upload-file-error">${esc(job.error)}</small>`:''}</span><span class="upload-file-status ${job.status.toLowerCase()}">${job.status==='Imported'?'✓ ':''}${job.status}</span><button type="button" class="icon-button" data-remove-upload="${job.id}" aria-label="Remove ${esc(job.file.name)}" ${queue.running?'disabled':''}>${inventoryIcon('close')}</button></div>`).join('');
  $(kind+'-upload-files').querySelectorAll('[data-remove-upload]').forEach(button=>button.onclick=()=>queue.remove(Number(button.dataset.removeUpload)));
}
function renderPlateUploads(){
  renderUploadFiles(plateUploads,'plate');
  const waiting=plateUploads.jobs.filter(job=>!job.invalid&&job.status!=='Imported');
  const signature=uploadRuleParams().toString();
  $('preview-upload').disabled=plateUploads.running||!waiting.length;
  $('commit-upload').disabled=plateUploads.running||!waiting.some(job=>job.status==='Ready'&&job.signature===signature);
  document.querySelectorAll('[data-upload-rule]').forEach(button=>button.disabled=plateUploads.running);
  const completed=plateUploads.jobs.filter(job=>job.status==='Imported');
  state.uploadPlan={rows:completed.flatMap(job=>job.result?.resuspension?.rows||[])};
  state.uploadParams=completed.length?new URLSearchParams(completed[0].signature):null;
  $('upload-resuspension-download').classList.toggle('hidden',!completed.length||plateUploads.running);
  $('upload-preview').innerHTML=plateUploads.jobs.filter(job=>job.result).map(job=>{
    const result=job.result,rows=result.resuspension?.rows||[];
    return `<details class="upload-result"><summary>${esc(job.file.name)} · ${result.count} ${job.status==='Imported'?'imported':'fragments'} · ${result.unchanged||0} unchanged</summary><div class="table-scroll"><table><thead><tr><th>Fragment</th><th>Plate / well</th><th>Target ng/µL</th><th>Resuspend µL</th><th>Use µL</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${esc(row.name)}${row.warnings?.length?`<small class="reaction-warning">${esc(row.warnings.join(' '))}</small>`:''}</td><td>${esc(plateLabel(row.plate_id))} / ${esc(row.well)}</td><td>${inventoryQuantity(row.target_ng_ul)}</td><td>${inventoryQuantity(row.resuspension_ul)}</td><td>${inventoryQuantity(row.input_volume_ul)}</td></tr>`).join('')}</tbody></table></div></details>`;
  }).join('');
}
function renderPlasmidUploads(){
  renderUploadFiles(plasmidUploads,'plasmid');
  $('import-plasmid').disabled=plasmidUploads.running||!plasmidUploads.jobs.some(job=>!job.invalid&&job.status!=='Imported');
  document.querySelectorAll('[data-upload-topology],#upload-backbone-toggle').forEach(button=>button.disabled=plasmidUploads.running);
  $('plasmid-upload-result').innerHTML=plasmidUploads.jobs.filter(job=>job.result).map(job=>`<div class="notice">${esc(job.file.name)} · ${job.result.count} imported · ${esc(job.result.names.join(', '))}</div>`).join('');
}
function clearPlatePreview(){plateUploads.invalidate();}
async function plateUpload(preview){
  if(plateUploads.running)return;
  const signature=uploadRuleParams().toString();
  if(!preview){
    // Never commit a file that has not been previewed with the current settings.
    if(plateUploads.jobs.some(job=>!job.invalid&&!['Imported','Error'].includes(job.status)&&(job.status!=='Ready'||job.signature!==signature))){await plateUpload(true);return;}
  }
  const wasImported=plateUploads.jobs.filter(job=>job.status==='Imported').length;
  busy(preview?'Previewing plate maps…':'Importing plate maps…');
  try{
    await plateUploads.run({preview,signature,eligible:job=>preview||(job.status==='Ready'&&job.signature===signature),request:async(file,job)=>{
      if(!preview&&(job.status!=='Importing'||job.signature!==signature))throw Error('Preview this file before importing');
      const params=new URLSearchParams(signature);params.set('preview',String(preview));
      const fd=new FormData();fd.append('file',file);
      return api('/api/uploads/plate?'+params,{method:'POST',body:fd});
    }});
    if(plateUploads.jobs.filter(job=>job.status==='Imported').length>wasImported){await refresh();await loadUploads();}
  }catch(error){toast(error.message);}finally{busy('');}
}
async function importPlasmids(){
  if(plasmidUploads.running)return;
  const params=new URLSearchParams({topology:$('upload-topology').value,backbone_template:$('upload-backbone').checked});
  const wasImported=plasmidUploads.jobs.filter(job=>job.status==='Imported').length;
  busy('Importing plasmids…');
  try{
    await plasmidUploads.run({request:file=>{const fd=new FormData();fd.append('file',file);return api('/api/uploads/plasmid?'+params,{method:'POST',body:fd});}});
    if(plasmidUploads.jobs.filter(job=>job.status==='Imported').length>wasImported){await refresh();renderPlasmidLibraries();}
  }catch(error){toast(error.message);}finally{busy('');}
}
function initializeUploads(){
  for(const[kind,queue]of [['plate',plateUploads],['plasmid',plasmidUploads]]){
    JunctionUploadQueue.bindDrop($(kind+'-drop-zone'),$(kind+'-upload'),files=>queue.add(files));
    $(kind+'-upload-clear').onclick=()=>queue.clear();
  }
  $('preview-upload').onclick=()=>plateUpload(true);$('commit-upload').onclick=()=>plateUpload(false);
  $('import-plasmid').onclick=importPlasmids;
  renderPlateUploads();renderPlasmidUploads();
}

// Files remain in this tab; comparisons are read-only and do not import inventory.
const compareJobs=[],compareSelection=new Set();let compareNextId=1,compareActiveId=null,compareWorker=false,compareRevision=0,compareDiscovery=0;
const compareFileView={search:'',filter:'all',sort:null,direction:1};
function visibleCompareJobs(){return CompareFiles.select(compareJobs,compareFileView,compareSelection);}
function updateCompareSortHeaders(){
  document.querySelectorAll('[data-compare-sort]').forEach(button=>{const active=button.dataset.compareSort===compareFileView.sort;button.dataset.direction=active?(compareFileView.direction===1?'ascending':'descending'):'';button.closest('th').setAttribute('aria-sort',button.closest('th').querySelector(`[data-compare-sort="${compareFileView.sort}"]`)?(compareFileView.direction===1?'ascending':'descending'):'none');});
}
function compareRecords(job){return job?.result?.records|| (job?.result?[job.result]:[]);}
function comparisonIdentityHtml(match){
  const hue=CompareVisuals.identityHue(match),value=CompareVisuals.percent(match);
  return `<span class="compare-identity${hue===null?' is-unknown':''}" ${hue===null?'':`style="--identity-hue:${hue}"`} title="Identical bases / all alignment columns, including gaps" aria-label="Sequence identity ${value}"><strong>${value}</strong><small>identity</small></span>`;
}
function comparisonDetailsHtml(job){
  if(job.status!=='Done')return `<div class="compare-inline-body"><span class="${job.error?'reaction-warning':'muted'}">${esc(job.error||job.status+'…')}</span></div>`;
  const records=compareRecords(job),r=records[job.recordIndex]||records[0];if(!r)return '';
  const tabs=records.length>1?`<div class="compare-record-tabs" role="tablist" aria-label="Records in ${esc(job.path)}">${records.map((record,index)=>`<button role="tab" aria-selected="${index===job.recordIndex}" data-compare-record="${index}" data-compare-job="${job.id}">${esc(record.query_name)}${exactMatchIcon(record.matches?.find(CompareVisuals.perfect))}${record.error?' !':''}</button>`).join('')}</div>`:'';
  if(r.error)return `<div class="compare-inline-body">${tabs}${messages([r.error])}</div>`;
  const matches=r.matches||[],d=r.enzyme_detection||{},modes=d.compatible_assembly_modes||[],detected=['BsaI','BsmBI'].filter(e=>d.site_counts?.[e]).map(e=>`${e}: ${d.site_counts[e]}`).join(' · ');
  return `<div class="compare-inline-body">${tabs}<div class="compare-inline-heading"><div><h3>Plasmids & assemblies <span class="muted small">(${matches.length})</span></h3><span class="small muted">${esc(r.query_name)} · ${fmt(r.query_length,0)} bp · ${r.query_circular?'Circular':'Linear'}${modes.length?' · '+esc(modes.join(' / ')):''}</span></div><button class="text-button" data-queue-fragments="${job.id}" aria-haspopup="dialog">Fragment matches (${r.fragment_matches?.length||0})</button></div><div class="compare-inline-matches">${matches.length?matches.map((match,index)=>`<button class="compare-inline-candidate" data-queue-candidate="${job.id}" data-queue-candidate-index="${index}" data-queue-record="${job.recordIndex}" aria-haspopup="dialog" aria-controls="compare-detail-dialog" title="${esc((match.aliases||[]).map(a=>a.source+': '+a.name).join(' · '))}"><span class="compare-inline-name"><b>${esc(match.name)}${exactMatchIcon(match)}</b><small>${esc(match.source||'Library assembly')} · ${fmt(match.reference_length,0)} bp${match.assembly_enzymes?.length?' · '+esc(match.assembly_enzymes.join(' / ')):''}</small></span>${comparisonIdentityHtml(match)}</button>`).join(''):'<span class="small muted">No assembly candidates</span>'}</div><details class="compare-search-details"><summary class="small muted">Search details</summary><p class="small muted">${esc(r.note||'')}</p>${detected?`<p class="small muted">Sites · ${esc(detected)}</p>`:''}<pre class="sequence-view">${esc(JSON.stringify({sources:r.source_counts,candidates:r.candidate_count,inferred:r.inferred_count,assembly_search:r.search,fragment_search:r.fragment_search},null,2))}</pre></details></div>`;
}
function comparisonQueue(){
  window.JunctionSandbox?.schedule();
  $('compare-queue').classList.toggle('hidden',!compareJobs.length&&!compareDiscovery);
  const visible=visibleCompareJobs();
  $('compare-count').textContent=compareJobs.length?(visible.length===compareJobs.length?`(${compareJobs.length})`:`(${visible.length} / ${compareJobs.length})`):'';
  updateCompareSortHeaders();
  const counts=Object.fromEntries(['Queued','Comparing','Done','Error','Skipped'].map(s=>[s,compareJobs.filter(j=>j.status===s).length]));
  $('compare-queue-status').textContent=[compareDiscovery?'Finding files…':'',...Object.entries(counts).filter(([,n])=>n).map(([s,n])=>`${n} ${s.toLowerCase()}`)].filter(Boolean).join(' · ');
  $('compare-queue-body').innerHTML=visible.map(job=>{
    const records=compareRecords(job),record=records[job.recordIndex]||records[0],best=record?.matches?.[0];
    return `<tr class="${job.expanded?'expanded':''}" data-compare-row="${job.id}" tabindex="0" aria-label="${job.expanded?'Collapse':'Expand'} ${esc(job.path)}"><td><input type="checkbox" data-compare-select="${job.id}" aria-label="Select ${esc(job.path)} for export" ${job.status!=='Done'?'disabled':''} ${compareSelection.has(job.id)?'checked':''}></td><td><button class="compare-file-select" data-compare-open="${job.id}" aria-expanded="${!!job.expanded}" aria-controls="compare-details-${job.id}" title="${esc(job.path)}"><span class="compare-row-chevron" aria-hidden="true">${inventoryIcon('next')}</span><span class="compare-file-name">${esc(job.path)}</span>${CompareVisuals.filePerfect(job)?exactMatchIcon(records[0]?.matches?.find(CompareVisuals.perfect)):''}</button>${records.length>1?`<small>${records.length} records · ${records.filter(r=>!r.error&&r.matches?.some(CompareVisuals.perfect)).length} exact</small>`:''}</td><td><span class="compare-job-status ${job.status.toLowerCase()}" title="${esc(job.error||'')}">${job.status}</span></td><td><span class="compare-closest-name" title="${esc(best?.name||job.error||'')}">${esc(best?.name||job.error||'—')}</span>${best?comparisonIdentityHtml(best):''}</td><td>${job.status==='Done'&&record&&!record.error?`<button class="text-button" data-queue-fragments="${job.id}" aria-label="View fragment matches for ${esc(record.query_name)}" aria-haspopup="dialog">${record.fragment_matches?.length||0}</button>`:'—'}</td><td><div class="button-row">${['Error','Done'].includes(job.status)?`<button class="icon-button" data-compare-retry="${job.id}" aria-label="Recompare ${esc(job.path)}" title="Recompare">${inventoryIcon('reset')}</button>`:''}<button class="icon-button compare-remove" data-compare-remove="${job.id}" aria-label="Remove ${esc(job.path)}">${inventoryIcon('close')}</button></div></td></tr><tr id="compare-details-${job.id}" class="compare-detail-row${job.expanded?'':' hidden'}"><td colspan="6">${job.expanded?comparisonDetailsHtml(job):''}</td></tr>`;
  }).join('')||(compareJobs.length?'<tr><td colspan="6" class="compare-no-files">No matching files</td></tr>':'');
  $('compare-queue-body').querySelectorAll('[data-compare-select]').forEach(input=>input.onchange=()=>{const id=Number(input.dataset.compareSelect);input.checked?compareSelection.add(id):compareSelection.delete(id);if(compareFileView.filter==='selected')comparisonQueue();else updateCompareSelection();});
  const toggleFile=id=>{const job=compareJobs.find(j=>j.id===id);if(!job)return;compareActiveId=id;job.expanded=!job.expanded;comparisonQueue();};
  $('compare-queue-body').querySelectorAll('[data-compare-row]').forEach(row=>{
    row.onclick=event=>{if(event.target.closest('button,input,a,select,label'))return;toggleFile(Number(row.dataset.compareRow));};
    row.onkeydown=event=>{if(event.target!==row||!['Enter',' '].includes(event.key))return;event.preventDefault();const id=Number(row.dataset.compareRow);toggleFile(id);$('compare-queue-body').querySelector(`[data-compare-open="${id}"]`)?.focus({preventScroll:true});};
  });
  $('compare-queue-body').querySelectorAll('[data-compare-open]').forEach(button=>button.onclick=()=>{const id=Number(button.dataset.compareOpen);toggleFile(id);$('compare-queue-body').querySelector(`[data-compare-open="${id}"]`)?.focus({preventScroll:true});});
  $('compare-queue-body').querySelectorAll('[data-compare-record]').forEach(button=>button.onclick=()=>{const job=compareJobs.find(j=>j.id===Number(button.dataset.compareJob));job.recordIndex=Number(button.dataset.compareRecord);job.candidateIndex=0;compareActiveId=job.id;comparisonQueue();$('compare-queue-body').querySelector(`[data-compare-job="${job.id}"][data-compare-record="${job.recordIndex}"]`)?.focus({preventScroll:true});});
  $('compare-queue-body').querySelectorAll('[data-queue-candidate]').forEach(button=>button.onclick=()=>{const id=Number(button.dataset.queueCandidate),job=compareJobs.find(j=>j.id===id);if(!job)return;compareActiveId=id;job.recordIndex=Number(button.dataset.queueRecord);openComparisonPopup(id,Number(button.dataset.queueCandidateIndex));});
  $('compare-queue-body').querySelectorAll('[data-queue-fragments]').forEach(button=>button.onclick=()=>{const job=compareJobs.find(j=>j.id===Number(button.dataset.queueFragments));if(!job)return;compareActiveId=job.id;openComparisonPopup(job.id,job.candidateIndex||0,'fragments');});
  $('compare-queue-body').querySelectorAll('[data-compare-remove]').forEach(b=>b.onclick=async()=>{const i=compareJobs.findIndex(j=>j.id===Number(b.dataset.compareRemove));try{if(compareJobs[i]?.sandboxId)await api('/api/workspace/comparisons/'+compareJobs[i].sandboxId,{method:'DELETE'});}catch(error){toast(error.message);return;}if(comparisonPopup?.jobId===compareJobs[i]?.id)$('compare-detail-dialog').close();compareJobs.splice(i,1);if(!compareJobs.some(j=>j.id===compareActiveId))compareActiveId=compareJobs[0]?.id??null;comparisonQueue();});
  $('compare-queue-body').querySelectorAll('[data-compare-retry]').forEach(b=>b.onclick=()=>{const job=compareJobs.find(j=>j.id===Number(b.dataset.compareRetry));job.status='Queued';job.error='';comparisonQueue();runCompareQueue();});
  updateCompareSelection();
}
function updateCompareSelection(){
  const done=compareJobs.filter(job=>job.status==='Done'),valid=new Set(done.map(job=>job.id));
  for(const id of compareSelection)if(!valid.has(id))compareSelection.delete(id);
  const visible=visibleCompareJobs().filter(job=>job.status==='Done'),visibleSelected=visible.filter(job=>compareSelection.has(job.id)).length;
  const all=$('compare-select-all');all.disabled=!visible.length;all.checked=!!visible.length&&visibleSelected===visible.length;all.indeterminate=visibleSelected>0&&!all.checked;
  const exactCount=done.reduce((n,job)=>n+compareRecords(job).filter(record=>!record.error&&record.matches?.some(CompareVisuals.perfect)).length,0);
  $('compare-export-exact').disabled=!exactCount;$('compare-export-exact').textContent=`100% matches (${exactCount})`;
  $('compare-export-selected').disabled=!compareSelection.size;$('compare-export-selected').textContent=`Selected (${compareSelection.size})`;
  $('compare-export-toggle').disabled=!done.length;$('compare-selected-count').textContent=compareSelection.size?`${compareSelection.size} selected${compareSelection.size>visibleSelected?' · '+(compareSelection.size-visibleSelected)+' hidden':''}`:'';
}
function closeCompareExport(restoreFocus=false){$('compare-export-menu').classList.add('hidden');$('compare-export-toggle').setAttribute('aria-expanded','false');if(restoreFocus)$('compare-export-toggle').focus();}
async function exportComparisonResults(scope){
  closeCompareExport();const records=CompareVisuals.exportRecords(compareJobs,compareSelection,scope);
  if(!records.length){toast('No results selected');return;}
  await fileDownload('/api/compare/export',{scope,records},'comparison-'+scope+'.xlsx');
}
function addCompareFile(file,path=file.webkitRelativePath||file.name){
  if(path.split('/').some(p=>p.startsWith('.')))return;
  const key=[path,file.size,file.lastModified].join('|');if(compareJobs.some(j=>j.key===key))return;
  if(compareJobs.length>=200){toast('Queue limit: 200 files');return;}
  const supported=/\.(gb|gbk|genbank|fa|fasta|fna|fas|txt)$/i.test(file.name),tooLarge=file.size>10*1024*1024;
  const job={id:compareNextId++,key,file,path,status:!supported?'Skipped':tooLarge?'Error':'Queued',error:!supported?'Unsupported file type':tooLarge?'File exceeds 10 MiB':'',recordIndex:0,candidateIndex:0};
  compareJobs.push(job);if(compareActiveId===null)compareActiveId=job.id;
  comparisonQueue();if(job.id===compareActiveId)renderComparison();runCompareQueue();
}
async function runCompareQueue(){
  if(compareWorker)return;compareWorker=true;
  try{let job;while((job=compareJobs.find(j=>j.status==='Queued'))){
    const revision=compareRevision,enzyme=$('compare-enzyme').value;job.status='Comparing';job.error='';comparisonQueue();if(job.id===compareActiveId)renderComparison();
    try{
      const form=new FormData();form.append('file',job.file);
      const result=await api('/api/compare?enzyme='+encodeURIComponent(enzyme)+'&infer=true'+(job.sandboxId?'&sandbox_id='+job.sandboxId:''),{method:'POST',body:form});
      job.sandboxId=result.sandbox_id||job.sandboxId;
      if(!compareJobs.includes(job)){if(job.sandboxId)api('/api/workspace/comparisons/'+job.sandboxId,{method:'DELETE'}).catch(error=>toast(error.message));continue;}
      if(revision!==compareRevision){job.status='Queued';continue;}
      job.result=result;job.status='Done';job.recordIndex=0;job.candidateIndex=0;
    }catch(error){job.sandboxId=error.sandboxId||job.sandboxId;if(!compareJobs.includes(job)){if(job.sandboxId)api('/api/workspace/comparisons/'+job.sandboxId,{method:'DELETE'}).catch(e=>toast(e.message));continue;}if(revision!==compareRevision){job.status='Queued';continue;}job.error=error.message;job.status='Error';}
    comparisonQueue();if(job.id===compareActiveId)renderComparison();
  }}finally{compareWorker=false;comparisonQueue();}
}
function exactMatchIcon(match){return CompareVisuals.perfect(match)?`<span class="exact-match-tick" role="img" aria-label="100% exact match" title="100% exact match">${inventoryIcon('check')}</span>`:'';}
// Results live inside expandable file rows; retained as a queue-update hook.
function renderComparison(){}
function fragmentMatchesHtml(r){
  const hits=r.fragment_matches||[];
  return `<div class="panel-heading"><h3>Fragment matches (${hits.length})</h3><span class="small muted">1-based query coordinates</span></div>${hits.length?`<div class="table-scroll"><table class="compare-fragment-table"><thead><tr><th>Fragment</th><th>Plate / well</th><th>Query span</th><th>Strand</th><th>Match</th><th>Identity</th><th>Coverage</th></tr></thead><tbody>${hits.map(h=>`<tr><td><b>${esc(h.name)}</b><small>${esc(h.representation)}${h.enzymes?.length?' · '+esc(h.enzymes.join(' / ')):''}</small></td><td>${esc(plateLabel(h.plate_id)||'—')} / ${esc(h.well||'—')}</td><td>${esc(h.query_spans.map(x=>spanLabel(...x)).join(', '))}${h.occurrences?.length>1?`<small title="${esc(h.occurrences.map(spans=>spans.map(x=>spanLabel(...x)).join(', ')).join('; '))}">${h.occurrences.length}${h.occurrences_capped?'+':''} locations</small>`:''}</td><td>${esc(h.strand)}</td><td><span class="badge ${h.exact?'':'warn'}" title="${h.short_match?'Short match; not unique source evidence':'Shared sequences may match multiple fragments'}">${exactMatchIcon(h)}${esc(h.status)}</span>${h.changes?.length?`<details class="fragment-differences"><summary>${h.changes.length} differences</summary><div class="small muted">Fragment coordinates follow the matched strand.</div>${h.changes.map(c=>`<div class="fragment-change change-${esc(c.type)}"><b>${esc(c.type)}</b> · fragment ${spanLabel(c.reference_start,c.reference_end)} · query ${esc((c.original_query_spans||[]).map(x=>spanLabel(...x)).join(', '))}<code>${esc((c.reference_bases||'∅').slice(0,120))} → ${esc((c.query_bases||'∅').slice(0,120))}</code></div>`).join('')}</details>`:''}</td><td>${CompareVisuals.percent(h)}</td><td>${fmt(h.coverage*100)}%</td></tr>`).join('')}</tbody></table></div>`:'<span class="small muted">No fragment matches found</span>'}<div class="small muted compare-limit">${r.fragment_search?.approximate_search_capped?'Approximate search capped. ':''}Shared matches may overlap. Unreported fragments are not proven absent.</div>`;
}
let comparisonPopup=null;
function popupComparison(){
  if(!comparisonPopup)return {};
  const job=compareJobs.find(j=>j.id===comparisonPopup.jobId),record=compareRecords(job)[comparisonPopup.recordIndex];
  return {job,record,match:record?.matches?.[comparisonPopup.candidateIndex]};
}
function openComparisonPopup(jobId,candidateIndex=0,tab='alignment'){
  const job=compareJobs.find(j=>j.id===jobId);if(!job||job.status!=='Done')return;
  const record=compareRecords(job)[job.recordIndex];if(!record||record.error)return;
  comparisonPopup={jobId,recordIndex:job.recordIndex,candidateIndex,tab,focus:document.activeElement};
  renderComparisonPopup();if(!$('compare-detail-dialog').open)$('compare-detail-dialog').showModal();
  selectComparisonTab(record.matches?.length?tab:'fragments');
}
function renderComparisonPopup(){
  const {record:r,match:m}=popupComparison();if(!r)return;
  $('compare-detail-title').innerHTML=`${exactMatchIcon(m)}${esc(m?.name||r.query_name)}`;
  $('compare-detail-summary').innerHTML=`<span>${esc(r.query_name)} · ${fmt(r.query_length,0)} bp${m?' → '+esc(m.name):''}</span>${m?comparisonIdentityHtml(m):''}`;
  $('compare-reference-select').innerHTML=(r.matches||[]).map((candidate,i)=>`<option value="${i}">${esc(candidate.name)} · ${CompareVisuals.percent(candidate)} identity</option>`).join('');
  $('compare-reference-select').value=String(comparisonPopup.candidateIndex);$('compare-reference-field').classList.toggle('hidden',!m);
  $('compare-fragments-panel').innerHTML=fragmentMatchesHtml(r);$('compare-alignment-panel').innerHTML='';
  if(m)renderAlignment(m);
  $('compare-alignment-tab').disabled=!m;
}
function selectComparisonTab(tab){
  hideDifferenceTooltip();
  if(!comparisonPopup||!['alignment','fragments'].includes(tab))return;comparisonPopup.tab=tab;
  document.querySelectorAll('[data-compare-detail-tab]').forEach(button=>{const active=button.dataset.compareDetailTab===tab;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;$(button.getAttribute('aria-controls')).classList.toggle('hidden',!active);});
}
async function droppedCompareEntry(entry,path=''){
  if(entry.isFile){const file=await new Promise((resolve,reject)=>entry.file(resolve,reject));addCompareFile(file,path+file.name);}
  else if(entry.isDirectory){const reader=entry.createReader();let batch;do{batch=await new Promise((resolve,reject)=>reader.readEntries(resolve,reject));for(const child of batch)await droppedCompareEntry(child,path+entry.name+'/');}while(batch.length);}
}
function initializeCompare(){
  $('compare-file-search').oninput=event=>{compareFileView.search=event.target.value;comparisonQueue();};
  $('compare-file-filter').onchange=event=>{compareFileView.filter=event.target.value;comparisonQueue();};
  document.querySelectorAll('[data-compare-sort]').forEach(button=>button.onclick=()=>{const key=button.dataset.compareSort;compareFileView.direction=compareFileView.sort===key?-compareFileView.direction:['identity','fragments'].includes(key)?-1:1;compareFileView.sort=key;comparisonQueue();});
  $('compare-select-all').onchange=event=>{CompareFiles.selectVisible(compareSelection,visibleCompareJobs(),event.target.checked);comparisonQueue();};
  $('compare-export-toggle').onclick=()=>{const menu=$('compare-export-menu'),open=menu.classList.contains('hidden');menu.classList.toggle('hidden',!open);$('compare-export-toggle').setAttribute('aria-expanded',String(open));if(open)menu.querySelector('button:not(:disabled)')?.focus();};
  $('compare-export-exact').onclick=()=>exportComparisonResults('exact');$('compare-export-selected').onclick=()=>exportComparisonResults('selected');
  document.addEventListener('click',event=>{if(!event.target.closest('.compare-export-controls'))closeCompareExport();});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!$('compare-export-menu').classList.contains('hidden')){event.preventDefault();closeCompareExport(true);}});
  $('compare-detail-back').onclick=$('compare-detail-close').onclick=()=>$('compare-detail-dialog').close();
  $('compare-detail-dialog').onclose=()=>{hideDifferenceTooltip();const focus=comparisonPopup?.focus,jobId=comparisonPopup?.jobId;comparisonPopup=null;(focus?.isConnected?focus:document.querySelector(`[data-compare-open="${jobId}"]`))?.focus({preventScroll:true});};
  document.querySelectorAll('[data-compare-detail-tab]').forEach(button=>{button.onclick=()=>selectComparisonTab(button.dataset.compareDetailTab);button.onkeydown=event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const tabs=[...document.querySelectorAll('[data-compare-detail-tab]')].filter(t=>!t.disabled);let index=tabs.indexOf(button);index=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowLeft'?-1:1)+tabs.length)%tabs.length;tabs[index].click();tabs[index].focus();};});
  $('compare-reference-select').onchange=()=>{if(!comparisonPopup)return;comparisonPopup.candidateIndex=Number($('compare-reference-select').value);const tab=comparisonPopup.tab;renderComparisonPopup();selectComparisonTab(tab);};
  $('compare-add-files').onclick=()=>$('compare-file').click();$('compare-add-folder').onclick=()=>$('compare-folder').click();
  for(const id of ['compare-file','compare-folder'])$(id).onchange=e=>{for(const file of e.target.files)addCompareFile(file);e.target.value='';};
  $('compare-clear').onclick=async()=>{try{await api('/api/workspace/comparisons',{method:'DELETE'});}catch(error){toast(error.message);return;}if(comparisonPopup)$('compare-detail-dialog').close();compareJobs.length=0;compareActiveId=null;compareFileView.search='';compareFileView.filter='all';$('compare-file-search').value='';$('compare-file-filter').value='all';comparisonQueue();renderComparison();};
  $('compare-enzyme').onchange=()=>{if(comparisonPopup)$('compare-detail-dialog').close();compareRevision++;for(const job of compareJobs){if(job.status!=='Skipped'){job.result=null;job.error='';if(job.status!=='Comparing')job.status='Queued';}}comparisonQueue();renderComparison();runCompareQueue();};
  const zone=$('compare-dropzone');let dragDepth=0;
  zone.onkeydown=e=>{if(e.target===zone&&(e.key==='Enter'||e.key===' ')){e.preventDefault();$('compare-file').click();}};
  zone.ondragenter=e=>{e.preventDefault();dragDepth++;zone.classList.add('dragover');};
  zone.ondragover=e=>{e.preventDefault();e.dataTransfer.dropEffect='copy';};
  zone.ondragleave=e=>{e.preventDefault();if(--dragDepth<=0){dragDepth=0;zone.classList.remove('dragover');}};
  zone.ondrop=async e=>{
    e.preventDefault();dragDepth=0;zone.classList.remove('dragover');
    // Read entries synchronously while the browser still exposes the drop data.
    const items=[...(e.dataTransfer.items||[])].filter(i=>i.kind==='file'),entries=items.map(i=>i.webkitGetAsEntry?.()).filter(Boolean),files=[...e.dataTransfer.files];
    compareDiscovery++;comparisonQueue();
    try{if(entries.length){for(const entry of entries)await droppedCompareEntry(entry);}else for(const file of files)addCompareFile(file);}
    catch(error){toast('Some dropped files could not be read: '+error.message);}
    finally{compareDiscovery--;comparisonQueue();}
  };
}
function renderAlignment(m){
  const target=$('compare-alignment-panel');let model;
  try{model=DifferenceViewer.build(m);}catch(error){target.innerHTML=messages([error.message]);return;}
  const selected=model.changes.length?0:null,size=60;
  comparisonPopup.differenceNavigator={model,selected,filter:'all',size,start:DifferenceViewer.startFor(model,selected===null?0:model.changes[selected].startColumn,size)};
  const paths=m.assembly_paths?.length?m.assembly_paths:m.parts?.length?[{parts:m.parts,assembly_enzymes:m.assembly_enzymes}]:[];
  const routes=paths.length?`<details class="compare-assembly-paths"><summary>Assembly fragments (${paths[0].parts.length})</summary>${paths.map(path=>`<p class="small"><b>${esc((path.assembly_enzymes||[]).join(' / ')||path.source||'Assembly')}</b><br>${path.parts.map((name,index)=>esc(name)+(path.part_orientations?.[index]===-1?' (RC)':'')).join(' → ')}</p>`).join('')}</details>`:'';
  target.innerHTML=`${routes}<div class="difference-navigator"><div class="panel-heading diff-heading"><h3>${m.exact?exactMatchIcon(m)+'Exact match':model.changes.length+' difference region'+(model.changes.length===1?'':'s')}</h3><span class="badge ${m.exact?'':'warn'}">${m.orientation==='-'?'Reverse complement':'Forward'} · rotation ${fmt(m.rotation,0)}</span></div>${m.warnings?.length?messages([],m.warnings):''}<div id="diff-filters" class="diff-filters" role="group" aria-label="Difference types">${['all',...Object.keys(DifferenceViewer.names)].map(type=>`<button class="diff-filter" data-diff-filter="${type}" aria-pressed="${type==='all'}">${type==='all'?'All':DifferenceViewer.names[type]+'s'} <span>${type==='all'?model.changes.length:model.changes.filter(c=>c.type===type).length}</span></button>`).join('')}</div><div class="diff-inspection-grid"><div class="diff-overview-column"><div id="diff-overview" class="diff-overview" aria-label="Reference features and difference positions"></div><div class="diff-navigation"><div class="diff-navigation-buttons"><button id="diff-previous" class="icon-button" aria-label="Previous difference" title="Previous difference">${inventoryIcon('previous')}</button><label class="sr-only" for="diff-choice">Selected difference</label><select id="diff-choice" aria-label="Selected difference"></select><button id="diff-next" class="icon-button" aria-label="Next difference" title="Next difference">${inventoryIcon('next')}</button></div><span id="diff-counter" class="small muted" role="status"></span><button id="diff-focus" class="text-button">Focus difference</button></div></div><div id="diff-selected-detail" class="diff-selected-detail" aria-live="polite"></div></div><div class="diff-window-controls"><div class="diff-window-buttons"><button id="diff-window-back" class="icon-button" aria-label="Previous sequence window" title="Previous sequence window">${inventoryIcon('previous')}</button><button id="diff-window-forward" class="icon-button" aria-label="Next sequence window" title="Next sequence window">${inventoryIcon('next')}</button></div><label>Zoom<select id="diff-window-size"><option value="60" selected>60 columns</option><option value="120">120 columns</option><option value="240">240 columns</option><option value="480">480 columns</option></select></label><form id="diff-goto-form"><label>Reference position<input id="diff-goto" type="number" min="1" max="${model.referenceLength}" value="1" step="1" required></label><button class="secondary compact" type="submit">Go</button></form><label class="diff-position-slider-label"><span class="sr-only">Alignment position</span><input id="diff-position-slider" aria-label="Alignment position" type="range" min="0" max="${Math.max(0,model.columns-1)}" value="0"></label></div><div class="diff-window-heading"><h4 id="diff-window-title" tabindex="-1">Sequence</h4><span class="small muted">Reference coordinates${model.orientation==='-'?' · query reverse complemented':''}</span></div><div id="diff-sequence-window" class="diff-sequence-window" tabindex="0" role="region" aria-label="Aligned sequence window"></div><details id="diff-full-list" class="diff-full-list"><summary>All differences (${model.changes.length})</summary><div id="diff-full-list-body" class="table-scroll"></div></details><div id="diff-hover-tooltip" class="diff-hover-tooltip hidden" role="tooltip"></div></div>`;
  target.onwheel=hideDifferenceTooltip;$('compare-detail-dialog').onscroll=scrollDifferenceTooltip;
  target.onkeydown=event=>{if(event.key==='Escape'&&!$('diff-hover-tooltip').classList.contains('hidden')){event.preventDefault();event.stopPropagation();hideDifferenceTooltip();}};
  target.querySelectorAll('[data-diff-filter]').forEach(button=>button.onclick=()=>{const nav=comparisonPopup.differenceNavigator;nav.filter=button.dataset.diffFilter;const choices=filteredDifferences(nav);if(!choices.some(c=>c.index===nav.selected))nav.selected=choices[0]?.index??null;if(nav.selected!==null)nav.start=DifferenceViewer.startFor(nav.model,nav.model.changes[nav.selected].startColumn,nav.size);updateDifferenceNavigator(true);});
  $('diff-choice').onchange=()=>selectDifference(Number($('diff-choice').value));
  const step=direction=>{const nav=comparisonPopup.differenceNavigator,choices=filteredDifferences(nav),index=choices.findIndex(c=>c.index===nav.selected);const next=choices[index+direction];if(next)selectDifference(next.index);};
  $('diff-previous').onclick=()=>step(-1);$('diff-next').onclick=()=>step(1);
  $('diff-focus').onclick=()=>{const nav=comparisonPopup.differenceNavigator,c=nav.model.changes[nav.selected];if(c){nav.start=DifferenceViewer.startFor(nav.model,(c.startColumn+c.endColumn-1)/2,nav.size);updateDifferenceNavigator();}};
  $('diff-window-size').onchange=()=>{const nav=comparisonPopup.differenceNavigator,center=nav.start+Math.min(nav.size,nav.model.columns)/2;nav.size=Number($('diff-window-size').value);nav.start=DifferenceViewer.startFor(nav.model,center,nav.size);updateDifferenceNavigator();};
  $('diff-position-slider').oninput=()=>{const nav=comparisonPopup.differenceNavigator;nav.start=DifferenceViewer.startFor(nav.model,Number($('diff-position-slider').value),nav.size);updateDifferenceNavigator();};
  const moveWindow=direction=>{const nav=comparisonPopup.differenceNavigator;nav.start=Math.max(0,Math.min(Math.max(0,nav.model.columns-nav.size),nav.start+direction*Math.max(1,Math.floor(nav.size/2))));updateDifferenceNavigator();};
  $('diff-window-back').onclick=()=>moveWindow(-1);$('diff-window-forward').onclick=()=>moveWindow(1);
  $('diff-goto-form').onsubmit=event=>{event.preventDefault();const input=$('diff-goto');if(!input.checkValidity()){input.reportValidity();return;}const nav=comparisonPopup.differenceNavigator;nav.start=DifferenceViewer.startFor(nav.model,DifferenceViewer.columnForReference(nav.model,Number(input.value)-1),nav.size);updateDifferenceNavigator();};
  $('diff-full-list').ontoggle=()=>{if($('diff-full-list').open)renderDifferenceList();};
  updateDifferenceNavigator(true);
}
function hideDifferenceTooltip(){
  $('diff-hover-tooltip')?.classList.add('hidden');
  $('compare-alignment-panel')?.querySelectorAll('.diff-hovered').forEach(node=>node.classList.remove('diff-hovered'));
}
function scrollDifferenceTooltip(){
  const active=document.activeElement,rect=active?.getBoundingClientRect();
  if(active?.matches('[data-diff-feature],[data-diff-affected],[data-diff-index],[data-diff-site]')&&rect.bottom>0&&rect.top<window.innerHeight)showDifferenceTooltip(active);
  else hideDifferenceTooltip();
}
function bindDifferenceHover(){
  const panel=$('compare-alignment-panel');
  panel.querySelectorAll('[data-diff-feature],[data-diff-affected],[data-diff-index],[data-diff-site],[data-diff-base]').forEach(node=>{
    node.onpointerenter=()=>showDifferenceTooltip(node);node.onfocus=()=>showDifferenceTooltip(node);
    node.onpointerleave=()=>{if(document.activeElement!==node)hideDifferenceTooltip();};node.onblur=hideDifferenceTooltip;
  });
}
function showDifferenceTooltip(node){
  const nav=comparisonPopup?.differenceNavigator,tooltip=$('diff-hover-tooltip');if(!nav||!tooltip)return;
  const d=node.dataset,side=d.diffSide||'reference';let type,index,selector;
  if(d.diffFeature!==undefined||d.diffAffected!==undefined){type='feature';index=Number(d.diffFeature??d.diffAffected);selector=`[data-diff-feature="${index}"],[data-diff-affected="${index}"]`;}
  else if(d.diffIndex!==undefined||d.diffChange!==undefined){type='change';index=Number(d.diffIndex??d.diffChange);selector=`[data-diff-index="${index}"],[data-diff-change="${index}"]`;}
  else if(d.diffSite!==undefined){type='site';index=Number(d.diffSite);selector=`[data-diff-site="${index}"][data-diff-side="${side}"]`;}
  else {type='base';index=Number(d.diffBase);selector=`[data-diff-base="${index}"]`;}
  const html=DifferenceViewer.hoverHtml(nav.model,type,index,side);if(!html)return;
  hideDifferenceTooltip();tooltip.innerHTML=html;tooltip.classList.remove('hidden');
  $('compare-alignment-panel').querySelectorAll(selector).forEach(target=>target.classList.add('diff-hovered'));
  const rect=node.getBoundingClientRect(),box=tooltip.getBoundingClientRect();
  const right=rect.right+10,left=rect.left-box.width-10;
  tooltip.style.left=Math.max(10,Math.min(right+box.width<window.innerWidth-10?right:left>=10?left:rect.left,window.innerWidth-box.width-10))+'px';
  tooltip.style.top=Math.max(10,Math.min(rect.top,window.innerHeight-box.height-10))+'px';
}
function focusDifferenceSite(side,index){
  const nav=comparisonPopup?.differenceNavigator,site=(side==='query'?nav?.model.querySites:nav?.model.refSites)?.[index];if(!site)return;
  const position=site.topCut??site.start,column=DifferenceViewer.siteColumn(nav.model,side,position);
  nav.start=DifferenceViewer.startFor(nav.model,column,nav.size);updateDifferenceNavigator();
}
function filteredDifferences(nav){return nav.model.changes.filter(c=>nav.filter==='all'||nav.filter===c.type);}
function selectDifference(index){
  const nav=comparisonPopup?.differenceNavigator,c=nav?.model.changes[index];if(!c)return;
  if(nav.filter!=='all'&&nav.filter!==c.type)nav.filter='all';nav.selected=index;
  nav.start=DifferenceViewer.startFor(nav.model,c.startColumn,nav.size);updateDifferenceNavigator(true);
}
function focusDifferenceFeature(index){
  const nav=comparisonPopup?.differenceNavigator,feature=nav?.model.features[index];if(!feature)return;
  if(feature.autoRestriction){focusDifferenceSite(feature._siteSide,feature._siteIndex);return;}
  nav.start=DifferenceViewer.startFor(nav.model,DifferenceViewer.columnForReference(nav.model,feature.start),nav.size);updateDifferenceNavigator();
}
function updateDifferenceNavigator(updateChoices=false){
  hideDifferenceTooltip();
  const nav=comparisonPopup?.differenceNavigator;if(!nav)return;
  const {model,selected,filter,size}=nav,range=DifferenceViewer.windowRange(model,nav.start,size),{start,end}=range;nav.start=start;
  const c=model.changes[selected],choices=filteredDifferences(nav),index=choices.findIndex(c=>c.index===selected);
  $('diff-overview').innerHTML=DifferenceViewer.overviewHtml(model,selected,filter,start,size);
  $('diff-overview').querySelectorAll('[data-diff-index]').forEach(button=>{button.onclick=()=>selectDifference(Number(button.dataset.diffIndex));button.onkeydown=event=>{if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();$(event.key==='ArrowLeft'?'diff-previous':'diff-next').click();$('diff-overview').querySelector(`[data-diff-index="${comparisonPopup.differenceNavigator.selected}"]`)?.focus({preventScroll:true});}};});
  $('diff-overview').querySelectorAll('[data-diff-feature]').forEach(button=>button.onclick=()=>focusDifferenceFeature(Number(button.dataset.diffFeature)));
  $('diff-overview').querySelectorAll('[data-diff-track]').forEach(track=>track.onclick=event=>{if(event.target.closest('button'))return;const rect=track.getBoundingClientRect(),position=Math.max(0,Math.min(model.referenceLength,(event.clientX-rect.left)/rect.width*model.referenceLength));nav.start=DifferenceViewer.startFor(model,DifferenceViewer.columnForReference(model,position),size);updateDifferenceNavigator();});
  $('diff-filters').querySelectorAll('[data-diff-filter]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.diffFilter===filter)));
  if(updateChoices){$('diff-choice').innerHTML=choices.length?choices.map(change=>`<option value="${change.index}">${esc(DifferenceViewer.label(change))}</option>`).join(''):'<option>No differences</option>';}
  $('diff-choice').value=selected===null?'':String(selected);$('diff-choice').disabled=!choices.length;
  $('diff-previous').disabled=index<=0;$('diff-next').disabled=index<0||index>=choices.length-1;$('diff-focus').disabled=!c;
  $('diff-counter').textContent=choices.length?`${index+1} / ${choices.length}`:'No differences';
  const features=DifferenceViewer.affected(model,c);
  const detailSignature=c?'event:'+c.index:'none:'+filter;
  if($('diff-selected-detail').dataset.signature!==detailSignature){$('diff-selected-detail').dataset.signature=detailSignature;
  $('diff-selected-detail').innerHTML=c?`<div class="diff-event-heading"><strong class="diff-kind-${c.type}">${DifferenceViewer.names[c.type]}</strong><span>Reference ${DifferenceViewer.span(c.reference_start,c.reference_end)}</span><span>Original query ${esc(DifferenceViewer.originalQueryLabel(model,c.query_start,c.query_end))}</span></div><div class="diff-event-bases"><div><small>Reference · ${c.reference_bases.length} bp</small><code class="change-${c.type}">${esc(c.reference_bases||'—')}</code></div><div><small>Query · ${c.query_bases.length} bp</small><code class="change-${c.type}">${esc(c.query_bases||'—')}</code></div></div>${features.length?`<div class="diff-affected-features"><small>Features</small>${features.map(f=>`<button class="diff-feature-chip${DifferenceViewer.enzymeFor(f)?' diff-enzyme-chip':''}" ${DifferenceViewer.enzymeFor(f)?`style="--re-color:${DifferenceViewer.enzymes[DifferenceViewer.enzymeFor(f)].color}"`:''} data-diff-affected="${model.features.indexOf(f)}" aria-describedby="diff-hover-tooltip">${esc(f.label||f.type)}</button>`).join('')}</div>`:'<div class="small muted">No annotated feature at this position</div>'}`:`<span class="small muted">${model.changes.length?'No differences of this type':'Identical aligned sequences'}</span>`;
  $('diff-selected-detail').querySelectorAll('[data-diff-affected]').forEach(button=>button.onclick=()=>focusDifferenceFeature(Number(button.dataset.diffAffected)));
  }
  $('diff-window-title').textContent=`Reference ${DifferenceViewer.span(model.refBefore[start],model.refBefore[end])}`;
  $('diff-sequence-window').innerHTML=DifferenceViewer.windowHtml(model,start,size,selected);
  const slider=$('diff-position-slider');slider.min=String(range.sliderMin);slider.max=String(range.sliderMax);slider.disabled=range.sliderMin===range.sliderMax;slider.value=String(range.sliderValue);
  if(document.activeElement!==$('diff-goto'))$('diff-goto').value=Math.min(model.referenceLength,model.refBefore[Math.floor(start+(end-start)/2)]+1);
  $('diff-window-back').disabled=start===0;$('diff-window-forward').disabled=end===model.columns;
  $('diff-sequence-window').querySelectorAll('[data-diff-feature]').forEach(node=>node.onclick=()=>focusDifferenceFeature(Number(node.dataset.diffFeature)));
  $('compare-alignment-panel').querySelectorAll('[data-diff-site]:not([data-diff-base])').forEach(node=>{
    const inspect=event=>{event.stopPropagation();focusDifferenceSite(node.dataset.diffSide,Number(node.dataset.diffSite));};
    node.onclick=inspect;node.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();inspect(event);}};
  });
  bindDifferenceHover();$('diff-sequence-window').onscroll=hideDifferenceTooltip;
  if($('diff-full-list').open)renderDifferenceList();
}
function renderDifferenceList(){
  const nav=comparisonPopup?.differenceNavigator;if(!nav)return;
  const {model}=nav;
  $('diff-full-list-body').innerHTML=model.changes.length?`<table><thead><tr><th>Difference</th><th>Reference</th><th>Original query</th><th>Features</th><th>Sequence</th></tr></thead><tbody>${model.changes.map(c=>`<tr class="${c.index===nav.selected?'diff-table-selected':''}"><td><button class="text-button diff-kind-${c.type}" data-diff-list-index="${c.index}">${c.index+1} · ${DifferenceViewer.names[c.type]}</button></td><td>${DifferenceViewer.span(c.reference_start,c.reference_end)}</td><td>${esc(DifferenceViewer.originalQueryLabel(model,c.query_start,c.query_end))}</td><td>${esc(DifferenceViewer.affected(model,c).map(f=>f.label||f.type).join(', ')||'—')}</td><td><code>${esc((c.reference_bases||'—').slice(0,80))} → ${esc((c.query_bases||'—').slice(0,80))}${Math.max(c.reference_bases.length,c.query_bases.length)>80?'…':''}</code></td></tr>`).join('')}</tbody></table>`:'<span class="small muted">No differences</span>';
  $('diff-full-list-body').querySelectorAll('[data-diff-list-index]').forEach(button=>button.onclick=()=>{selectDifference(Number(button.dataset.diffListIndex));$('diff-full-list').open=false;$('diff-window-title').focus({preventScroll:true});});
}
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>showView(b.dataset.view));
document.querySelector('.brand').onclick=event=>{
  if(event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
  event.preventDefault();showView('home');window.scrollTo({top:0,behavior:'auto'});$('home-heading').focus({preventScroll:true});
};
async function changeAssemblyEnzyme(){
  busy('Updating cut sites…');
  try{
    if(!await refresh())return;
    state.parts=state.parts.map(part=>state.fragments.find(fragment=>fragment.id===part.id)).filter(Boolean);
    await loadNestedChildren();backboneChanged();
  }catch(error){toast(error.message);}finally{busy('');}
}
function selectBackbone(){backboneChanged();}
$('backbone').onchange=selectBackbone;$('slot').onchange=()=>{updateCassetteFlag();renderParts();invalidate();if(state.subtab==='reaction')loadResuspension();};
$('enzyme').onchange=changeAssemblyEnzyme;
$('clear-parts').onclick=()=>{state.parts=[];state.nestedAssemblies=[];state.nestedParent=null;state.nestedDraftStocks={};renderParts();invalidate();};
$('fragment-search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(searchFragments,160);};$('fragment-search').onfocus=searchFragments;$('compatible-only').onchange=searchFragments;
$('fragment-search').onkeydown=e=>{const options=[...$('search-results').querySelectorAll('.search-option:not(:disabled)')];if(e.key==='Escape')closeAssemblySearch();if(e.key==='ArrowDown'&&options.length){e.preventDefault();options[0].focus();}if(e.key==='ArrowUp'&&options.length){e.preventDefault();options.at(-1).focus();}if(e.key==='Enter'&&options.length&&!$('search-results').classList.contains('hidden')){e.preventDefault();options[0].click();}};
$('search-results').onkeydown=e=>{const options=[...$('search-results').querySelectorAll('.search-option:not(:disabled)')];let i=options.indexOf(document.activeElement);if(e.key==='ArrowDown'){e.preventDefault();options[(i+1)%options.length]?.focus();}if(e.key==='ArrowUp'){e.preventDefault();options[(i-1+options.length)%options.length]?.focus();}if(e.key==='Escape'){$('fragment-search').focus();closeAssemblySearch();}};
document.addEventListener('click',e=>{if(!e.target.closest('.nested-search-wrap')&&$('nested-search-results')){$('nested-search-results').classList.add('hidden');$('nested-search')?.setAttribute('aria-expanded','false');}if(!e.target.closest('.search-wrap'))closeAssemblySearch();});

$('build-preview').onmouseenter=()=>clearTimeout(buildPreviewTimer);$('build-preview').onmouseleave=scheduleHideBuildPreview;
$('export-build-genbank').onclick=()=>downloadBuildGenbanks();
$('new-build').onclick=newBuild;
$('undo-build-remove').onclick=undoBuildRemove;

const plannerInputKeys={'backbone-pmol':'backbone_pmol','insert-ratio':'insert_ratio','reaction-ul':'reaction_volume_ul','master-ul':'master_mix_volume_ul'};
const plannerRuleGroups={
  molar:{title:'DNA input',fields:[['backbone_pmol','DNA input · pmol']]},
  ratio:{title:'Fragment ratio',fields:[['insert_ratio','Fragment ratio']]},
  target:{title:'Target volume',fields:[['preferred_resuspension_ul','Volume µL']]},
  inputs:{title:'Fragment inputs',fields:[['min_input_volume_ul','Minimum µL'],['max_input_volume_ul','Maximum µL']]},
  resuspension:{title:'Fragment resuspension',fields:[['max_resuspension_ul','Maximum µL']]}
};
let editingPlannerRule=null,editingRuleScope='planner';
function readPlannerOverrides(){try{const value=window.JunctionSandbox?.preferences?.plannerOverrides||{};const allowed=['backbone_pmol','insert_ratio','preferred_resuspension_ul','reaction_volume_ul','master_mix_volume_ul','min_input_volume_ul','max_input_volume_ul','max_resuspension_ul'];return Object.fromEntries(Object.entries(value).filter(([key,v])=>allowed.includes(key)&&Number.isFinite(v)));}catch{return {};}}
function persistPlannerOverrides(){if(window.JunctionSandbox){window.JunctionSandbox.preferences.plannerOverrides={...state.plannerOverrides};window.JunctionSandbox.schedule();}}
function plannerRuleDefaults(){return{reaction_volume_ul:20,master_mix_volume_ul:4,...state.rules};}
function updatePlannerRuleLabels(){
  const rules={...plannerRuleDefaults(),...state.plannerOverrides};
  $('target-volume-rule').textContent=`Target ${fmt(rules.preferred_resuspension_ul)} µL`;
  $('input-volume-rule').textContent=`Inputs ${fmt(rules.min_input_volume_ul)}–${fmt(rules.max_input_volume_ul)} µL`;
  $('resuspension-cap-rule').textContent=`Resuspension ≤${fmt(rules.max_resuspension_ul)} µL`;
}
function openPlannerRule(group,scope='planner'){
  if(scope==='planner'&&$('assume-stock').checked)return;
  editingPlannerRule=group;editingRuleScope=scope;const spec=plannerRuleGroups[group];const current=scope==='upload'?uploadRules():settings();
  $('planner-rule-title').textContent=spec.title;
  $('planner-rule-fields').innerHTML=spec.fields.map(([key,label])=>`<label>${label}<input data-planner-field="${key}" aria-label="${label}" type="number" min="0" step="any" value="${current[key]}" required></label>`).join('');
  $('planner-rule-error').classList.add('hidden');$('planner-rule-editor').showModal();
}
function applyPlannerRule(values){
  if(editingRuleScope==='upload'){Object.assign(state.uploadRuleOverrides,values);if(window.JunctionSandbox){window.JunctionSandbox.preferences.uploadRuleOverrides={...state.uploadRuleOverrides};window.JunctionSandbox.schedule();}updateUploadRuleLabels();$('planner-rule-editor').close();clearPlatePreview();if(plateUploads.jobs.some(job=>!job.invalid&&job.status!=='Imported'))plateUpload(true);return;}
  Object.assign(state.plannerOverrides,values);
  for(const[id,key]of Object.entries(plannerInputKeys))if(key in values)$(id).value=values[key];
  updatePlannerRuleLabels();$('planner-rule-editor').close();planChanged();
}
function backboneInputVolume(pmol,length,stock){
  if(stock===null||stock===undefined||stock==='')return 1;
  return Number(stock)>0&&length>0&&pmol>0?pmol*length*660/1000/Number(stock):null;
}
function updateBackboneVolume(){
  const group=backboneStockChoices().find(g=>g.key===plannerStockKey);
  const source=group&&(group.kind==='plasmid'?state.plasmids:state.fragments).find(p=>p.id===group.id);
  const savedPart=group?.items[0]?.plan?.parts.find(p=>p.role==='backbone');
  const length=source?.physical_length||source?.length||savedPart?.physical_length;
  const entered=$('planner-backbone-stock').value,current=group?.key===selectedStockKey;
  const savedStock=source?.stock_ng_ul||savedPart?.stock_ng_ul||null;
  const mixed=group&&plannerBackboneStock(group).mixed&&entered==='';
  const targets=current&&!mixed?[{backbone_pmol:Number($('backbone-pmol').value)}]:(group?.items||[]).map(item=>({...item.request.settings,...planRowDrafts.get(item.id)}));
  const volumes=group?targets.map(target=>backboneInputVolume(target.backbone_pmol,length,(mixed?target.backbone_stock_ng_ul:entered)||savedStock)).filter(value=>value!==null):[];
  if(group&&!targets.length&&entered===''&&!savedStock)volumes.push(1);
  const low=volumes.length?Math.min(...volumes):null,high=volumes.length?Math.max(...volumes):null;
  $('backbone-use-ul').textContent=(low!==high?inventoryQuantity(low)+'–'+inventoryQuantity(high):inventoryQuantity(low))+' µL';
  $('backbone-use-ul').title=entered===''&&!savedStock&&!mixed?'Default backbone volume':current?'At the current backbone input':'Across queued builds';
}
function planChanged(){
  const invalidStock=$('resuspension-body').querySelector('input[aria-invalid="true"]');if(invalidStock){invalidStock.reportValidity();toast('Enter positive stock values');return;}
  clearTimeout(previewTimer);invalidate();clearTimeout(assemblyCheckTimer);
  updatePlannerStockMode();
  const invalid=[...document.querySelectorAll('.reaction-panel input')].find(input=>!input.matches(':disabled')&&!(input.id==='backbone-stock'&&!$('backbone').value)&&!input.checkValidity());
  if(invalid){invalid.reportValidity();assemblyCheckFailed('Enter a valid reaction value before checking the assembly.');return;}
  for(const[id,key]of Object.entries(plannerInputKeys))state.plannerOverrides[key]=Number($(id).value);
  if(state.activeBuildId===null)persistPlannerOverrides();else scheduleBuildSettingsSave();updatePlannerRuleLabels();updateBackboneVolume();
  previewTimer=setTimeout(()=>{loadResuspension();if(state.parts.length||$('backbone').value)checkAssembly();},200);
}
for(const id of ['backbone-pmol','insert-ratio','reaction-ul','master-ul','assume-stock'])$(id).onchange=()=>{if(id==='assume-stock'){state.plannerStocks={};clearTimeout(plannerStockTimer);}planChanged();};
document.querySelectorAll('[data-planner-rule]').forEach(button=>button.onclick=()=>openPlannerRule(button.dataset.plannerRule));
document.querySelectorAll('[data-upload-rule]').forEach(button=>button.onclick=()=>openPlannerRule(button.dataset.uploadRule,'upload'));
$('planner-rule-close').onclick=()=>$('planner-rule-editor').close();
$('planner-rule-form').onsubmit=event=>{
  event.preventDefault();const values=Object.fromEntries([...$('planner-rule-fields').querySelectorAll('input')].map(input=>[input.dataset.plannerField,Number(input.value)]));
  const merged={...(editingRuleScope==='upload'?uploadRules():settings()),...values};let error='';
  if(Object.values(values).some(value=>!Number.isFinite(value)||value<=0))error='Enter a positive number.';
  else if(merged.min_input_volume_ul>merged.max_input_volume_ul)error='Minimum cannot exceed maximum.';
  if(error){$('planner-rule-error').textContent=error;$('planner-rule-error').classList.remove('hidden');return;}
  applyPlannerRule(values);
};
$('planner-rule-reset').onclick=()=>{const defaults=editingRuleScope==='upload'?state.rules:plannerRuleDefaults();applyPlannerRule(Object.fromEntries(plannerRuleGroups[editingPlannerRule].fields.map(([key])=>[key,defaults[key]])));};
document.querySelectorAll('[data-subtab]').forEach(b=>b.onclick=()=>navigateAssemblyTab(b.dataset.subtab));
$('assembly-next').onclick=()=>navigateAssemblyTab({assembly:'reaction',reaction:'export'}[state.subtab]);
$('assembly-warning-back').onclick=()=>finishAssemblyExportWarnings(false);
$('assembly-warning-continue').onclick=()=>finishAssemblyExportWarnings(true);
$('assembly-warning-dialog').onclose=()=>finishAssemblyExportWarnings(false);
$('backbone-stock-select').onchange=selectPlannerBackboneStock;
$('planner-backbone-stock').oninput=$('planner-backbone-stock').onchange=editPlannerBackboneStock;
$('backbone-pmol').oninput=updateBackboneVolume;
$('planner-recalculate').onclick=planChanged;

$('assembly-name').oninput=$('assembly-name').onchange=()=>assemblyNameChanged();
$('assembly-name-recommendation').onclick=applyRecommendedAssemblyName;
let viewerRenameChain=Promise.resolve(),viewerRenameRevision=0,viewerRenameTimer=null;
function renameViewer(){
  clearTimeout(viewerRenameTimer);
  const result=state.result;if(!result)return;
  if(result.viewerReadOnly)return;
  if(result.viewerPlasmidId&&window.JunctionAccount&&!window.JunctionAccount.allowed('can_edit'))return;
  const input=$('viewer-name');const name=input.value.trim();
  if(!name){input.setCustomValidity('Enter a plasmid name.');input.reportValidity();$('viewer-name-status').textContent='Name required';return;}
  input.setCustomValidity('');input.value=name;
  if(!result.storedReference)state.assemblyNameManual=true;
  if(name===result.name)return;
  const oldName=result.name;const revision=++viewerRenameRevision;
  result.name=name;
  if(!result.storedReference)$('assembly-name').value=name;
  renderMap();renderBuildList();
  if(!result.storedReference)scheduleBuildSettingsSave();
  $('viewer-name-status').textContent=result.viewerPlasmidId?'Saving…':'Updated';
  viewerRenameChain=viewerRenameChain.catch(()=>{}).then(async()=>{
    try{
      if(result.viewerPlasmidId){
        await api('/api/plasmids/'+result.viewerPlasmidId,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
        await refresh();renderPlasmidLibraries();
      }
      if(state.result===result&&revision===viewerRenameRevision)$('viewer-name-status').textContent=result.viewerPlasmidId?'Saved':'Updated';
    }catch(error){
      if(state.result===result&&revision===viewerRenameRevision){
        result.name=oldName;if(input.value.trim()===name)input.value=oldName;if(!result.storedReference)$('assembly-name').value=oldName;renderMap();renderBuildList();$('viewer-name-status').textContent='Not saved';
      }
      toast(error.message);
    }
  });
}
$('viewer-name').oninput=()=>{
  const input=$('viewer-name');input.setCustomValidity('');clearTimeout(viewerRenameTimer);
  const result=state.result;
  if(result&&!result.storedReference){state.assemblyNameManual=true;if(input.value.trim()){$('assembly-name').value=input.value;scheduleBuildSettingsSave();}}
  const value=input.value;
  if(value.trim())viewerRenameTimer=setTimeout(()=>{if(state.result===result&&input.value===value)renameViewer();},400);
};
$('viewer-name').onchange=renameViewer;
$('viewer-name').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();renameViewer();event.target.blur();}if(event.key==='Escape'){event.preventDefault();clearTimeout(viewerRenameTimer);event.target.value=state.result?.name||'';if(state.result&&!state.result.storedReference){$('assembly-name').value=state.result.name;scheduleBuildSettingsSave();}event.target.setCustomValidity('');$('viewer-name-status').textContent='';event.target.blur();}};
function genbankExportDate(){
  const now=new Date();return [now.getFullYear(),String(now.getMonth()+1).padStart(2,'0'),String(now.getDate()).padStart(2,'0')].join('-');
}
async function downloadViewedGenbank(){
  if(assemblyExportBusy)return;
  const result=state.result;
  if(!result?.sequence||result.errors?.length||result.storedReference&&!result.viewerPlasmidId)return;
  assemblyExportBusy=true;
  try{
    renameViewer();
    // Preserve the displayed recipe even if another assembly opens while exporting.
    const request=result.storedReference?null:JSON.parse(JSON.stringify({...result.recipe,name:result.name}));
    await viewerRenameChain;
    if(result.storedReference)await fileDownload('/api/plasmids/'+result.viewerPlasmidId+'/genbank',null,result.name+'.gb');
    else{
      if(!request.fragment_ids)throw Error('Recheck this assembly before exporting');
      if(result.warnings?.length&&!await confirmAssemblyExportWarnings([{name:result.name,messages:result.warnings}]))return;
      await fileDownload('/api/assemblies/genbank',request,result.name+'.gb');
    }
  }catch(error){toast(error.message);}
  finally{assemblyExportBusy=false;}
}
async function downloadBuildGenbanks(){
  if(assemblyExportBusy||state.buildBusy)return;
  assemblyExportBusy=true;
  try{
    flushPlanInputs();await persistPendingBuild();await Promise.all([...planEditOperations]);
    if(state.buildSaveError)throw Error('Save build list changes before exporting');
    await loadBuildList();
    const failures=state.buildList.filter(item=>!item.plan||item.plan.errors?.length).map(item=>({name:item.request.name,messages:item.plan?.errors?.length?item.plan.errors:[item.error||'Assembly unavailable.']}));
    if(!state.buildList.length)failures.push({name:'Build list',messages:['Add an assembly to the build list first.']});
    if(failures.length){
      $('assembly-warning-continue').hidden=true;
      try{await confirmAssemblyExportWarnings(failures);}finally{$('assembly-warning-continue').hidden=false;}
      return;
    }
    const warnings=state.buildList.filter(item=>item.plan.warnings?.length).map(item=>({name:item.request.name,messages:item.plan.warnings}));
    if(warnings.length&&!await confirmAssemblyExportWarnings(warnings))return;
    // Reaction volumes do not affect a valid sequence export.
    await fileDownload('/api/build-list/genbank?export_date='+genbankExportDate(),null,'Build_list_GenBank.zip');
  }catch(error){toast(error.message);}
  finally{assemblyExportBusy=false;updateBuildActions();}
}
$('viewer-download-gb').onclick=downloadViewedGenbank;
$('download-gb').onclick=downloadViewedGenbank;
async function saveAssembly(asBackbone=false){
  const button=$(asBackbone?'save-backbone':'save-assembly');button.disabled=true;
  try{const r=await api('/api/assemblies',jsonBody({...payload(),save_as_backbone:asBackbone}));if(state.result)state.result.viewerPlasmidId=r.id;await refresh();toast(asBackbone?'Saved backbone · '+r.name+' · '+r.backbone_enzymes.join(' / '):'Saved '+r.name+' to the plasmid library.');}
  catch(e){toast(e.message);}
  finally{if(state.result)renderResult();}
}
$('save-assembly').onclick=()=>saveAssembly();
$('save-backbone').onclick=()=>saveAssembly(true);
$('planner-reset-stocks').onclick=()=>{state.plannerStocks={};clearTimeout(plannerStockTimer);checkAssembly();loadResuspension();scheduleBuildSettingsSave();};
let worksheetExportSource=null;
function closeWorksheetExport(restoreFocus=false){
  const source=worksheetExportSource;worksheetExportSource=null;$('worksheet-export-menu').classList.add('hidden');
  source?.setAttribute('aria-expanded','false');if(restoreFocus)source?.focus();
}
function openWorksheetExport(button){
  const wasOpen=worksheetExportSource===button;closeWorksheetExport();if(wasOpen)return;
  worksheetExportSource=button;button.setAttribute('aria-expanded','true');
  const menu=$('worksheet-export-menu'),rect=button.getBoundingClientRect();menu.classList.remove('hidden');
  menu.style.left=Math.max(8,Math.min(rect.right-menu.offsetWidth,window.innerWidth-menu.offsetWidth-8))+'px';
  menu.style.top=(rect.bottom+menu.offsetHeight+6>window.innerHeight?Math.max(8,rect.top-menu.offsetHeight-6):rect.bottom+6)+'px';
  menu.querySelector('button').focus();
}
async function downloadWorksheet(kind,format){
  const assemblyExport=kind==='build-list'||kind==='assembly';
  if(assemblyExport&&assemblyExportBusy)return;
  if(assemblyExport)assemblyExportBusy=true;
  try{
    if(assemblyExport){
      flushPlanInputs();
      const invalid=document.querySelector('#build-plans-body input[aria-invalid="true"],.reaction-panel input[aria-invalid="true"]');
      if(invalid){invalid.reportValidity();throw Error('Enter valid build plan values');}
      await persistPendingBuild();await Promise.all([...planEditOperations]);
      if(buildPlanErrors.size)throw Error('Save build plan changes before exporting');
      if(state.parts.length||$('backbone').value)await checkAssembly();
      if(kind==='build-list')await loadBuildList();
      const warnings=assemblyExportWarnings(kind);
      if(warnings.length&&!await confirmAssemblyExportWarnings(warnings))return;
      if(kind==='build-list'){
        const now=new Date(),exportDate=[now.getFullYear(),String(now.getMonth()+1).padStart(2,'0'),String(now.getDate()).padStart(2,'0')].join('-');
        await fileDownload('/api/build-list/worksheet?format='+format+'&export_date='+exportDate,null,'Build_list_'+exportDate+'.'+format);
      }
      else await fileDownload('/api/assemblies/worksheet?format='+format,payload(),'assembly.'+format);
    }
    else if(kind==='library')await fileDownload('/api/inventory/worksheet?format='+format,{...state.rules,no_backbone:true,resuspension_mode:'constrained',planner_stock_mode:'saved',plate:$('plate-filter').value||''},'resuspension.'+format);
    else if(kind==='upload'){
      const keys=new Set((state.uploadPlan?.rows||[]).map(row=>JSON.stringify([row.plate_id,row.well])));
      const ids=state.fragments.filter(part=>keys.has(JSON.stringify([part.plate_id,part.well]))).map(part=>part.id);
      if(!ids.length)throw Error('Import plate maps before exporting');
      const values=Object.fromEntries(state.uploadParams||[]);delete values.apply_import_rules;
      for(const key of Object.keys(values))if(!['no_backbone','resuspension_mode'].includes(key))values[key]=Number(values[key]);
      await fileDownload('/api/inventory/worksheet?format='+format,{...values,no_backbone:true,planner_stock_mode:'saved',fragment_ids:ids},'resuspension.'+format);
    }
  }catch(error){toast(error.message);}
  finally{if(assemblyExport)assemblyExportBusy=false;}
}
document.querySelectorAll('[data-worksheet-export]').forEach(button=>{button.onclick=()=>openWorksheetExport(button);button.onkeydown=event=>{if(event.key==='ArrowDown'){event.preventDefault();openWorksheetExport(button);}};});
$('worksheet-export-menu').querySelectorAll('[data-worksheet-format]').forEach(button=>button.onclick=()=>{const kind=worksheetExportSource?.dataset.worksheetExport;closeWorksheetExport(true);if(kind)downloadWorksheet(kind,button.dataset.worksheetFormat);});
$('worksheet-export-menu').onkeydown=event=>{const buttons=[...$('worksheet-export-menu').querySelectorAll('button')],index=buttons.indexOf(document.activeElement);if(event.key==='Escape'){event.preventDefault();closeWorksheetExport(true);}else if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();buttons[event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowDown'?1:buttons.length-1))%buttons.length].focus();}else if(event.key==='Tab')closeWorksheetExport();};
document.addEventListener('click',event=>{if(!event.target.closest('[data-worksheet-export],#worksheet-export-menu'))closeWorksheetExport();});
window.addEventListener('resize',()=>closeWorksheetExport());window.addEventListener('scroll',()=>closeWorksheetExport(),true);
$('map-site-filter').onchange=()=>{renderMap();renderSequence();};
$('view-circular').onclick=()=>{state.mapMode='circular';renderMap();};$('view-linear').onclick=()=>{state.mapMode='linear';renderMap();};$('show-sequence').onclick=renderSequence;$('sequence-prev').onclick=()=>{$('sequence-start').value=Math.max(1,Number($('sequence-start').value)-200);renderSequence();};$('sequence-next').onclick=()=>{$('sequence-start').value=Number($('sequence-start').value)+200;renderSequence();};
$('inventory-rules-form').onsubmit=async event=>{event.preventDefault();try{const rules=Object.fromEntries(Object.keys(state.rules).map(key=>[key,Number($('rule-'+key).value)]));await api('/api/inventory/rules',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(rules)});await reloadInventory();toast('Rules saved');}catch(e){toast(e.message);}};
$('reset-rules').onclick=async()=>{try{await api('/api/inventory/rules/reset',jsonBody({}));await reloadInventory();toast('Default rules restored');}catch(e){toast(e.message);}};
$('reset-inventory').onclick=()=>resetInventoryRows(Array.from(state.fragmentSelection));
$('apply-inventory-rules').onclick=openSelectedRules;
$('inventory-rule-apply-form').onsubmit=applySelectedRules;
$('inventory-rule-close').onclick=()=>$('inventory-rule-editor').close();
$('inventory-rule-editor').oncancel=event=>{if($('inventory-rule-apply').disabled)event.preventDefault();};
$('inventory-rule-default').onclick=async()=>{try{fillSelectedRuleFields((await api('/api/inventory/rules')).defaults);}catch(error){toast(error.message);}};
$('select-fragments').onchange=event=>{$('inventory-body').querySelectorAll('[data-inventory-id]').forEach(row=>{const id=Number(row.dataset.inventoryId);event.target.checked?state.fragmentSelection.add(id):state.fragmentSelection.delete(id);row.querySelector('[data-fragment-select]').checked=event.target.checked;});updateFragmentSelection();};
$('archive-fragments').onclick=()=>archiveSelection(Array.from(state.fragmentSelection),[]);
document.querySelectorAll('[data-inventory-sort]').forEach(button=>button.onclick=()=>{const key=button.dataset.inventorySort;state.inventorySort={key,direction:state.inventorySort?.key===key?-state.inventorySort.direction:1};sortInventoryRows();});
$('select-bin').onchange=event=>{$('bin-body').querySelectorAll('[data-bin-id]').forEach(input=>input.checked=event.target.checked);updateBinSelection();};
$('restore-bin').onclick=async()=>{try{const selected=[...$('bin-body').querySelectorAll('[data-bin-id]:checked')];const selection={fragment_ids:selected.filter(i=>i.dataset.binKind==='fragment').map(i=>Number(i.dataset.binId)),plasmid_ids:selected.filter(i=>i.dataset.binKind==='plasmid').map(i=>Number(i.dataset.binId)),plate_ids:selected.filter(i=>i.dataset.binKind==='plate').map(i=>i.dataset.binId)};await api('/api/bin/restore',jsonBody(selection));await refresh();renderPlasmidLibraries();await loadBin();toast('Items restored');}catch(e){toast(e.message);}};
$('library-search').oninput=()=>{state.fragmentSelection.clear();clearTimeout(searchTimer);searchTimer=setTimeout(loadInventory,200);};$('plate-filter').onchange=()=>{state.fragmentSelection.clear();loadInventory();};$('library-enzyme').onchange=loadInventory;
initializeUploads();
window.CustomUploads.setup(window,document,{api,fragments:()=>state.fragments,onImported:async()=>{await refresh();await loadUploads();},notify:toast});
document.querySelectorAll('[data-upload-topology]').forEach(button=>{button.innerHTML=inventoryIcon(button.dataset.uploadTopology);button.onclick=()=>{$('upload-topology').value=button.dataset.uploadTopology;if(button.dataset.uploadTopology!=='circular')$('upload-backbone').checked=false;updateUploadPlasmidIcons();};});
$('upload-backbone-toggle').innerHTML=inventoryIcon('backbone');$('upload-backbone-toggle').onclick=()=>{$('upload-backbone').checked=!$('upload-backbone').checked;if($('upload-backbone').checked)$('upload-topology').value='circular';updateUploadPlasmidIcons();};updateUploadPlasmidIcons();
$('select-plates').onchange=event=>{state.plateSelection=new Set(event.target.checked?state.plateMaps.map(p=>p.plate_id):[]);renderPlateMaps();};
$('archive-plates').onclick=archivePlateMaps;
$('plate-export-format').onchange=async event=>{
  const format=event.target.value,plate=state.plateView;if(!format||!plate)return;
  event.target.value='';event.target.disabled=true;hidePlateTooltip();
  try{await fileDownload('/api/plates/well-list?'+new URLSearchParams({plate_id:plate.plate_id,format,layout:$('plate-view-format').value}),null,'plate-well-list.'+(format==='csv'?'csv.zip':format));}
  finally{event.target.disabled=!state.plateView;}
};
$('plate-archive-map').onclick=()=>archiveFromPlate([],true);
$('plate-archive-wells').onclick=()=>archiveFromPlate([...state.plateWellSelection]);
$('plate-select-wells').onchange=renderPlateView;
$('plate-wells-all').onclick=()=>{const p=state.plateView;if(!p||p.archived_at||state.plateArchiveBusy)return;$('plate-select-wells').checked=true;state.plateWellSelection=new Set(p.fragments.filter(f=>!f.archived_at).map(f=>f.id));renderPlateView();};
$('plate-wells-clear').onclick=()=>{state.plateWellSelection.clear();renderPlateView();};
$('fragment-info-close').onclick=()=>$('fragment-info-dialog').close();
$('fragment-info-dialog').onclose=()=>{fragmentInfoToken++;fragmentInfoRecord=null;};
$('fragment-sequence-close').onclick=()=>$('fragment-sequence-dialog').close();
$('fragment-sequence-dialog').onclose=()=>{fragmentSequenceToken++;fragmentSequenceRecord=null;$('fragment-sequence-text').value='';};
$('fragment-sequence-kind').onchange=renderFragmentSequence;
$('fragment-sequence-copy').onclick=copyFragmentSequence;
$('plate-view-close').onclick=()=>$('plate-viewer').close();
$('plate-viewer').onclose=()=>{plateViewToken++;hidePlateTooltip();state.plateView=null;state.plateWellSelection.clear();updatePlateArchiveControls();};
$('plate-view-format').onchange=renderPlateView;$('plate-show-labels').onchange=renderPlateView;$('plate-grid').parentElement.onscroll=hidePlateTooltip;

initializeCompare();

$('swap-search').oninput=renderSwapOptions;
$('swap-close').onclick=()=>closeFragmentSwap(true);
$('fragment-swap').onkeydown=event=>{
  const options=[...$('swap-options').querySelectorAll('.swap-option')];
  const current=options.indexOf(document.activeElement);
  if(event.key==='ArrowDown'&&options.length){event.preventDefault();options[(current+1)%options.length].focus();}
  if(event.key==='ArrowUp'&&options.length){event.preventDefault();options[current<0?options.length-1:(current-1+options.length)%options.length].focus();}
  if(event.key==='Enter'&&document.activeElement===$('swap-search')&&options.length){event.preventDefault();options[0].click();}
};
document.addEventListener('click',event=>{if(state.swapIndex!==null&&!event.target.closest('#fragment-swap')&&!event.target.closest('[data-swap-index]'))closeFragmentSwap();});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&state.swapIndex!==null){event.preventDefault();closeFragmentSwap(true);}});
document.addEventListener('focusin',event=>{if(state.swapIndex!==null&&!event.target.closest('#fragment-swap')&&!event.target.closest('[data-swap-index]'))closeFragmentSwap();});
window.addEventListener('resize',()=>closeFragmentSwap());
window.addEventListener('scroll',event=>{if(state.swapIndex!==null&&!$('fragment-swap').contains(event.target))closeFragmentSwap();},true);

document.querySelectorAll('dialog').forEach(PopupControls.bindDialog);
$('plasmid-view-back').onclick=$('plasmid-view-close').onclick=()=>$('plasmid-view-dialog').close();
$('plasmid-view-dialog').onclose=restorePlasmidViewer;
document.addEventListener('click',event=>{
  if(state.nestedParent!==null&&!event.target.closest('#nested-assembly-editor,[data-nested-parent]'))closeNestedEditor(false);
  if(!event.target.closest('#plasmid-map,#map-tooltip'))hideMapTooltip();
  if(!event.target.closest('[data-plan-build],#build-preview'))hideBuildPreview();
  if(!event.target.closest('[data-nested-parent],#nested-card-tooltip'))hideNestedCardTooltip();
  if(!event.target.closest('.fragment-check,#fragment-check-tooltip'))hideFragmentCheckTooltip();
});

function sandboxSnapshot(){
  return {version:1,workbench_id:state.workbenchId,worksheet_ids:state.worksheetIds,design:window.JunctionDesign?.snapshot(),draft:payload(),activeBuildId:state.activeBuildId,plannerOverrides:state.plannerOverrides,uploadRuleOverrides:state.uploadRuleOverrides,
    backboneStocks:Object.fromEntries(backboneStockCache),subtab:state.subtab,view:location.hash.slice(1),
    compareView:{...compareFileView,enzyme:$('compare-enzyme').value,jobs:Object.fromEntries(compareJobs.filter(j=>j.sandboxId).map(j=>[j.sandboxId,{expanded:!!j.expanded,recordIndex:j.recordIndex,selected:compareSelection.has(j.id),path:j.path}]))}};
}
async function restoreSandbox(saved,runs){
  state.workbenchId=saved.workbench_id||null;state.worksheetIds=saved.worksheet_ids||{};
  window.JunctionDesign?.restore(saved.design);
  const draft=saved.draft;
  if(draft){
    state.assemblyNameManual=true;
    $('enzyme').value=['BsaI','BsmBI','BsmBI + BsaI'].includes(draft.enzyme)?draft.enzyme:'BsaI';await refresh();
    $('assembly-name').value=draft.name||'New assembly';$('backbone').value=draft.backbone_id?'p:'+draft.backbone_id:'';
    const ids=draft.fragment_ids||[];state.parts=ids.map(id=>state.fragments.find(f=>f.id===id)).filter(Boolean);
    state.nestedAssemblies=(draft.nested_assemblies||[]).filter(g=>state.parts.some(p=>p.id===g.parent_fragment_id));
    for(const[key,value]of Object.entries(saved.backboneStocks||{}))backboneStockCache.set(key,value);
    try{await loadNestedChildren();}catch(error){toast('A nested sandbox fragment is unavailable. Restore it from Archive.');}
    restoreAssemblyName(draft);
    backboneChanged(false);if(draft.slot_id!==null)$('slot').value=String(draft.slot_id);
    const incomplete=state.parts.length!==ids.length||(draft.backbone_id&&!$('backbone').value);
    setPlannerInputs(draft.settings||{});state.activeBuildId=!incomplete&&state.buildList.some(item=>item.id===saved.activeBuildId)?saved.activeBuildId:null;renderParts();
    if(incomplete)toast('Some sandbox inputs are archived or unavailable. Saved builds are preserved.');
    if(state.parts.length||$('backbone').value)await checkAssembly();
  }else{$('backbone').value='';backboneChanged(false);}
  const view=saved.compareView||{};Object.assign(compareFileView,{search:view.search||'',filter:view.filter||'all',sort:view.sort||null,direction:view.direction||1});
  $('compare-file-search').value=compareFileView.search;$('compare-file-filter').value=compareFileView.filter;
  if(['auto','BsaI','BsmBI','BsmBI + BsaI'].includes(view.enzyme))$('compare-enzyme').value=view.enzyme;
  for(const run of runs){const file=new File([run.source],run.filename,{type:'text/plain',lastModified:0}),meta=view.jobs?.[run.id]||{},id=compareNextId++;
    compareJobs.push({id,sandboxId:run.id,key:[meta.path||run.filename,file.size,0].join('|'),file,path:meta.path||run.filename,status:run.error?'Error':run.result?'Done':'Queued',error:run.error||'',result:run.result,expanded:!!meta.expanded,recordIndex:meta.recordIndex||0,candidateIndex:0});if(meta.selected)compareSelection.add(id);
  }
  comparisonQueue();selectSubtab(['assembly','reaction','export'].includes(saved.subtab)?saved.subtab:'assembly');
  showView(JunctionHome.resolveView(location.hash.slice(1)));renderBuildList();
}
const sandbox=SandboxState.create({request:(url,body)=>api(url,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),capture:sandboxSnapshot,report:error=>toast('Sandbox not saved: '+error.message)});
window.JunctionSandbox=Object.assign(sandbox,{preferences:{}});
for(const event of ['input','change','click'])document.addEventListener(event,()=>sandbox.schedule());
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')sandbox.flush().catch(error=>toast(error.message));});
window.addEventListener('pagehide',()=>{if(sandbox.ready)fetch('/api/workspace',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({data:sandboxSnapshot()}),keepalive:true}).catch(()=>{});});
window.JunctionWorkbenchController=JunctionWorkbenches.setup(window,document,{
  api,download:fileDownload,notify:toast,
  setCurrent:id=>{state.workbenchId=id;},
  recommendedName:()=>{const name=$('assembly-name').value.trim();return name&&name!=='New assembly'?name:'Workbench '+new Date().toLocaleDateString();},
  stats:()=>`${state.buildList.length} builds · ${window.JunctionDesign?.snapshot()?.designs?.length||0} designs · ${compareJobs.length} comparison files · v${document.querySelector('.brand-version').textContent.replace(/^v/,'')}`,
  flush:async()=>{if(!sandbox.ready)throw Error('Wait for your sandbox to finish loading.');flushPlanInputs();await persistPendingBuild();await Promise.all([...planEditOperations]);await sandbox.flush();},
  pause:()=>{if(compareWorker)throw Error('Wait for comparisons to finish before switching workbenches.');sandbox.stop();},
  resume:()=>sandbox.start(sandboxSnapshot())
});
window.JunctionWorksheetController=JunctionWorksheets.setup(window,document,{
  api,flush:async()=>{if(!sandbox.ready)throw Error('Wait for your sandbox to finish loading.');flushPlanInputs();await persistPendingBuild();await Promise.all([...planEditOperations]);await sandbox.flush();},
  pause:()=>{if(compareWorker)throw Error('Wait for comparisons to finish before switching worksheets.');sandbox.stop();},resume:()=>sandbox.start(sandboxSnapshot()),
  reload:view=>location.replace('/?worksheet='+Date.now()+'#'+view),download:fileDownload,notify:toast,
  nameFor:scope=>scope==='design'?$('design-name').value:scope==='build'?$('assembly-name').value:'Compare worksheet',
  setCurrent:(scope,id)=>{state.worksheetIds[scope]=id;},changed:scheduleLibraryMetrics
});
$('junction-count-button').onclick=async()=>{await refreshLibraryMetrics();renderJunctionList();$('junction-list-dialog').showModal();};
$('junction-list-close').onclick=()=>$('junction-list-dialog').close();
window.JunctionHomeController=JunctionHome.setup(window,document,{navigate:showView});
window.addEventListener('hashchange',()=>showView(JunctionHome.resolveView(location.hash.slice(1))));
showView(JunctionHome.resolveView(location.hash.slice(1)));
(async()=>{const splash=window.JunctionHomeController;
  try{
    splash.status('Checking your account…');await JunctionAccount.ready;
    splash.status('Loading your instance…');const [workspace,runs]=await Promise.all([api('/api/workspace'),api('/api/workspace/comparisons')]);
    sandbox.preferences=workspace.data;state.plannerOverrides=readPlannerOverrides();state.uploadRuleOverrides=readUploadRules();
    splash.status('Loading fragments, backbones and rules…');await refresh();
    splash.status('Restoring build plans…');await loadBuildList();
    splash.status('Restoring worksheets and comparison files…');await restoreSandbox(workspace.data,runs.items);sandbox.start(sandboxSnapshot());
    splash.status('Loading saved worksheets and Workbenches…');await api('/api/worksheets/bootstrap',jsonBody({}));
    await Promise.all([window.JunctionWorksheetController.loadAll(),window.JunctionWorkbenchController.load(),refreshLibraryMetrics()]);
    splash.ready();runCompareQueue();
  }catch(error){splash.fail(error.message);}
})();
