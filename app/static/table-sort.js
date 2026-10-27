/* Sort the existing row nodes so edits, selection and attached handlers survive. */
(function(root){
  const collator=new Intl.Collator(undefined,{numeric:true,sensitivity:'base'}),states=new WeakMap();
  function parse(value){
    if(typeof value==='number')return Number.isFinite(value)?value:null;
    const text=String(value??'').trim();if(!text||/^(?:—|–|-|n\/a|unknown)$/i.test(text))return null;
    const numeric=text.replace(/,/g,'').match(/^[<>]?\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)\s*(?:%|bp|ng|pmol|fmol|µl|ul|ng\/(?:µl|ul))?$/i);
    return numeric&&Number.isFinite(Number(numeric[1]))?Number(numeric[1]):text;
  }
  function compare(a,b,direction){
    if(a===null)return b===null?0:1;if(b===null)return -1;
    return direction*(typeof a==='number'&&typeof b==='number'?a-b:collator.compare(String(a),String(b)));
  }
  function cellValue(cell){
    if(!cell)return null;
    if(cell.dataset.sortValue!==undefined)return parse(cell.dataset.sortValue);
    const field=cell.querySelector('input:not([type="checkbox"]):not([type="hidden"]),select,textarea');
    if(field)return parse(field.value);
    const quantity=cell.querySelector('[data-sort-value]');if(quantity)return parse(quantity.dataset.sortValue);
    const primary=Array.from(cell.childNodes||[]).filter(node=>node.nodeType===3).map(node=>node.textContent).join(' ').trim();
    return parse(primary||cell.querySelector('b,strong')?.textContent||cell.textContent);
  }
  function orderRows(rows,column,direction){
    return rows.map((row,index)=>({row,index,value:cellValue(row.cells[column])})).sort((a,b)=>compare(a.value,b.value,direction)||a.index-b.index).map(entry=>entry.row);
  }
  function apply(table){
    const state=states.get(table);if(!state)return;
    for(const body of table.tBodies){
      const rows=Array.from(body.rows),sortable=rows.filter(row=>!Array.from(row.cells).some(cell=>cell.colSpan>1)),pinned=rows.filter(row=>!sortable.includes(row));
      const ordered=[...orderRows(sortable,state.column,state.direction),...pinned];
      if(ordered.some((row,index)=>row!==rows[index]))body.append(...ordered);
    }
    for(const th of table.tHead?.rows[0]?.cells||[]){
      const active=th.cellIndex===state.column;if(th.querySelector('[data-table-sort]'))th.setAttribute('aria-sort',active?(state.direction===1?'ascending':'descending'):'none');
    }
  }
  function enhance(table){
    if(table.dataset.managedSort||table.querySelector('[data-inventory-sort]'))return;
    const headers=table.tHead?.rows[0]?.cells;if(!headers)return;
    for(const th of headers){
      if(th.colSpan>1||th.querySelector('input,select,a,button'))continue;
      const label=th.textContent.trim();if(!label)continue;
      th.setAttribute('scope','col');th.setAttribute('aria-sort','none');
      const button=table.ownerDocument.createElement('button');button.type='button';button.className='table-sort-header';button.dataset.tableSort=th.cellIndex;button.textContent=label;
      const icon=table.ownerDocument.createElement('span');icon.className='table-sort-indicator';icon.setAttribute('aria-hidden','true');button.append(icon);th.replaceChildren(button);
      button.onclick=()=>{const current=states.get(table);states.set(table,{column:th.cellIndex,direction:current?.column===th.cellIndex?-current.direction:1});apply(table);};
    }
    apply(table);
  }
  function setup(doc){
    let queued=false;
    const refresh=()=>{queued=false;doc.querySelectorAll('table').forEach(enhance);};
    const schedule=()=>{if(!queued){queued=true;root.requestAnimationFrame(refresh);}};
    refresh();new root.MutationObserver(schedule).observe(doc.body,{childList:true,subtree:true});
    doc.addEventListener('change',event=>{const table=event.target.closest('table');if(table&&states.has(table))apply(table);});
  }
  const api={parse,compare,cellValue,orderRows,enhance,apply,setup};
  if(typeof module==='object'&&module.exports)module.exports=api;
  else {root.TableSort=api;if(root.document.readyState==='loading')root.document.addEventListener('DOMContentLoaded',()=>setup(root.document));else setup(root.document);}
})(typeof window==='object'?window:globalThis);
