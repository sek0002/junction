/* Manual entries are independent stocks, even when they share a linked sequence. */
(function(root,factory){const api=factory(typeof module==='object'&&module.exports?require('./design-table.js'):root.DesignTable);if(typeof module==='object'&&module.exports)module.exports=api;else root.CustomUploads=api;})(typeof globalThis==='object'?globalThis:this,function(tables){
  'use strict';
  const fields=['name','concentration','location','plate','well','link','sequence'];
  const titles=['Name','Concentration ng/µL','Location','Plate','Well','Link','Sequence'];
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const blank=()=>Object.fromEntries(fields.map(key=>[key,'']));
  function paste(rows,text,start=rows.length,key='name'){
    const incoming=tables.parseDelimited(text);if(!incoming.length)return rows;
    const aliases={name:'name',concentration:'concentration','concentration ng/µl':'concentration','concentration ng/ul':'concentration','stock ng/µl':'concentration',location:'location',plate:'plate',plate_id:'plate',well:'well',link:'link',sequence:'sequence',upload:'sequence'};
    let columns=fields.slice(fields.indexOf(key));
    if(incoming[0].some(value=>value.trim().toLowerCase()==='name')){columns=incoming.shift().map(value=>{const field=aliases[value.trim().toLowerCase()];if(!field)throw Error('Unknown column: '+value);return field;});if(new Set(columns).size!==columns.length)throw Error('Repeated table column.');}
    if(start+incoming.length>1000)throw Error('Use up to 1,000 rows.');
    const copy=rows.map(row=>({...row}));
    incoming.forEach((values,index)=>{if(values.length>columns.length)throw Error('Too many pasted columns.');while(copy.length<=start+index)copy.push(blank());const row=copy[start+index];if(row.imported)throw Error('Add a new row to import another stock.');values.forEach((value,i)=>row[columns[i]]=value.trim());if(row.link&&row.sequence)throw Error('Use Link or Sequence in each row.');});return copy;
  }
  function payload(rows){return rows.filter(row=>!row.imported&&fields.some(key=>String(row[key]??'').trim())).map((row,index)=>{
    const result=Object.fromEntries(fields.map(key=>[key,String(row[key]??'').trim()]));
    if(!result.link&&!result.sequence)throw Error('Row '+(index+1)+': choose a link or add a sequence.');
    if(result.link&&result.sequence)throw Error('Row '+(index+1)+': use Link or Sequence.');
    result.concentration=result.concentration===''?null:Number(result.concentration);
    if(result.concentration!==null&&(!Number.isFinite(result.concentration)||result.concentration<=0))throw Error('Row '+(index+1)+': concentration must be positive.');
    return {...result,filename:row.filename||'',features:row.features||[]};
  });}
  function tsv(rows){const quote=value=>'"'+String(value??'').replace(/"/g,'""')+'"';return [titles,...rows.map(row=>fields.map(key=>row[key]))].map(row=>row.map(quote).join('\t')).join('\n');}
  function setup(win,doc,{api,fragments,onImported,notify}){
    const host=doc.getElementById('custom-upload-panel');let rows=[blank()],busy=false,parsing=0,requestId=win.crypto.randomUUID();
    const status=message=>host.querySelector('[data-custom-status]').textContent=message;
    const locked=()=>busy||parsing>0;
    function render(){
      requestId=win.crypto.randomUUID();
      host.innerHTML=`<div class="panel-heading"><h2>Custom upload</h2><div class="button-row"><button class="secondary compact" data-custom-add type="button">+ Row</button><button class="text-button" data-custom-copy type="button">Copy table</button><button class="text-button" data-custom-clear type="button">Clear</button></div></div><div class="table-scroll"><table class="custom-upload-table" data-managed-sort="true"><thead><tr>${titles.map((title,i)=>`<th>${i===6?'Upload / Sequence':title}${[3,4].includes(i)?'<small>Optional</small>':''}</th>`).join('')}<th></th></tr></thead><tbody>${rows.map((row,index)=>`<tr data-custom-row="${index}" ${row.imported?'class="custom-imported"':''}>${fields.map(key=>`<td>${key==='sequence'?`<textarea rows="2" data-key="sequence" aria-label="Sequence row ${index+1}" spellcheck="false" ${row.imported?'disabled':''}>${esc(row.sequence)}</textarea><label class="custom-file-label">${esc(row.filename||'GenBank / FASTA')}<input type="file" data-custom-file="${index}" aria-label="Upload sequence row ${index+1}" accept=".gb,.gbk,.genbank,.fa,.fasta,.fna" multiple ${row.imported?'disabled':''}></label>`:`<input data-key="${key}" aria-label="${esc(titles[fields.indexOf(key)])} row ${index+1}" value="${esc(row[key])}" ${key==='link'?'list="custom-link-options"':''} ${key==='concentration'?'inputmode="decimal"':''} ${row.imported?'disabled':''}>`}</td>`).join('')}<td>${row.imported?'<span class="custom-upload-ok" title="Imported stock">✓</span>':`<button class="text-button custom-remove" data-custom-remove="${index}" aria-label="Remove custom row ${index+1}" type="button">×</button>`}</td></tr>`).join('')}</tbody></table></div><datalist id="custom-link-options"></datalist><details><summary>Paste table</summary><textarea data-custom-paste rows="4" aria-label="Paste custom fragment table" placeholder="Name&#9;Concentration&#9;Location&#9;Plate&#9;Well&#9;Link&#9;Sequence"></textarea><button class="secondary compact" data-custom-apply type="button">Add rows</button></details><div class="button-row"><button id="custom-upload-import" class="primary" type="button">Import</button><span data-custom-status role="status"></span></div>`;
      updateLinks();setLocked();
      host.querySelector('[data-custom-add]').onclick=()=>{if(!locked()){rows.push(blank());render();}};
      host.querySelector('[data-custom-clear]').onclick=()=>{if(!locked()){rows=[blank()];render();}};
      host.querySelector('[data-custom-copy]').onclick=async()=>{try{await win.navigator.clipboard.writeText(tsv(rows));notify('Table copied');}catch{status('Clipboard unavailable.');}};
      host.querySelector('[data-custom-apply]').onclick=()=>{try{const start=rows.length===1&&fields.every(key=>!rows[0][key])?0:rows.length;rows=paste(rows,host.querySelector('[data-custom-paste]').value,start);render();}catch(error){status(error.message);}};
      host.querySelector('#custom-upload-import').onclick=commit;
      host.querySelectorAll('[data-custom-remove]').forEach(button=>button.onclick=()=>{if(locked())return;rows.splice(Number(button.dataset.customRemove),1);if(!rows.length)rows.push(blank());render();});
      host.querySelectorAll('[data-custom-row]').forEach(tr=>{
        const index=Number(tr.dataset.customRow),row=rows[index];
        tr.oninput=event=>{const key=event.target.dataset.key;if(!key||row.imported)return;row[key]=event.target.value;requestId=win.crypto.randomUUID();if(key==='sequence'){row.link='';row.filename='';row.features=[];tr.querySelector('[data-key="link"]').value='';}if(key==='link'&&row.link){row.sequence='';row.filename='';row.features=[];tr.querySelector('textarea').value='';}};
        tr.querySelector('[data-key="link"]').onfocus=updateLinks;
        tr.querySelector('[data-key="link"]').onchange=()=>{const id=row.link.match(/#(\d+)\)$/)?.[1],source=fragments().find(item=>item.id===Number(id));if(source&&!row.name){row.name=source.name;tr.querySelector('[data-key="name"]').value=row.name;}};
        tr.onpaste=event=>{const key=event.target.dataset.key,text=event.clipboardData?.getData('text/plain');if(!key||!text||locked()||row.imported)return;if(!text.includes('\t')&&(!/[\r\n]/.test(text)||key==='sequence'||key==='location'))return;event.preventDefault();try{rows=paste(rows,text,index,key);render();}catch(error){status(error.message);}};
        tr.querySelector('[data-custom-file]').onchange=event=>parseFiles(index,[...event.target.files]);
      });
    }
    function updateLinks(){host.querySelector('#custom-link-options').innerHTML=fragments().map(fragment=>`<option value="${esc(fragment.name)} (#${fragment.id})">${esc([fragment.location,fragment.plate_id,fragment.well].filter(Boolean).join(' · '))}${fragment.custom_metadata?.linked_fragment_id?' · Linked stock':''}</option>`).join('');}
    function setLocked(){host.querySelectorAll('input,textarea,button').forEach(el=>{el.disabled=locked()||!!el.closest('.custom-imported');});if(win.JunctionAccount?.user&&!win.JunctionAccount.allowed('can_upload'))host.querySelector('#custom-upload-import').disabled=true;}
    async function parseFiles(index,files){if(locked()||!files.length)return;parsing++;setLocked();status('Reading sequences…');try{
      const added=[];for(const file of files){const data=new FormData();data.append('file',file);const result=await api('/api/uploads/custom/parse',{method:'POST',body:data});for(const record of result.records)added.push({...blank(),name:record.name,sequence:record.sequence,features:record.features,filename:file.name});}
      if(rows.length-1+added.length>1000)throw Error('Use up to 1,000 rows.');const original=rows[index];added[0]={...original,...added[0],name:original.name||added[0].name,link:''};rows.splice(index,1,...added);
    }catch(error){status(error.message);parsing--;setLocked();return;}parsing--;render();}
    async function commit(){if(locked())return;let selected;try{selected=payload(rows);if(!selected.length)throw Error('Add a fragment first.');}catch(error){status(error.message);return;}
      busy=true;setLocked();status('Importing…');try{const result=await api('/api/uploads/custom',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rows:selected,request_id:requestId})});for(const row of rows)if(fields.some(key=>String(row[key]??'').trim()))row.imported=true;busy=false;render();status(`${result.count} imported${result.unchanged?' · '+result.unchanged+' existing':''}`);try{await onImported();}catch(error){notify('Imported. Refresh library: '+error.message);}}catch(error){busy=false;setLocked();status(error.message);}}
    render();return{refresh:updateLinks};
  }
  return{blank,paste,payload,tsv,setup};
});
