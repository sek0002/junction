/* Page worksheets are distinct from the collection saved as a Workbench. */
(function(root){
  'use strict';
  const scopes={build:'Assembly',design:'Design',compare:'Compare'};
  const paths={save:'<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h12l4 4v12a2 2 0 0 1-2 2Z"/><path d="M7 3v6h10V3M7 21v-8h10v8"/>',share:'<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m9 10 6-3M9 14l6 3"/>',new:'<path d="M14 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9ZM14 3v6h6M8 15h8M12 11v8"/>',remove:'<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',edit:'<path d="m16 3 5 5L8 21H3v-5ZM13 6l5 5"/>',close:'<path d="m6 6 12 12M18 6 6 18"/>'};
  const icon=kind=>'<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true">'+paths[kind]+'</svg>';
  function setup(win,doc,{api,flush,pause,resume,reload,download,notify,nameFor,changed,setCurrent}){
    const $=id=>doc.getElementById(id);let scope=null,locked=false,afterSaveNew=false,exportSource=null,removeTarget=null;
    const records={},active={},loads={};
    const post=(url,body={})=>api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    function render(kind){
      const select=doc.querySelector(`[data-worksheet-select="${kind}"]`),current=active[kind],items=records[kind]||[];
      if(select){select.replaceChildren();const empty=doc.createElement('option');empty.value='';empty.textContent='Unsaved worksheet';select.append(empty);
        for(const item of items){const option=doc.createElement('option');option.value=item.id;option.textContent=item.name;select.append(option);}select.value=current?.id||'';select.disabled=locked;}
      doc.querySelectorAll(`[data-worksheet-delete="${kind}"]`).forEach(button=>button.disabled=locked||!current);
      if(kind===scope){$('worksheet-save').disabled=$('worksheet-share').disabled=$('worksheet-new').disabled=locked||!scope;}
    }
    async function load(kind){
      const revision=(loads[kind]||0)+1;loads[kind]=revision;const result=await api('/api/worksheets?scope='+kind);if(loads[kind]!==revision)return;records[kind]=result.items;active[kind]=result.current;setCurrent?.(kind,result.current?.id||null);render(kind);changed?.();
    }
    async function loadAll(){await Promise.all(Object.keys(scopes).map(load));}
    function setScope(view){scope=scopes[view]?view:null;
      for(const action of ['save','share','new']){$('worksheet-'+action).disabled=!scope;$('worksheet-'+action).title=(scope?scopes[scope]+' worksheet':'Open Assembly, Design or Compare')+' · '+action;}
      if(scope)load(scope).catch(error=>notify(error.message));
    }
    function menuClose(){if($('workbench-menu-toggle').getAttribute('aria-expanded')==='true')$('workbench-menu-toggle').click();}
    function lock(value){locked=value;Object.keys(scopes).forEach(render);doc.querySelectorAll('[data-worksheet-new],[data-worksheet-share]').forEach(button=>button.disabled=value);$('worksheet-save-submit').disabled=value;}
    async function saveDialog(kind=scope,{thenNew=false}={}){
      if(!kind||locked)return;scope=kind;menuClose();afterSaveNew=thenNew;
      try{await flush();await load(kind);$('worksheet-save-title').textContent='Save '+scopes[kind]+' worksheet';$('worksheet-save-name').value=active[kind]?.name||nameFor(kind);$('worksheet-save-notes').value=active[kind]?.notes||'';$('worksheet-save-error').textContent='';$('worksheet-save-dialog').showModal();$('worksheet-save-name').focus();}catch(error){notify(error.message);}
    }
    async function startNew(kind,discard=false){
      if(locked)return;lock(true);menuClose();
      try{root.JunctionHomeController.start('Saving the current worksheet…');await flush();pause();root.JunctionHomeController.status('Creating a new '+scopes[kind]+' worksheet…');await post('/api/worksheets/new',{scope:kind,discard_unsaved:discard});reload(kind);}catch(error){resume();root.JunctionHomeController.cancel();notify(error.message);lock(false);}
    }
    async function newPage(kind=scope){
      if(!kind||locked)return;scope=kind;menuClose();
      try{await flush();await load(kind);if(active[kind])await startNew(kind);else{$('worksheet-new-title').textContent='Save this '+scopes[kind]+' worksheet?';$('worksheet-new-dialog').showModal();}}catch(error){notify(error.message);}
    }
    async function open(kind,id){
      if(!id||locked)return;lock(true);
      try{root.JunctionHomeController.start('Saving the current worksheet…');await flush();pause();root.JunctionHomeController.status('Loading '+(records[kind]?.find(item=>item.id===id)?.name||scopes[kind]+' worksheet')+'…');const result=await post('/api/worksheets/'+id+'/open');reload(result.view);}catch(error){resume();root.JunctionHomeController.cancel();notify(error.message);lock(false);}
    }
    function share({kind=scope,workbench=null,worksheet=null}={}){
      if(locked)return;menuClose();exportSource={kind,workbench,worksheet};
      $('instance-export-scope').value=kind||'workbench';$('instance-export-dialog').showModal();
    }
    $('instance-export-form').addEventListener('submit',async event=>{
      event.preventDefault();const choice=$('instance-export-scope').value,source=exportSource;if(!source)return;
      $('instance-export-submit').disabled=true;
      try{
        await flush();let url,body=null;
        if(source.workbench)url='/api/workbenches/'+source.workbench+'/export'+(choice==='workbench'?'':'?scope='+choice);
        else if(choice==='workbench'){url='/api/workbenches/export-current';body={};}
        else if(source.worksheet&&choice===source.kind)url='/api/worksheets/'+source.worksheet+'/export';
        else{url='/api/worksheets/export-current?scope='+choice;body={};}
        const downloaded=await download(url,body,'Junction.junc');if(downloaded!==false)$('instance-export-dialog').close();
      }catch(error){notify(error.message);}finally{$('instance-export-submit').disabled=false;}
    });
    $('worksheet-save-form').addEventListener('submit',async event=>{
      event.preventDefault();if(locked||!scope)return;lock(true);$('worksheet-save-error').textContent='';
      try{if(scope==='design'){$('design-name').value=$('worksheet-save-name').value.trim();$('design-name').dispatchEvent(new Event('input',{bubbles:true}));}await flush();await post('/api/worksheets',{scope,id:active[scope]?.id||null,name:$('worksheet-save-name').value.trim(),notes:$('worksheet-save-notes').value});await load(scope);$('worksheet-save-dialog').close();notify('Worksheet saved');lock(false);if(afterSaveNew){afterSaveNew=false;await startNew(scope);}}
      catch(error){$('worksheet-save-error').textContent=error.message;lock(false);}
    });
    for(const action of ['save','share','new'])$('worksheet-'+action).innerHTML=icon(action);
    $('worksheet-save').onclick=()=>saveDialog();$('worksheet-share').onclick=()=>share();$('worksheet-new').onclick=()=>newPage();
    $('worksheet-save-close').onclick=()=>$('worksheet-save-dialog').close();
    $('worksheet-new-cancel').onclick=()=>$('worksheet-new-dialog').close();
    $('worksheet-new-save').onclick=()=>{$('worksheet-new-dialog').close();saveDialog(scope,{thenNew:true});};
    $('worksheet-new-discard').onclick=()=>{$('worksheet-new-dialog').close();startNew(scope,true);};
    $('instance-export-close').onclick=()=>$('instance-export-dialog').close();
    for(const kind of Object.keys(scopes)){
      doc.querySelector(`[data-worksheet-select="${kind}"]`).onchange=event=>event.target.value?open(kind,event.target.value):newPage(kind);
      const add=doc.querySelector(`[data-worksheet-new="${kind}"]`),del=doc.querySelector(`[data-worksheet-delete="${kind}"]`),exportButton=doc.querySelector(`[data-worksheet-share="${kind}"]`);
      add.innerHTML=icon('new');add.onclick=()=>newPage(kind);del.innerHTML=icon('remove');
      del.onclick=()=>{removeTarget=active[kind];if(removeTarget){$('worksheet-remove-name').textContent=removeTarget.name;$('worksheet-remove-dialog').showModal();}};
      exportButton.innerHTML=icon('share');exportButton.onclick=()=>share({kind});
    }
    $('worksheet-remove-cancel').onclick=()=>$('worksheet-remove-dialog').close();
    $('worksheet-remove-confirm').onclick=async()=>{if(!removeTarget)return;try{await flush();await api('/api/worksheets/'+removeTarget.id,{method:'DELETE'});$('worksheet-remove-dialog').close();await load(removeTarget.scope);notify('Worksheet archived');}catch(error){notify(error.message);}};
    $('worksheet-archive-toggle').onclick=async()=>{
      const host=$('worksheet-archive-list');host.replaceChildren();
      try{for(const kind of Object.keys(scopes)){const result=await api('/api/worksheets?scope='+kind+'&archived=true');for(const item of result.items){const row=doc.createElement('div');row.className='worksheet-archive-row';const name=doc.createElement('span');name.textContent=scopes[kind]+' · '+item.name;const restore=doc.createElement('button');restore.className='secondary compact';restore.textContent='Restore';restore.onclick=async()=>{try{await post('/api/worksheets/'+item.id+'/restore');row.remove();await load(kind);}catch(error){notify(error.message);}};row.append(name,restore);host.append(row);}}if(!host.childElementCount)host.textContent='No archived worksheets';$('worksheet-archive-dialog').showModal();}catch(error){notify(error.message);}
    };
    $('worksheet-archive-close').onclick=()=>$('worksheet-archive-dialog').close();
    // One shared compact title editor uses the existing validated name fields.
    let titleKind=null;
    for(const kind of ['build','design']){
      const button=$('edit-'+kind+'-title');button.innerHTML=icon('edit');button.onclick=()=>{titleKind=kind;$('page-name-input').value=$(kind==='build'?'assembly-name':'design-name').value;$('page-name-dialog').showModal();$('page-name-input').focus();};
    }
    $('page-name-close').onclick=()=>$('page-name-dialog').close();
    $('page-name-form').onsubmit=async event=>{event.preventDefault();const kind=titleKind,field=$(kind==='build'?'assembly-name':'design-name');field.value=$('page-name-input').value.trim();field.dispatchEvent(new Event('input',{bubbles:true}));syncTitles();$('page-name-dialog').close();
      if(kind==='design'&&active.design){try{await flush();await post('/api/worksheets',{scope:'design',id:active.design.id,name:field.value,notes:active.design.notes});await load('design');}catch(error){notify(error.message);}}
    };
    function syncTitles(){for(const[kind,input]of [['build','assembly-name'],['design','design-name']])$(kind+'-card-title').textContent=$(input).value||(kind==='build'?'New assembly':'New design');}
    doc.addEventListener('input',syncTitles);doc.addEventListener('change',syncTitles);
    for(const dialog of [$('worksheet-save-dialog'),$('worksheet-new-dialog')])dialog.addEventListener('cancel',event=>{if(locked)event.preventDefault();});
    syncTitles();setScope(win.location.hash.slice(1));return{setScope,loadAll,share,syncTitles,records,active};
  }
  root.JunctionWorksheets={setup};
})(window);
