/* A row is one named combination; constants are template-derived and locked. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.DesignTable=api;})(typeof globalThis==='object'?globalThis:this,function(){
  'use strict';
  const dna=text=>String(text||'').split(/\r?\n/).filter(line=>!line.startsWith('>')).join('').replace(/\s/g,'').toUpperCase();
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function columns(design,context=[]){
    const result=[{key:'name',name:'Name',title:'Name',mode:'name'}];
    for(const entry of design.entries){
      if(entry.kind==='fragment'){
        const node=context.find(node=>node.id===entry.id);
        result.push({key:'fixed:'+entry.id,name:entry.name,title:entry.name,mode:'constant',value:node?.digest?.target||''});continue;
      }
      const sequence=dna(entry.sequence),sections=[...entry.sections].sort((a,b)=>a.start-b.start);let start=0,number=1;
      const add=(a,b,section)=>{if(a>=b)return;const name=section?.name||'Constant '+number++;
        result.push({key:section?.mode==='dynamic'?`${entry.id}:${a}:${b}`:`constant:${entry.id}:${a}:${b}`,name,title:entry.name+' / '+name,mode:section?.mode||'constant',value:sequence.slice(a,b)});};
      for(const section of sections){add(start,section.start);add(section.start,section.end,section);start=section.end;}
      add(start,sequence.length);
    }
    return result;
  }
  function parseDelimited(text){
    text=String(text||'').replace(/^\uFEFF/,'');const delimiter=text.includes('\t')?'\t':',';
    const rows=[];let row=[],cell='',quoted=false;
    for(let i=0;i<text.length;i++){
      const char=text[i];
      if(char==='"'){
        if(quoted&&text[i+1]==='"'){cell+='"';i++;}else if(quoted||!cell){quoted=!quoted;}else cell+=char;
      }else if(char===delimiter&&!quoted){row.push(cell);cell='';}
      else if((char==='\n'||char==='\r')&&!quoted){if(char==='\r'&&text[i+1]==='\n')i++;row.push(cell);if(row.some(value=>value.trim()))rows.push(row);row=[];cell='';}
      else cell+=char;
    }
    if(quoted)throw Error('Close the quoted CSV cell.');
    row.push(cell);if(row.some(value=>value.trim()))rows.push(row);return rows;
  }
  function applyPaste(rows,text,schema,startRow=rows.length,startKey='name'){
    const incoming=parseDelimited(text);if(!incoming.length)return rows;
    const compact=schema.filter(column=>column.mode!=='constant');let mapping=null;
    const alias=value=>String(value).trim().toLowerCase();
    if(['name','input name','construct name'].includes(alias(incoming[0][0]))){
      const headers=incoming.shift();mapping=headers.map(header=>{
        if(['name','input name','construct name'].includes(alias(header)))return schema[0];
        const matches=schema.filter(column=>[column.key,column.name,column.title].some(value=>alias(value)===alias(header)));
        if(matches.length!==1)throw Error('Unknown or ambiguous column: '+header);return matches[0];
      });
      if(new Set(mapping.map(column=>column.key)).size!==mapping.length)throw Error('Pasted headers repeat a column.');
    }
    const copy=rows.map(row=>({...row,dynamic_inputs:{...row.dynamic_inputs}}));
    if(startRow+incoming.length>384)throw Error('Use at most 384 table rows.');
    incoming.forEach((values,index)=>{
      let targets=mapping;
      if(!targets){
        if(startKey==='name'&&values.length===schema.length)targets=schema;
        else {const offset=compact.findIndex(column=>column.key===startKey);if(offset<0)throw Error('Constant cells are fixed.');targets=compact.slice(offset);}
      }
      if(values.length>targets.length)throw Error('Too many pasted cells for the table columns.');
      const position=startRow+index;
      while(copy.length<=position)copy.push({name:'Variant '+(copy.length+1),dynamic_inputs:{}});
      values.forEach((value,columnIndex)=>{
        const column=targets[columnIndex];
        if(column.mode==='constant'){
          if(value.trim()&&dna(value)!==column.value)throw Error(column.title+': the pasted Constant sequence differs from the template.');
        }else if(column.mode==='name')copy[position].name=value.trim();
        else copy[position].dynamic_inputs[column.key]=dna(value);
      });
    });
    return copy;
  }
  function templateTSV(schema){
    const quote=value=>'"'+String(value).replace(/"/g,'""')+'"';
    return [schema.map(column=>quote(schema.filter(other=>other.title===column.title).length>1?column.key:column.title)).join('\t'),schema.map(column=>quote(column.mode==='name'?'Example':column.value)).join('\t')].join('\n');
  }
  function create({getDesign,getContext,onChange,report}){
    const panel=document.getElementById('design-table-panel');let schema=[],lastStatus=null;
    const dynamic=()=>schema.filter(column=>column.mode==='dynamic');
    function changed(repaint=true){onChange();if(repaint)render();}
    function render(){
      const design=getDesign();if(!design)return;design.table_rows??=[];design.use_table??=false;
      schema=columns(design,getContext());const inputs=dynamic();
      panel.classList.toggle('hidden',!inputs.length&&!design.table_rows.length&&!design.use_table);
      panel.innerHTML=`<div class="panel-heading"><h2>Variant table</h2><div class="design-actions"><label class="design-table-toggle"><input id="design-table-enabled" type="checkbox" ${design.use_table?'checked':''}>Use rows</label><button type="button" id="design-table-add" class="secondary compact">+ Row</button><button type="button" id="design-table-reference" class="secondary compact">Reference row</button><button type="button" id="design-table-copy" class="text-button">Copy template</button><button type="button" id="design-table-clear" class="text-button">Clear rows</button></div></div><div id="design-table-overhangs" class="design-table-overhangs"></div><div class="table-scroll"><table id="design-input-table" data-managed-sort="true" class="design-input-table"><thead><tr>${schema.map(column=>`<th title="${esc(column.title)}">${esc(column.title)}<small>${column.mode==='constant'?'Constant · Locked':column.mode==='dynamic'?'Dynamic':''}</small></th>`).join('')}<th>Check</th><th></th></tr></thead><tbody>${design.table_rows.map((row,index)=>`<tr data-table-row="${index}">${schema.map(column=>`<td>${column.mode==='name'?`<input data-row="${index}" data-key="name" aria-label="Row ${index+1} name" maxlength="100" value="${esc(row.name)}">`:`<textarea rows="2" spellcheck="false" data-row="${index}" data-key="${esc(column.key)}" aria-label="Row ${index+1} ${esc(column.title)}" ${column.mode==='constant'?'readonly tabindex="-1"':''}>${esc(column.mode==='constant'?column.value:row.dynamic_inputs[column.key]||'')}</textarea>`}</td>`).join('')}<td data-table-status="${index}">—</td><td><button type="button" class="design-table-remove" data-remove-row="${index}" aria-label="Remove row ${index+1}">×</button></td></tr>`).join('')}</tbody></table></div><details class="design-table-paste"><summary>Paste rows</summary><textarea id="design-table-paste" rows="4" spellcheck="false" aria-label="Paste named variant rows" placeholder="${esc(['Name',...inputs.map(column=>column.name)].join('\t'))}\n${esc(['Sample 1',...inputs.map(()=> 'ACGT…')].join('\t'))}" title="Paste TSV or CSV: Name, then each Dynamic input. A full table with unchanged Constant columns is also accepted."></textarea><button type="button" id="design-table-apply" class="secondary compact">Add pasted rows</button></details><div id="design-table-error" class="reaction-warning" role="alert"></div>${design.table_rows.some(row=>Object.keys(row.dynamic_inputs).some(key=>!inputs.some(column=>column.key===key)))?'<button type="button" id="design-table-prune" class="text-button">Remove inputs for deleted regions</button>':''}`;
      panel.querySelector('#design-table-enabled').onchange=event=>{design.use_table=event.target.checked;changed();};
      panel.querySelector('#design-table-add').onclick=()=>add(false);
      panel.querySelector('#design-table-reference').onclick=()=>add(true);
      panel.querySelector('#design-table-clear').onclick=()=>{design.table_rows=[];design.use_table=false;changed();};
      panel.querySelector('#design-table-copy').onclick=async()=>{try{await navigator.clipboard.writeText(templateTSV(schema));report('Template copied');}catch{error('Clipboard unavailable. Paste Name and Dynamic sequences as TSV or CSV.');}};
      panel.querySelector('#design-table-apply').onclick=()=>{try{design.table_rows=applyPaste(design.table_rows,panel.querySelector('#design-table-paste').value,schema);design.use_table=true;changed();}catch(e){error(e.message);}};
      panel.querySelector('#design-table-prune')?.addEventListener('click',()=>{for(const row of design.table_rows)row.dynamic_inputs=Object.fromEntries(inputs.filter(column=>Object.hasOwn(row.dynamic_inputs,column.key)).map(column=>[column.key,row.dynamic_inputs[column.key]]));changed();});
      const table=panel.querySelector('#design-input-table');
      table.oninput=event=>{const input=event.target;if(input.dataset.row===undefined||input.readOnly)return;const row=design.table_rows[Number(input.dataset.row)];if(input.dataset.key==='name')row.name=input.value;else row.dynamic_inputs[input.dataset.key]=input.value;design.use_table=true;panel.querySelector('#design-table-enabled').checked=true;changed(false);};
      table.onpaste=event=>{const input=event.target,text=event.clipboardData?.getData('text/plain');if(!text||(!text.includes('\t')&&!/[\r\n]/.test(text))||input.dataset.row===undefined)return;event.preventDefault();try{if(input.readOnly)throw Error('Constant cells are fixed.');design.table_rows=applyPaste(design.table_rows,text,schema,Number(input.dataset.row),input.dataset.key);design.use_table=true;changed();}catch(e){error(e.message);}};
      table.onclick=event=>{const button=event.target.closest('[data-remove-row]');if(button){design.table_rows.splice(Number(button.dataset.removeRow),1);changed();}};
      setResult(lastStatus);
      function add(reference){if(design.table_rows.length>=384){error('Use at most 384 table rows.');return;}design.table_rows.push({name:'Variant '+(design.table_rows.length+1),dynamic_inputs:reference?Object.fromEntries(inputs.map(column=>[column.key,column.value])):{}});design.use_table=true;changed();}
    }
    function error(message){panel.querySelector('#design-table-error').textContent=message;}
    function setResult(result){
      lastStatus=result;if(!panel.querySelector('#design-table-overhangs'))return;
      const overhangs=result?.constant_overhangs||[];
      panel.querySelector('#design-table-overhangs').innerHTML=overhangs.length?'<strong>✓ Constant overhangs</strong> '+overhangs.map(item=>`<span>${esc(item.name)} <code>${esc(item.left_overhang)}</code> / <code>${esc(item.right_overhang)}</code></span>`).join(''):'';
      for(const cell of panel.querySelectorAll('[data-table-status]')){
        const status=result?.table_rows?.[Number(cell.dataset.tableStatus)];cell.textContent=status?(status.valid?'✓':'!'):'—';cell.className=status?(status.valid?'design-pass':'reaction-warning'):'';cell.title=status?.errors?.join(' ')||'';
      }
    }
    function refreshConstants(){
      schema=columns(getDesign(),getContext());
      for(const field of panel.querySelectorAll('textarea[readonly][data-key]')){
        const column=schema.find(column=>column.key===field.dataset.key);if(column)field.value=column.value;
      }
    }
    return{render,setResult,refreshConstants,clear(){lastStatus=null;setResult(null);}};
  }
  return {columns,parseDelimited,applyPaste,templateTSV,create};
});
