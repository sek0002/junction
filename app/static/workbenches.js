/* Named snapshots and local .junc downloads; sharing never publishes a file. */
(function(root){
  const icons={save:'<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h12l4 4v12a2 2 0 0 1-2 2Z"/><path d="M7 3v6h10V3M7 21v-8h10v8"/>',share:'<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m9 10 6-3M9 14l6 3"/>',new:'<path d="M14 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9ZM14 3v6h6M8 15h8M12 11v8"/>',open:'<path d="M3 9V6a2 2 0 0 1 2-2h5l3 3h6a2 2 0 0 1 2 2v2M3 9h6l2 3h10l-3 8H4L2 11a1.5 1.5 0 0 1 1-2Z"/>',close:'<path d="m6 6 12 12M18 6 6 18"/>',menu:'<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 7h8M8 11h8M8 15h4"/>'};
  const icon=type=>'<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true">'+icons[type]+'</svg>';
  function setup(win,doc,{api,flush,setCurrent,pause,resume,recommendedName,stats,download,notify}){
    const $=id=>doc.getElementById(id),list=$('workbench-list'),saveDialog=$('workbench-save-dialog'),newDialog=$('workbench-new-dialog');
    let items=[],current=null,locked=false,afterSaveNew=false,loadRevision=0;
    const element=(tag,text,className)=>{const n=doc.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n;};
    const date=value=>value?new Date(value).toLocaleString():'';
    const request=(url,body)=>api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
    function menu(open){$('workbench-floating-menu').hidden=!open;$('workbench-menu-toggle').setAttribute('aria-expanded',String(open));$('workbench-menu-toggle').innerHTML=icon(open?'close':'menu');}
    function lock(value){locked=value;for(const button of doc.querySelectorAll('[data-workbench-action]'))button.disabled=value;}
    function context(record){current=record;setCurrent(record?.id||null);$('workbench-current').textContent=record?.name||'Unsaved instance';$('workbench-save').title=record?'Save Workbench · '+record.name:'Save Workbench';}
    function render(){
      const query=$('workbench-search').value.trim().toLocaleLowerCase(),visible=items.filter(item=>(item.name+' '+item.notes).toLocaleLowerCase().includes(query));
      list.replaceChildren();$('workbench-count').textContent=String(items.length);
      if(!visible.length){list.append(element('p',items.length?'No matches':'No saved workbenches','empty-state'));return;}
      for(const item of visible){
        const card=element('article',undefined,'workbench-card'),title=element('h2',item.name),header=element('div',undefined,'panel-heading');header.append(title);
        if(item.id===current?.id)header.append(element('span','Current','badge neutral'));
        card.append(header);
        if(item.notes)card.append(element('p',item.notes,'workbench-notes'));
        const meta=element('dl',undefined,'workbench-metadata');
        for(const[label,value]of [['Saved',date(item.updated_at)],['Created',date(item.created_at)],['By',item.metadata.created_by],['Version',item.metadata.app_version],['Builds',item.metadata.builds],['Designs',item.metadata.designs],['Comparisons',item.metadata.comparisons],['Fragments',item.metadata.fragments],['Plasmids',item.metadata.plasmids],['Worksheets',item.metadata.worksheets||0]]){
          meta.append(element('dt',label),element('dd',String(value??'—')));
        }
        card.append(meta);const actions=element('div',undefined,'button-row');
        for(const[kind,label,handler]of [['open','Open '+item.name,()=>open(item)],['share','Share '+item.name+' (.junc)',()=>root.JunctionWorksheetController.share({kind:null,workbench:item.id})]]){
          const button=element('button',undefined,'icon-button');button.type='button';button.innerHTML=icon(kind);button.setAttribute('aria-label',label);button.title=label;button.disabled=kind==='open'&&item.id===current?.id;button.addEventListener('click',handler);actions.append(button);
        }
        if(item.metadata.automatic)actions.append(element('small','Recovery copy','muted'));
        card.append(actions);list.append(card);
      }
    }
    async function load(){
      const revision=++loadRevision;
      try{const result=await api('/api/workbenches');if(revision!==loadRevision)return;items=result.items;context(result.current);render();}
      catch(error){$('workbench-page-status').textContent=error.message;}
    }
    async function openSave({thenNew=false}={}){
      menu(false);afterSaveNew=thenNew;
      try{
        await flush();await load();$('workbench-save-name').value=current?.name||recommendedName()||'Workbench';$('workbench-save-notes').value=current?.notes||'';
        $('workbench-save-meta').textContent=stats();$('workbench-save-error').textContent='';saveDialog.showModal();$('workbench-save-name').focus();
      }catch(error){notify(error.message);}
    }
    function reload(view='home'){
      win.location.replace('/?instance='+Date.now()+'#'+view);
    }
    async function open(item){
      if(locked)return;lock(true);menu(false);
      try{await flush();pause();const result=await request('/api/workbenches/'+item.id+'/open');reload(result.view);}
      catch(error){resume();notify(error.message);lock(false);}
    }
    async function startNew(discard=false){
      if(locked)return;lock(true);menu(false);
      try{await flush();pause();await request('/api/workbenches/new',{discard_unsaved:discard});reload();}
      catch(error){resume();notify(error.message);lock(false);}
    }
    async function newInstance(){
      menu(false);
      try{await flush();await load();if(current)await startNew();else newDialog.showModal();}
      catch(error){notify(error.message);}
    }
    $('workbench-save-form').addEventListener('submit',async event=>{
      event.preventDefault();if(locked)return;lock(true);$('workbench-save-submit').disabled=true;$('workbench-save-error').textContent='';
      try{
        await flush();const saved=await request('/api/workbenches',{id:current?.id||null,name:$('workbench-save-name').value.trim(),notes:$('workbench-save-notes').value});
        context(saved);await root.JunctionWorksheetController?.loadAll();await flush();saveDialog.close();notify('Workbench saved');await load();
        lock(false);if(afterSaveNew){afterSaveNew=false;await startNew();}
      }catch(error){$('workbench-save-error').textContent=error.message;lock(false);}
      finally{$('workbench-save-submit').disabled=false;}
    });
    for(const[id,type]of [['workbench-save','save'],['workbench-share','share'],['workbench-new','new']])$(id).innerHTML=icon(type)+'<span class="bubble-all">All</span>';
    $('workbench-menu-toggle').addEventListener('click',()=>menu($('workbench-floating-menu').hidden));
    $('workbench-save').addEventListener('click',()=>openSave());
    $('workbench-share').addEventListener('click',()=>{menu(false);root.JunctionWorksheetController.share({kind:null});});
    $('workbench-new').addEventListener('click',newInstance);
    $('workbench-save-close').addEventListener('click',()=>saveDialog.close());
    $('workbench-new-cancel').addEventListener('click',()=>newDialog.close());
    $('workbench-new-save').addEventListener('click',()=>{newDialog.close();openSave({thenNew:true});});
    $('workbench-new-discard').addEventListener('click',()=>{newDialog.close();startNew(true);});
    $('workbench-search').addEventListener('input',render);
    $('workbench-import').addEventListener('change',async event=>{
      const file=event.target.files[0];if(!file)return;const data=new FormData();data.append('file',file);$('workbench-page-status').textContent='Importing…';
      try{let choice=$('instance-import-scope').value;const contents=JSON.parse(await file.text());if(choice==='auto')choice=contents.format==='junction-worksheet'?(contents.scope||'build'):'workbench';const url=choice==='workbench'?'/api/workbenches/import':'/api/worksheets/import?scope='+choice;const result=await api(url,{method:'POST',body:data});await load();await root.JunctionWorksheetController.loadAll();$('workbench-page-status').textContent='Imported '+result.name;}
      catch(error){$('workbench-page-status').textContent=error.message;}finally{event.target.value='';}
    });
    doc.addEventListener('pointerdown',event=>{if(!event.target.closest('#workbench-floating'))menu(false);});
    $('workbench-floating').addEventListener('keydown',event=>{
      const buttons=[...$('workbench-floating-menu').querySelectorAll('button')];
      if(event.key==='Escape'){menu(false);$('workbench-menu-toggle').focus();}
      if(['ArrowUp','ArrowDown'].includes(event.key)){event.preventDefault();menu(true);const index=buttons.indexOf(doc.activeElement),next=event.key==='ArrowUp'?(index+1)%buttons.length:(index-1+buttons.length)%buttons.length;buttons[next]?.focus();}
    });
    for(const dialog of [saveDialog,newDialog])dialog.addEventListener('cancel',event=>{if(locked)event.preventDefault();});
    menu(false);doc.body.classList.add('workbench-ready');
    return {load,context:record=>context(record),openSave};
  }
  root.JunctionWorkbenches={setup};
})(window);
